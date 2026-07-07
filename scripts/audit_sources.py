#!/usr/bin/env python3
"""审查每周简报使用的来源 URL。

本脚本检查来源卫生状况，不单独证明事实真伪。它会检查 URL 是否可达或明确访问受限，
并对来源域名分类，最后写入结构化审查日志。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


OFFICIAL_HOST_KEYWORDS = [
    "apple.com",
    "microsoft.com",
    "abc.xyz",
    "google.com",
    "googleblog.com",
    "blog.google",
    "ai.google.dev",
    "aboutamazon.com",
    "amazon.com",
    "meta.com",
    "fb.com",
    "nvidia.com",
    "tesla.com",
    "samsung.com",
    "skhynix.com",
    "tsmc.com",
    "sec.gov",
    "essilorluxottica.com",
]

TIER1_MEDIA_HOST_KEYWORDS = [
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "nikkei.com",
    "cnbc.com",
    "theinformation.com",
    "caixin.com",
]

TRADE_MEDIA_HOST_KEYWORDS = [
    "tomshardware.com",
    "techcrunch.com",
    "thestreet.com",
    "businessinsider.com",
    "aljazeera.com",
    "cbsnews.com",
    "theguardian.com",
    "prnewswire.com",
    "top500.org",
]

ACCESS_LIMITED_STATUSES = {401, 403, 429}
OK_STATUSES = set(range(200, 400)) | ACCESS_LIMITED_STATUSES


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_markdown_urls(markdown: str) -> set[str]:
    urls = set(re.findall(r"\[[^\]]+\]\((https?://[^)]+)\)", markdown))
    urls.update(re.findall(r"(?<!\()https?://[^\s)>\"]+", markdown))
    return {url.rstrip(".,;") for url in urls}


def collect_urls(report_path: Path, baseline_path: Path | None) -> list[str]:
    urls = extract_markdown_urls(report_path.read_text(encoding="utf-8"))
    if baseline_path and baseline_path.exists():
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        for source in data.get("sources", []):
            if isinstance(source, str) and source.startswith(("http://", "https://")):
                urls.add(source)
        for edge in data.get("edges", []):
            for source in edge.get("sources", []):
                if isinstance(source, str) and source.startswith(("http://", "https://")):
                    urls.add(source)
    return sorted(urls)


def classify_host(host: str) -> str:
    host = host.lower()
    if any(host == key or host.endswith("." + key) for key in OFFICIAL_HOST_KEYWORDS):
        return "official_or_regulatory"
    if any(host == key or host.endswith("." + key) for key in TIER1_MEDIA_HOST_KEYWORDS):
        return "tier1_media"
    if any(host == key or host.endswith("." + key) for key in TRADE_MEDIA_HOST_KEYWORDS):
        return "trade_or_press_media"
    return "unclassified"


def probe_url(url: str, timeout: int) -> dict[str, object]:
    parsed = urllib.parse.urlparse(url)
    result: dict[str, object] = {
        "url": url,
        "scheme": parsed.scheme,
        "host": parsed.netloc.lower(),
        "source_class": classify_host(parsed.netloc),
        "status": None,
        "reachable": False,
        "access_limited": False,
        "content_verified": False,
        "requires_manual_verification": False,
        "error": None,
    }
    if parsed.scheme != "https":
        result["error"] = "non_https_url"
        return result

    context = ssl.create_default_context()
    headers = {
        "User-Agent": "weekly-tech-brief-source-audit/1.0",
        "Accept": "text/html,application/pdf,*/*",
    }
    request = urllib.request.Request(url, method="HEAD", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            result["status"] = response.status
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
    except Exception:
        request = urllib.request.Request(url, method="GET", headers={**headers, "Range": "bytes=0-2048"})
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                result["status"] = response.status
        except urllib.error.HTTPError as exc:
            result["status"] = exc.code
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            return result

    status = int(result["status"] or 0)
    result["reachable"] = status in OK_STATUSES
    result["access_limited"] = status in ACCESS_LIMITED_STATUSES
    result["content_verified"] = result["reachable"] and not result["access_limited"]
    result["requires_manual_verification"] = result["access_limited"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    report_path = Path(args.report)
    baseline_path = Path(args.baseline) if args.baseline else None
    urls = collect_urls(report_path, baseline_path)
    audited = [probe_url(url, args.timeout) for url in urls]
    summary = {
        "total": len(audited),
        "reachable": sum(1 for item in audited if item["reachable"]),
        "access_limited": sum(1 for item in audited if item["access_limited"]),
        "unclassified": sum(1 for item in audited if item["source_class"] == "unclassified"),
        "errors": sum(1 for item in audited if item["error"] or not item["reachable"]),
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report": args.report,
        "baseline": args.baseline,
        "report_sha256": sha256_file(report_path),
        "baseline_sha256": sha256_file(baseline_path) if baseline_path else None,
        "audited_urls": urls,
        "summary": summary,
        "sources": audited,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    hard_failures = [item for item in audited if not item["reachable"] and not item["access_limited"]]
    if args.strict and hard_failures:
        print(f"错误：{len(hard_failures)} 个来源 URL 未通过可达性检查", file=sys.stderr)
        raise SystemExit(1)
    print(
        "来源审查通过 "
        f"total={summary['total']} "
        f"reachable={summary['reachable']} "
        f"access_limited={summary['access_limited']} "
        f"unclassified={summary['unclassified']}"
    )


if __name__ == "__main__":
    main()

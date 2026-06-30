#!/usr/bin/env python3
"""Audit source URLs used by a weekly brief.

This script verifies source hygiene, not factual truth by itself. It checks that
URLs are reachable or explicitly access-limited, classifies source domains, and
writes a structured audit file for review.
"""

from __future__ import annotations

import argparse
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
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    urls = collect_urls(Path(args.report), Path(args.baseline) if args.baseline else None)
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
        "summary": summary,
        "sources": audited,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    hard_failures = [item for item in audited if not item["reachable"] and not item["access_limited"]]
    if args.strict and hard_failures:
        print(f"ERROR: {len(hard_failures)} source URLs failed reachability checks", file=sys.stderr)
        raise SystemExit(1)
    print(f"source_audit_ok total={summary['total']} reachable={summary['reachable']} access_limited={summary['access_limited']} unclassified={summary['unclassified']}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""审查每周简报使用的来源 URL 和核心事实 claim。

本脚本会检查 URL 是否可达或明确访问受限、来源域名分类、年度产品关系图来源是否
纳入审计，并对带有 claim_keywords 的结构化事实做关键词匹配。关键词匹配不能替代
人工事实判断，但能拦截“来源链接存在却完全不支持该事实”的常见错误。
"""

from __future__ import annotations

import argparse
import gzip
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
    "xbox.com",
    "abc.xyz",
    "google.com",
    "googleblog.com",
    "blog.google",
    "ai.google.dev",
    "aboutamazon.com",
    "amazon.com",
    "meta.com",
    "fb.com",
    "atmeta.com",
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


def collect_urls(report_path: Path, baseline_path: Path | None, product_graph_path: Path | None = None) -> list[str]:
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
    if product_graph_path and product_graph_path.exists():
        data = json.loads(product_graph_path.read_text(encoding="utf-8"))
        for section in ("companies", "relationships", "product_nodes", "product_edges"):
            for item in data.get(section, []):
                for source in item.get("official_sources", []):
                    if isinstance(source, str) and source.startswith(("http://", "https://")):
                        urls.add(source)
    return sorted(urls)


def collect_claims(baseline_path: Path | None) -> list[dict[str, object]]:
    if not baseline_path or not baseline_path.exists():
        return []
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    claims: list[dict[str, object]] = []
    for edge in data.get("edges", []):
        keywords = edge.get("claim_keywords", [])
        if not keywords:
            continue
        claims.append(
            {
                "claim_id": edge.get("edge_id"),
                "scope": "weekly_supply_edge",
                "description": edge.get("product_or_service"),
                "source_urls": edge.get("sources", []),
                "keywords": keywords,
                "min_keyword_matches": edge.get("min_keyword_matches", min(2, len(keywords))),
                "required": edge.get("claim_check_required", True),
            }
        )
    return claims


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


def fetch_text(url: str, timeout: int) -> str:
    context = ssl.create_default_context()
    attempts = [
        {
            "User-Agent": "Mozilla/5.0 weekly-tech-brief-source-audit/1.0",
            "Accept": "text/html,application/pdf,text/plain,*/*",
            "Accept-Encoding": "identity",
            "Range": "bytes=0-262143",
        },
        {
            "User-Agent": "Mozilla/5.0 weekly-tech-brief-source-audit/1.0",
            "Accept": "text/html,application/pdf,text/plain,*/*",
            "Accept-Encoding": "identity",
        },
    ]
    raw = b""
    encoding = ""
    for headers in attempts:
        request = urllib.request.Request(url, method="GET", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                raw = response.read(262144)
                encoding = response.headers.get("Content-Encoding", "")
                break
        except Exception:
            continue
    if not raw:
        return ""
    if encoding.lower() == "gzip":
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    text = raw.decode("utf-8", errors="ignore")
    text = re.sub(r"<(script|style).*?</\1>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).lower()


def check_claims(
    claims: list[dict[str, object]],
    audited: list[dict[str, object]],
    timeout: int,
) -> list[dict[str, object]]:
    source_by_url = {str(item["url"]): item for item in audited}
    text_cache: dict[str, str] = {}
    checked: list[dict[str, object]] = []
    for claim in claims:
        keywords = [str(keyword).lower() for keyword in claim.get("keywords", [])]
        min_matches = int(claim.get("min_keyword_matches", min(2, len(keywords))) or 1)
        url_results: list[dict[str, object]] = []
        best_count = 0
        best_keywords: list[str] = []
        has_access_limited_source = False
        for url in claim.get("source_urls", []):
            url = str(url)
            source = source_by_url.get(url, {})
            has_access_limited_source = has_access_limited_source or bool(source.get("access_limited"))
            if url not in text_cache:
                text_cache[url] = fetch_text(url, timeout)
            text = text_cache[url]
            matched_keywords = [keyword for keyword in keywords if keyword and keyword in text]
            if len(matched_keywords) > best_count:
                best_count = len(matched_keywords)
                best_keywords = matched_keywords
            url_results.append(
                {
                    "url": url,
                    "status": source.get("status"),
                    "access_limited": source.get("access_limited", False),
                    "matched_keywords": matched_keywords,
                }
            )
        matched = best_count >= min_matches
        requires_manual_verification = not matched and has_access_limited_source
        required = bool(claim.get("required", True))
        checked.append(
            {
                **claim,
                "matched": matched,
                "requires_manual_verification": requires_manual_verification,
                "failed": required and not matched and not requires_manual_verification,
                "best_match_count": best_count,
                "best_matched_keywords": best_keywords,
                "url_results": url_results,
            }
        )
    return checked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--product-graph")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    report_path = Path(args.report)
    baseline_path = Path(args.baseline) if args.baseline else None
    product_graph_path = Path(args.product_graph) if args.product_graph else None
    urls = collect_urls(report_path, baseline_path, product_graph_path)
    audited = [probe_url(url, args.timeout) for url in urls]
    claim_checks = check_claims(collect_claims(baseline_path), audited, args.timeout)
    summary = {
        "total": len(audited),
        "reachable": sum(1 for item in audited if item["reachable"]),
        "access_limited": sum(1 for item in audited if item["access_limited"]),
        "unclassified": sum(1 for item in audited if item["source_class"] == "unclassified"),
        "errors": sum(1 for item in audited if item["error"] or not item["reachable"]),
        "claim_total": len(claim_checks),
        "claim_matched": sum(1 for item in claim_checks if item["matched"]),
        "claim_manual": sum(1 for item in claim_checks if item["requires_manual_verification"]),
        "claim_failed": sum(1 for item in claim_checks if item["failed"]),
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report": args.report,
        "baseline": args.baseline,
        "product_graph": args.product_graph,
        "report_sha256": sha256_file(report_path),
        "baseline_sha256": sha256_file(baseline_path) if baseline_path else None,
        "product_graph_sha256": sha256_file(product_graph_path) if product_graph_path else None,
        "audited_urls": urls,
        "summary": summary,
        "sources": audited,
        "claim_checks": claim_checks,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    hard_failures = [item for item in audited if not item["reachable"] and not item["access_limited"]]
    if args.strict and hard_failures:
        print(f"错误：{len(hard_failures)} 个来源 URL 未通过可达性检查", file=sys.stderr)
        raise SystemExit(1)
    claim_failures = [item for item in claim_checks if item["failed"]]
    if args.strict and claim_failures:
        print(f"错误：{len(claim_failures)} 个核心事实 claim 未通过关键词匹配", file=sys.stderr)
        raise SystemExit(1)
    print(
        "来源审查通过 "
        f"total={summary['total']} "
        f"reachable={summary['reachable']} "
        f"access_limited={summary['access_limited']} "
        f"unclassified={summary['unclassified']} "
        f"claim_failed={summary['claim_failed']}"
    )


if __name__ == "__main__":
    main()

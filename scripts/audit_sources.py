#!/usr/bin/env python3
"""审查每周简报使用的来源 URL 和核心事实 claim。

本脚本会检查 URL 是否可达或明确访问受限、来源域名分类、年度产品关系图来源是否
纳入审计，并对带有 claim_keywords 的结构化事实做关键词匹配。关键词匹配不能替代
人工事实判断，但能拦截“来源链接存在却完全不支持该事实”的常见错误。
本脚本不核验首次公开时间、财报期间或网页历史版本；不得以 HTTP/关键词通过
替代 validate_point_in_time.py 与 docs/point_in_time_policy.md 的逐条复核。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


OFFICIAL_HOST_KEYWORDS = [
    "apple.com",
    "microsoft.com",
    "github.blog",
    "xbox.com",
    "abc.xyz",
    "google.com",
    "googleblog.com",
    "blog.google",
    "ai.google.dev",
    "aboutamazon.com",
    "amazon.com",
    "meta.com",
    "research.meta.ai",
    "fb.com",
    "atmeta.com",
    "nvidia.com",
    "tesla.com",
    "openai.com",
    "anthropic.com",
    "claude.com",
    "samsung.com",
    "skhynix.com",
    "tsmc.com",
    "sec.gov",
    "justice.gov",
    "ftc.gov",
    "nhtsa.gov",
    "aisi.gov.uk",
    "metr.org",
    "essilorluxottica.com",
    "ec.europa.eu",
    "curia.europa.eu",
    "motir.go.kr",
    "mn8.com",
    "leginfo.legislature.ca.gov",
    "gov.ca.gov",
    "d-matrix.ai",
    "fortum.com",
    "googlecloudpresscorner.com",
]

TIER1_MEDIA_HOST_KEYWORDS = [
    "focustaiwan.tw",
    "channelnewsasia.com",
    "apnews.com",
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "nikkei.com",
    "cnbc.com",
    "theinformation.com",
    "caixin.com",
    "axios.com",
    "barrons.com",
    "cna.com.tw",
]

TRADE_MEDIA_HOST_KEYWORDS = [
    "finance.yahoo.com",
    "tomshardware.com",
    "techcrunch.com",
    "thestreet.com",
    "businessinsider.com",
    "aljazeera.com",
    "cbsnews.com",
    "theguardian.com",
    "prnewswire.com",
    "top500.org",
    "boursorama.com",
    "marketscreener.com",
    "macrumors.com",
    "electrek.co",
    "globalnews.ca",
    "iclg.com",
    "news.cision.com",
    "tech.yahoo.com",
    "law360.com",
    "nasdaq.com",
    "investing.com",
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
    if host == "newsmediaalliance.org" or host.endswith(".newsmediaalliance.org"):
        return "industry_association_statement"
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

    headers = {
        "User-Agent": "weekly-tech-brief-source-audit/1.0",
        "Accept": "text/html,application/pdf,*/*",
    }
    attempts = [
        ("HEAD", headers),
        ("GET", {**headers, "Range": "bytes=0-2048"}),
        ("GET", {**headers, "Range": "bytes=0-2048"}),
    ]
    last_error: Exception | None = None
    for index, (method, request_headers) in enumerate(attempts):
        request = urllib.request.Request(url, method=method, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
                result["status"] = response.status
            break
        except urllib.error.HTTPError as exc:
            result["status"] = exc.code
            break
        except Exception as exc:
            last_error = exc
            if index < len(attempts) - 1:
                time.sleep(0.5 * (index + 1))

    # A different TLS client can recover a transport failure, not an HTTP denial.
    if result["status"] is None and isinstance(last_error, urllib.error.URLError) and isinstance(last_error.reason, (ssl.SSLError, TimeoutError)):
        result["prior_transport_error"] = f"{type(last_error).__name__}: {last_error}"
        try:
            fallback = subprocess.run(
                ["curl", "--location", "--max-time", str(timeout), "--silent", "--show-error",
                 "--output", "/dev/null", "--write-out", "%{http_code}", url],
                capture_output=True, text=True, timeout=timeout + 2, check=False,
            )
            result["fallback_transport"] = "curl"
            result["fallback_returncode"] = fallback.returncode
            if fallback.returncode == 0 and re.fullmatch(r"[1-5][0-9]{2}", fallback.stdout.strip()):
                result["status"] = int(fallback.stdout.strip())
            else:
                result["fallback_error"] = fallback.stderr.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["fallback_error"] = f"{type(exc).__name__}: {exc}"
    if result["status"] is None:
        result["error"] = f"{type(last_error).__name__}: {last_error}"
        return result

    status = int(result["status"] or 0)
    result["reachable"] = status in OK_STATUSES
    result["access_limited"] = status in ACCESS_LIMITED_STATUSES
    result["content_verified"] = result["reachable"] and not result["access_limited"]
    result["requires_manual_verification"] = result["access_limited"]
    return result


def fetch_text(url: str, timeout: int) -> str:
    context = ssl.create_default_context()
    audit_user_agent = "Mozilla/5.0 weekly-tech-brief-source-audit/1.0"
    browser_user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36"
    )
    attempts = [
        {
            "User-Agent": audit_user_agent,
            "Accept": "text/html,application/pdf,text/plain,*/*",
            "Accept-Encoding": "identity",
            "Range": "bytes=0-262143",
        },
        {
            "User-Agent": audit_user_agent,
            "Accept": "text/html,application/pdf,text/plain,*/*",
            "Accept-Encoding": "identity",
        },
        {
            "User-Agent": browser_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,*/*",
            "Accept-Encoding": "identity",
        },
        {
            "User-Agent": browser_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,*/*",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
        },
    ]
    raw = b""
    encoding = ""
    for index, headers in enumerate(attempts):
        request = urllib.request.Request(url, method="GET", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                raw = response.read(1048576)
                encoding = response.headers.get("Content-Encoding", "")
                if raw:
                    break
        except Exception:
            pass
        if index < len(attempts) - 1:
            time.sleep(0.5 * (index + 1))
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
    text_cache: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    source_by_url = {str(item["url"]): item for item in audited}
    if text_cache is None:
        text_cache = {}
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
            text_fetch_retried = False
            if len(matched_keywords) < min_matches and not source.get("access_limited"):
                text_fetch_retried = True
                refreshed_text = fetch_text(url, timeout)
                if refreshed_text:
                    text = refreshed_text
                    text_cache[url] = refreshed_text
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
                    "text_fetch_retried": text_fetch_retried,
                    "text_fetch_failed": not bool(text),
                    "text_length": len(text),
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


def reusable_audit(path: Path, report: Path, baseline: Path | None,
                   product: Path | None, urls: list[str], claims: list[dict]) -> dict:
    old = json.loads(path.read_text(encoding="utf-8"))
    at = datetime.fromisoformat(old["generated_at"].replace("Z", "+00:00"))
    if at.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - at).total_seconds() <= 900:
        raise ValueError("Resume audit must be from the preceding 15 minutes")
    for key, source in (("report_sha256", report), ("baseline_sha256", baseline), ("product_graph_sha256", product)):
        if old.get(key) != (sha256_file(source) if source else None):
            raise ValueError("Resume audit input changed: " + key)
    if old.get("audited_urls") != urls or [s.get("url") for s in old.get("sources", [])] != urls:
        raise ValueError("Resume audit URL inventory changed")
    prior_claims = old.get("claim_checks", [])
    if len(prior_claims) != len(claims) or any(
        any(prior.get(k) != value for k, value in claim.items())
        for prior, claim in zip(prior_claims, claims)
    ):
        raise ValueError("Resume audit claim definitions changed")
    return old


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--product-graph")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--resume-audit", type=Path, help="Reuse only unchanged successful checks from an audit less than 15 minutes old")
    args = parser.parse_args()

    report_path = Path(args.report)
    baseline_path = Path(args.baseline) if args.baseline else None
    product_graph_path = Path(args.product_graph) if args.product_graph else None
    urls = collect_urls(report_path, baseline_path, product_graph_path)
    claims = collect_claims(baseline_path)
    old = reusable_audit(args.resume_audit, report_path, baseline_path, product_graph_path, urls, claims) if args.resume_audit else None
    previous_sources = {s["url"]: s for s in old["sources"]} if old else {}
    previous_claims = {c["claim_id"]: c for c in old["claim_checks"]} if old else {}
    audited = []
    reused_urls = []
    for url in urls:
        previous = previous_sources.get(url)
        if previous and previous.get("reachable") is True and not previous.get("error"):
            audited.append({**previous, "source_class": classify_host(urllib.parse.urlparse(url).netloc)})
            reused_urls.append(url)
        else:
            audited.append(probe_url(url, args.timeout))
    claim_checks = []
    reused_claims = []
    text_cache = {}
    for claim in claims:
        previous = previous_claims.get(claim["claim_id"])
        if previous and previous.get("matched") is True and previous.get("failed") is False and set(claim["source_urls"]) <= set(reused_urls):
            claim_checks.append(previous)
            reused_claims.append(claim["claim_id"])
        else:
            claim_checks.extend(check_claims([claim], audited, args.timeout, text_cache))
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
    if old:
        payload["resume"] = {"path": str(args.resume_audit), "sha256": sha256_file(args.resume_audit),
                             "previous_generated_at": old["generated_at"], "reused_urls": reused_urls,
                             "reused_claims": reused_claims,
                             "note": "Unchanged recent successful checks reused; failures re-probed, not overwritten as success."}
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

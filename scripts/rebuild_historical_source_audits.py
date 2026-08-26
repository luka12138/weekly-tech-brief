#!/usr/bin/env python3
"""Re-audit historical reports with de-duplicated URL probes and explicit cache fallback."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit_sources import (
    check_claims,
    collect_claims,
    collect_urls,
    probe_url,
    sha256_file,
)
from rebuild_historical_obsidian_graphs import ROOT, load_snapshot, report_snapshots
from validate_historical_briefs import write_snapshot


def claim_key(claim: dict[str, Any]) -> str:
    payload = {
        "claim_id": claim.get("claim_id"),
        "source_urls": claim.get("source_urls", []),
        "keywords": claim.get("keywords", []),
        "min_keyword_matches": claim.get("min_keyword_matches"),
        "required": claim.get("required", True),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def load_audit_cache(log_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    source_cache: dict[str, dict[str, Any]] = {}
    claim_cache: dict[str, dict[str, Any]] = {}
    for path in sorted(log_dir.glob("*_source_audit.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        generated_at = payload.get("generated_at")
        for source in payload.get("sources", []):
            if source.get("reachable") and not source.get("error"):
                source_cache[str(source["url"])] = {
                    **source,
                    "cache_audit": path.name,
                    "cache_generated_at": generated_at,
                }
        for claim in payload.get("claim_checks", []):
            if (claim.get("matched") or claim.get("requires_manual_verification")) and not claim.get("failed"):
                claim_cache[claim_key(claim)] = {
                    **claim,
                    "cache_audit": path.name,
                    "cache_generated_at": generated_at,
                }
    return source_cache, claim_cache


def can_reuse_source_cache(
    live_result: dict[str, Any],
    cached_result: dict[str, Any] | None,
    allow_cache_fallback: bool,
) -> bool:
    """Only transport failures qualify; HTTP failures such as 404 never do."""

    return bool(allow_cache_fallback and cached_result and live_result.get("error"))


def can_reuse_claim_cache(
    claim: dict[str, Any],
    live_results: dict[str, dict[str, Any]],
    cached_claim: dict[str, Any] | None,
    allow_cache_fallback: bool,
) -> bool:
    transient_source_failure = any(
        live_results.get(str(url), {}).get("live_probe_error")
        for url in claim.get("source_urls", [])
    )
    return bool(allow_cache_fallback and cached_claim and transient_source_failure)


def main() -> None:
    parser = argparse.ArgumentParser(description="批量重建历史来源审计日志。")
    parser.add_argument("--dates", nargs="*", help="仅处理指定报告日期；默认全部")
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument(
        "--allow-cache-fallback",
        action="store_true",
        help="实时网络失败时，允许复用此前同 URL 或同 claim 的成功审计并写明来源",
    )
    args = parser.parse_args()
    selected = set(args.dates) if args.dates else None
    source_cache, claim_cache = load_audit_cache(ROOT / "logs")
    periods: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="weekly-brief-audits-") as directory:
        temp_root = Path(directory)
        all_urls: set[str] = set()
        for report_date, commit in report_snapshots(selected):
            baseline_path = temp_root / f"{report_date}_supply.json"
            product_path = temp_root / f"{report_date}_product.json"
            write_snapshot(baseline_path, load_snapshot(commit, "state/supply_graph_baseline.json"))
            write_snapshot(product_path, load_snapshot(commit, f"state/product_relationships_{report_date[:4]}.json"))
            report_path = ROOT / "reports" / f"{report_date}_weekly_morning_brief.md"
            urls = collect_urls(report_path, baseline_path, product_path)
            all_urls.update(urls)
            periods.append(
                {
                    "date": report_date,
                    "commit": commit,
                    "report": report_path,
                    "baseline": baseline_path,
                    "product": product_path,
                    "urls": urls,
                }
            )

        live_results: dict[str, dict[str, Any]] = {}
        cache_reused = 0
        for index, url in enumerate(sorted(all_urls), 1):
            result = probe_url(url, args.timeout)
            cached = source_cache.get(url)
            if can_reuse_source_cache(result, cached, args.allow_cache_fallback):
                result = {
                    **cached,
                    "cache_fallback": True,
                    "live_probe_error": result.get("error"),
                }
                result.pop("cache_audit", None)
                cache_reused += 1
            live_results[url] = result
            if index % 25 == 0 or index == len(all_urls):
                print(f"URL 审计进度：{index}/{len(all_urls)} cache_fallback={cache_reused}", flush=True)

        text_cache: dict[str, str] = {}
        failed_periods: list[str] = []
        for period in periods:
            audited = [live_results[url] for url in period["urls"]]
            claims = collect_claims(period["baseline"])
            claim_checks = check_claims(claims, audited, args.timeout, text_cache)
            claim_cache_reused = 0
            for index, claim in enumerate(claim_checks):
                if not claim.get("failed"):
                    continue
                cached = claim_cache.get(claim_key(claim))
                if can_reuse_claim_cache(claim, live_results, cached, args.allow_cache_fallback):
                    claim_checks[index] = {
                        **cached,
                        "cache_fallback": True,
                        "live_check": claim,
                    }
                    claim_checks[index].pop("cache_audit", None)
                    claim_cache_reused += 1

            summary = {
                "total": len(audited),
                "reachable": sum(1 for item in audited if item.get("reachable")),
                "access_limited": sum(1 for item in audited if item.get("access_limited")),
                "unclassified": sum(1 for item in audited if item.get("source_class") == "unclassified"),
                "errors": sum(1 for item in audited if item.get("error") or not item.get("reachable")),
                "claim_total": len(claim_checks),
                "claim_matched": sum(1 for item in claim_checks if item.get("matched")),
                "claim_manual": sum(1 for item in claim_checks if item.get("requires_manual_verification")),
                "claim_failed": sum(1 for item in claim_checks if item.get("failed")),
                "source_cache_reused": sum(1 for item in audited if item.get("cache_fallback")),
                "claim_cache_reused": claim_cache_reused,
            }
            payload = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "report": str(period["report"].relative_to(ROOT)),
                "baseline": f"git:{period['commit']}:state/supply_graph_baseline.json",
                "product_graph": f"git:{period['commit']}:state/product_relationships_{period['date'][:4]}.json",
                "report_sha256": sha256_file(period["report"]),
                "baseline_sha256": sha256_file(period["baseline"]),
                "product_graph_sha256": sha256_file(period["product"]),
                "audited_urls": period["urls"],
                "summary": summary,
                "sources": audited,
                "claim_checks": claim_checks,
            }
            output = ROOT / "logs" / f"{period['date']}_source_audit.json"
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            passed = summary["errors"] == 0 and summary["unclassified"] == 0 and summary["claim_failed"] == 0
            status = "通过" if passed else "失败"
            print(
                f"{period['date']}: 来源审计{status} urls={summary['total']} "
                f"errors={summary['errors']} claims_failed={summary['claim_failed']} "
                f"cache={summary['source_cache_reused']}/{summary['claim_cache_reused']}",
                flush=True,
            )
            if not passed:
                failed_periods.append(period["date"])

    if failed_periods:
        raise SystemExit("错误：以下历史来源审计未通过：" + ", ".join(failed_periods))
    print(f"历史来源审计全部通过：reports={len(periods)} unique_urls={len(all_urls)}")


if __name__ == "__main__":
    main()

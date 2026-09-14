#!/usr/bin/env python3
"""Validate recorded temporal evidence, not the truth of source prose."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from graph_update_policy import supply_changed_edge_ids


SHANGHAI = ZoneInfo("Asia/Shanghai")
ENFORCE_FROM = date(2026, 9, 14)
REVIEW_SCOPES = {"financial_periods_and_units", "source_versions", "product_graph", "report_vintage"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field}: require ISO 8601 timestamp with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field}: timezone is required; do not invent midnight")
    return parsed


def report_day(report: Path) -> date:
    day = date.fromisoformat(report.name[:10])
    if day.weekday() != 0:
        raise ValueError("report date must be a Monday")
    return day


def publication_bounds(source: dict, identity: str) -> tuple[datetime, datetime, bool]:
    """An unknown timezone widens uncertainty; it never invents an instant."""
    has_instant = "claim_first_public_at" in source
    has_interval = "claim_first_public_interval" in source
    if has_instant == has_interval:
        raise ValueError(f"{identity}: require exactly one publication instant or interval")
    if has_instant:
        first = timestamp(source["claim_first_public_at"], f"{identity}.claim_first_public_at")
        explanation = " ".join(str(source.get(k, "")) for k in ("locator", "support"))
        if (first.hour, first.minute, first.second) == (23, 59, 59) and re.search(
                r"最晚时刻|日末|不宣称实际|不宣称精确|保守界|end.of.day|latest possible", explanation, re.I):
            raise ValueError(f"{identity}: declared day-end bound cannot be a publication instant")
        return first, first, False
    value = source["claim_first_public_interval"]
    if not isinstance(value, dict) or value.get("timezone_basis") != "global_utc_minus12_to_plus14":
        raise ValueError(f"{identity}: unsupported publication interval basis")
    raw_date = value.get("published_date")
    if not isinstance(raw_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
        raise ValueError(f"{identity}: interval requires a source publication date")
    day = date.fromisoformat(raw_date)
    if any(not isinstance(value.get(k), str) or not value[k].strip()
           for k in ("version_locator", "note")):
        raise ValueError(f"{identity}: interval requires specific version evidence and uncertainty note")
    midnight = datetime.combine(day, time.min, timezone.utc)
    earliest = midnight - timedelta(hours=14)
    latest = midnight + timedelta(days=1, hours=12)
    if (timestamp(value.get("earliest"), "interval.earliest") != earliest or
            timestamp(value.get("latest_exclusive"), "interval.latest_exclusive") != latest):
        raise ValueError(f"{identity}: interval must retain the full global timezone bounds")
    return earliest, latest, True


def collect_targets(text: str, baseline: dict) -> dict[str, str]:
    """Inventory report blocks independently so evidence cannot silently omit them."""
    targets: dict[str, str] = {}
    section = 0
    event = 0
    current: str | None = None
    in_comment = False
    for line in text.splitlines():
        if in_comment or line.lstrip().startswith("<!--"):
            in_comment = "-->" not in line
            continue
        heading = re.match(r"## ([1-7])\.", line)
        if heading:
            section = int(heading[1])
            current = None
        elif line.startswith("### "):
            current = None
        elif section in {1, 4, 5} and (item := re.match(r"(\d+)\. ", line)):
            prefix = {1: "headline", 4: "analysis", 5: "catalyst"}[section]
            current = f"{prefix}:{item[1]}"
            targets[current] = line
        elif section == 2 and line.startswith("| "):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells[0] != "公司" and not re.fullmatch(r"[-: ]+", cells[0]):
                current = f"company:{cells[0]}"
                targets[current] = line
        elif section == 3 and line.startswith("- 日期："):
            event += 1
            current = f"event:{event}"
            targets[current] = line
        elif section == 1 and line.strip() == "本周未发现可确认重大事件。":
            current = "headline:none"
            targets[current] = line
        elif current and line.strip():
            targets[current] += "\n" + line
    changed_ids = set(supply_changed_edge_ids(baseline))
    for edge in baseline.get("edges", []):
        if edge.get("edge_id") in changed_ids:
            targets[f"supply:{edge['edge_id']}"] = json.dumps(edge, ensure_ascii=False, sort_keys=True)
    return targets


def validate_evidence(data: dict, report: Path, baseline: Path, product: Path | None) -> None:
    if data.get("status") not in {None, "ready"}:
        raise ValueError("temporal evidence is draft/unresolved; publication blocked")
    day = report_day(report)
    cutoff = datetime.combine(day, time.min, SHANGHAI)
    start = cutoff - timedelta(days=7)
    if data.get("schema_version") != 1 or data.get("report_date") != day.isoformat():
        raise ValueError("temporal evidence schema/report date mismatch")
    if timestamp(data.get("cutoff_exclusive"), "cutoff_exclusive") != cutoff:
        raise ValueError("cutoff must be report Monday 00:00 Asia/Shanghai, exclusive")
    for key, path in (("report_sha256", report), ("baseline_sha256", baseline), ("product_graph_sha256", product)):
        if path is not None and data.get(key) != digest(path):
            raise ValueError(f"{key}: stale evidence; re-review the changed file")
    created = timestamp(data.get("report_created_at"), "report_created_at")
    reviewed = timestamp(data.get("reviewed_at"), "reviewed_at")
    if created > reviewed or reviewed > datetime.now(SHANGHAI) + timedelta(minutes=5):
        raise ValueError("invalid creation/review chronology")
    scopes = data.get("manual_reviews", {})
    for scope in REVIEW_SCOPES:
        item = scopes.get(scope, {})
        note = item.get("note")
        if item.get("status") != "reviewed" or not isinstance(note, str) or not note.strip():
            raise ValueError(f"manual review missing or unresolved: {scope}")

    baseline_data = json.loads(baseline.read_text(encoding="utf-8"))
    targets = collect_targets(report.read_text(encoding="utf-8"), baseline_data)
    if not targets:
        raise ValueError("no report targets found")
    for key, block in targets.items():
        if key.startswith("event:"):
            declared_dates = re.findall(r"\d{4}-\d{2}-\d{2}", block.splitlines()[0])
            if not declared_dates or any(date.fromisoformat(value) >= day for value in declared_dates):
                raise ValueError(f"{key}: declared disclosure date missing or beyond cutoff")
    covered: set[str] = set()
    claim_ids: set[str] = set()
    for claim in data.get("claims", []):
        identity = claim.get("id")
        if not isinstance(identity, str) or not identity or identity in claim_ids:
            raise ValueError("claim id missing or duplicated")
        claim_ids.add(identity)
        refs = claim.get("targets", [])
        if not isinstance(refs, list) or not refs or any(ref not in targets for ref in refs):
            raise ValueError(f"{identity}: invalid/missing target references")
        kind = claim.get("kind")
        if kind not in {"news", "background", "forecast", "analysis"}:
            raise ValueError(f"{identity}: unknown claim kind")
        statement = claim.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError(f"{identity}: missing atomic statement")
        if any(ref.startswith("supply:") for ref in refs) and kind != "news":
            raise ValueError(f"{identity}: changed supply edge requires current-week news")
        evidence = claim.get("evidence", [])
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"{identity}: no dated evidence; unknown is not a pass")
        for source in evidence:
            if not str(source.get("url", "")).startswith("https://"):
                raise ValueError(f"{identity}: HTTPS source required")
            first, latest, interval = publication_bounds(source, identity)
            retrieved = timestamp(source.get("retrieved_at"), f"{identity}.retrieved_at")
            if first >= cutoff or (interval and latest > cutoff):
                raise ValueError(f"{identity}: information first public at/after cutoff")
            if latest > retrieved or retrieved > reviewed:
                raise ValueError(f"{identity}: invalid source/retrieval chronology")
            if kind == "news" and first < start:
                raise ValueError(f"{identity}: old announcement cannot be current-week news")
            if source.get("basis") not in {"dated_release", "dated_section", "archive", "filing", "dated_media"}:
                raise ValueError(f"{identity}: publication basis is not evidence")
            if any(not isinstance(source.get(key), str) or not source[key].strip() for key in ("locator", "support")):
                raise ValueError(f"{identity}: dated paragraph/page locator and support required")
            if source.get("page_modified_at"):
                modified = timestamp(source["page_modified_at"], "page_modified_at")
                if modified >= cutoff and source["basis"] not in {"dated_section", "archive", "filing"}:
                    raise ValueError(f"{identity}: later page update needs claim-level version evidence")
        event_at = claim.get("event_at")
        if event_at and timestamp(event_at, f"{identity}.event_at") >= cutoff and kind != "forecast":
            raise ValueError(f"{identity}: future occurrence must be a forecast, not a realized fact")
        covered.update(refs)
    missing = sorted(set(targets) - covered)
    if missing:
        raise ValueError(f"unreviewed report targets: {', '.join(missing)}")
    changed_ids = set(supply_changed_edge_ids(baseline_data))
    for edge in baseline_data.get("edges", []):
        value = edge.get("evidence_date")
        identity = edge.get("edge_id")
        if value == "long_term_baseline" and identity not in changed_ids:
            # Legacy context only; this sentinel never certifies a disclosure date.
            continue
        if not value:
            if identity in changed_ids:
                raise ValueError(f"{identity}: changed edge requires evidence_date")
            continue
        parts = str(value).split("/")
        if any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", part) for part in parts):
            raise ValueError(f"{identity}: invalid evidence_date")
        dates = [date.fromisoformat(part) for part in parts]
        if any(value >= day for value in dates):
            raise ValueError(f"{edge.get('edge_id')}: evidence_date exceeds coverage cutoff")
        if identity in changed_ids and (len(dates) != 1 or dates[0] < start.date()):
            raise ValueError(f"{identity}: changed edge requires one current-week evidence_date")


def check_report(report: Path, baseline: Path, product: Path | None = None) -> str:
    day = report_day(report)
    evidence_path = report.parent.parent / "logs" / f"{day}_temporal_evidence.json"
    if not evidence_path.exists():
        if day < ENFORCE_FROM and "<!-- point-in-time-policy: 1 -->" not in report.read_text(encoding="utf-8"):
            return "legacy_unverified：旧报告缺少时点证据，未认证历史可得性"
        raise ValueError(f"missing temporal evidence: {evidence_path}")
    if product is None:
        raise ValueError("product graph is required to bind all temporal evidence inputs")
    validate_evidence(json.loads(evidence_path.read_text(encoding="utf-8")), report, baseline, product)
    return "时点记录校验通过；来源语义与数值真实性仍依赖原文复核"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=Path("state/supply_graph_baseline.json"))
    parser.add_argument("--product-graph", type=Path)
    parser.add_argument("--inventory", action="store_true", help="Print required targets; never invent evidence")
    parser.add_argument("--inventory-output", type=Path, help="Write the complete inventory to a new JSON artifact and print only its count")
    args = parser.parse_args()
    if args.inventory_output and not args.inventory:
        parser.error("--inventory-output requires --inventory")
    try:
        if args.inventory:
            targets = collect_targets(args.report.read_text(encoding="utf-8"), json.loads(args.baseline.read_text(encoding="utf-8")))
            if args.inventory_output:
                with args.inventory_output.open("x", encoding="utf-8") as output:
                    json.dump(targets, output, ensure_ascii=False, indent=2)
                    output.write("\n")
                print(json.dumps({"inventory": str(args.inventory_output), "targets": len(targets)}))
            else:
                print(json.dumps(targets, ensure_ascii=False, indent=2))
        else:
            print(check_report(args.report, args.baseline, args.product_graph))
    except (ValueError, OSError, TypeError, AttributeError) as exc:
        raise SystemExit(f"point-in-time validation failed: {exc}") from exc


if __name__ == "__main__":
    main()

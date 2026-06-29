#!/usr/bin/env python3
"""Validate weekly brief artifacts before committing or pushing."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path


REQUIRED_COMPANIES = [
    "Apple",
    "Microsoft",
    "Alphabet / Google",
    "Amazon / AWS",
    "Meta",
    "NVIDIA",
    "Tesla",
    "Samsung Electronics",
    "SK Hynix",
    "TSMC",
]

REQUIRED_EDGE_FIELDS = [
    "edge_id",
    "supplier",
    "customer",
    "product_or_service",
    "relationship_type",
    "evidence_date",
    "source_type",
    "last_seen",
    "changed_this_week",
    "status",
    "confidence",
    "confidence_reason",
    "markdown_section_ref",
    "sources",
]


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def extract_section(text: str, start: str, end: str | None = None) -> str:
    if start not in text:
        fail(f"Missing section marker: {start}")
    section = text.split(start, 1)[1]
    if end and end in section:
        section = section.split(end, 1)[0]
    return section


def extract_mermaid(text: str) -> str:
    match = re.search(r"```mermaid\n(.*?)\n```", text, flags=re.S)
    if not match:
        fail("Missing closed mermaid code block")
    return match.group(1)


def edge_ids_from_text(text: str) -> set[str]:
    return set(re.findall(r"\bE\d{2}\b", text))


def validate_latest(latest_path: Path) -> None:
    latest = latest_path.read_text(encoding="utf-8")
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", latest)
    if not links:
        fail("reports/latest.md has no Markdown link")
    for link in links:
        if link.startswith(("http://", "https://", "/")):
            continue
        target = latest_path.parent / link
        if not target.exists():
            fail(f"reports/latest.md link target does not exist: {link}")


def validate_report(report_path: Path, baseline_path: Path, latest_path: Path) -> None:
    report = report_path.read_text(encoding="utf-8")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    period = baseline.get("coverage_period", {})
    start = period.get("start")
    end = period.get("end")
    if not start or not end:
        fail("Baseline coverage_period.start/end missing")
    try:
        date.fromisoformat(start)
        date.fromisoformat(end)
    except ValueError as exc:
        fail(f"Invalid coverage date: {exc}")
    expected_period = f"{start} 至 {end}"
    if expected_period not in report:
        fail(f"Report does not contain coverage period: {expected_period}")

    companies = baseline.get("companies")
    if companies != REQUIRED_COMPANIES:
        fail("Baseline companies list is missing or not in the required canonical order")
    for company in REQUIRED_COMPANIES:
        if company not in report:
            fail(f"Report does not mention required company: {company}")

    edges = baseline.get("edges")
    if not isinstance(edges, list) or not edges:
        fail("Baseline edges must be a non-empty list")
    if not (8 <= len(edges) <= 25):
        fail(f"Baseline edge count outside expected range: {len(edges)}")

    json_ids: set[str] = set()
    for edge in edges:
        for field in REQUIRED_EDGE_FIELDS:
            if field not in edge:
                fail(f"Edge missing required field {field}: {edge}")
        edge_id = edge["edge_id"]
        if not re.fullmatch(r"E\d{2}", edge_id):
            fail(f"Invalid edge_id: {edge_id}")
        if edge_id in json_ids:
            fail(f"Duplicate edge_id: {edge_id}")
        json_ids.add(edge_id)
        if not edge["sources"]:
            fail(f"Edge has no sources: {edge_id}")
        if any(not str(source).startswith(("http://", "https://")) for source in edge["sources"]):
            fail(f"Edge has non-URL source: {edge_id}")
        joined = " ".join(str(edge.get(key, "")) for key in ("status", "source_type", "confidence_reason", "notes"))
        low_confidence = edge.get("confidence") in {"low", "low_medium", "medium"}
        if low_confidence and not re.search(r"media|baseline|insufficient|risk|no_new|not a new|not new", joined, re.I):
            fail(f"Low/medium confidence edge lacks limitation language: {edge_id}")

    mermaid = extract_mermaid(report)
    if "flowchart LR" not in mermaid:
        fail("Mermaid block must use flowchart LR")
    for company in REQUIRED_COMPANIES:
        if company not in mermaid:
            fail(f"Mermaid graph missing company node: {company}")
    mermaid_ids = edge_ids_from_text(mermaid)

    table = extract_section(report, "### 6.2 供应关系明细表", "### 6.3")
    table_ids = set(re.findall(r"\| (E\d{2}) \|", table))
    if json_ids != mermaid_ids or json_ids != table_ids:
        fail(
            "Edge ID mismatch: "
            f"json={sorted(json_ids)} mermaid={sorted(mermaid_ids)} table={sorted(table_ids)}"
        )

    disallowed_phrases = [
        "提交与推送在本次文件校验后执行",
        "将在校验通过后追加提交",
        "图中重要边均能",
    ]
    for phrase in disallowed_phrases:
        if phrase in report:
            fail(f"Report contains stale or imprecise self-check phrase: {phrase}")

    validate_latest(latest_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="reports/2026-06-29_weekly_morning_brief.md")
    parser.add_argument("--baseline", default="state/supply_graph_baseline.json")
    parser.add_argument("--latest", default="reports/latest.md")
    args = parser.parse_args()

    validate_report(Path(args.report), Path(args.baseline), Path(args.latest))
    print("weekly_brief_validation_ok")


if __name__ == "__main__":
    main()

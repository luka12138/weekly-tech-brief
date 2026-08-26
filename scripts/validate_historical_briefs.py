#!/usr/bin/env python3
"""Validate every archived brief against its immutable historical snapshot."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from rebuild_historical_obsidian_graphs import ROOT, load_snapshot, report_snapshots
from validate_weekly_brief import validate_report


def write_snapshot(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="逐期校验所有历史周报、JSON 快照和图谱。")
    parser.add_argument("--dates", nargs="*", help="仅校验指定报告日期；默认全部")
    parser.add_argument("--graph-plan", default="state/historical_graph_plan.json")
    parser.add_argument("--require-source-audits", action="store_true")
    args = parser.parse_args()
    selected = set(args.dates) if args.dates else None
    plans = json.loads((ROOT / args.graph_plan).read_text(encoding="utf-8")).get("reports", {})
    failures: list[str] = []
    checked = 0

    with tempfile.TemporaryDirectory(prefix="weekly-brief-history-") as directory:
        temp_root = Path(directory)
        for report_date, commit in report_snapshots(selected):
            report_path = ROOT / "reports" / f"{report_date}_weekly_morning_brief.md"
            plan = plans.get(report_date)
            if not plan:
                failures.append(f"{report_date}: 缺少历史图谱计划")
                continue
            baseline_path = temp_root / f"{report_date}_supply.json"
            product_path = temp_root / f"{report_date}_product.json"
            write_snapshot(baseline_path, load_snapshot(commit, "state/supply_graph_baseline.json"))
            write_snapshot(product_path, load_snapshot(commit, f"state/product_relationships_{report_date[:4]}.json"))
            audit_path = ROOT / "logs" / f"{report_date}_source_audit.json"
            try:
                validate_report(
                    report_path,
                    baseline_path,
                    ROOT / "reports" / "latest.md",
                    source_audit_path=audit_path if args.require_source_audits else None,
                    product_graph_path=product_path,
                    product_image_path=Path(plan["product"]["svg"]),
                    product_canvas_path=Path(plan["product"]["canvas"]),
                    supply_image_path=Path(plan["supply"]["svg"]),
                    supply_canvas_path=Path(plan["supply"]["canvas"]),
                    expected_changed_edge_ids=set(plan["supply"]["changed_edge_ids"]),
                )
            except SystemExit as exc:
                failures.append(f"{report_date}: 校验失败（exit={exc.code}）")
                continue
            checked += 1
            print(f"{report_date}: 历史周报校验通过")

    if failures:
        raise SystemExit("错误：\n- " + "\n- ".join(failures))
    print(f"历史周报批量校验通过：reports={checked} source_audits={args.require_source_audits}")


if __name__ == "__main__":
    main()

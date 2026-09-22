#!/usr/bin/env python3
"""Rebuild every historical report graph from its committed state snapshot."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from graph_update_policy import build_graph_plan_from_data
from historical_snapshot_overrides import apply_data_overrides, apply_plan_overrides
from json_canvas_graphs import build_product_canvas, build_supply_canvas, write_canvas_and_svg


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})_weekly_morning_brief\.md$")
SNAPSHOT_MAP_PATH = ROOT / "state" / "historical_snapshot_map.json"


def git_output(arguments: list[str]) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True)


def report_snapshots(selected_dates: set[str] | None = None) -> list[tuple[str, str]]:
    snapshot_map: dict[str, str] = {}
    if SNAPSHOT_MAP_PATH.exists():
        payload = json.loads(SNAPSHOT_MAP_PATH.read_text(encoding="utf-8"))
        snapshot_map = {str(key): str(value) for key, value in payload.get("reports", {}).items()}
    snapshots: list[tuple[str, str]] = []
    for report in sorted((ROOT / "reports").glob("*_weekly_morning_brief.md")):
        match = REPORT_PATTERN.fullmatch(report.name)
        if not match:
            continue
        report_date = match.group(1)
        if selected_dates and report_date not in selected_dates:
            continue
        relative = report.relative_to(ROOT)
        commit = snapshot_map.get(report_date)
        if not commit:
            commit = git_output(["log", "-1", "--format=%H", "--", str(relative)]).strip()
        if not commit:
            raise SystemExit(f"错误：找不到 {relative} 对应的 Git 快照")
        snapshots.append((report_date, commit))
    return snapshots


def load_snapshot(commit: str, path: str) -> dict[str, Any]:
    try:
        raw = git_output(["show", f"{commit}:{path}"])
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"错误：快照 {commit[:10]} 中缺少 {path}") from exc
    data = json.loads(raw)
    mapping = json.loads(SNAPSHOT_MAP_PATH.read_text(encoding="utf-8")).get("reports", {})
    report_date = next((str(date) for date, snapshot in mapping.items() if snapshot == commit), "")
    return apply_data_overrides(report_date, data) if report_date else data


def main() -> None:
    parser = argparse.ArgumentParser(description="按每期周报的 Git 快照重建全部 Obsidian Canvas 与 SVG。")
    parser.add_argument("--dates", nargs="*", help="仅重建指定报告日期；默认重建全部历史周报")
    parser.add_argument(
        "--prune-redundant",
        action="store_true",
        help="删除策略判定为沿用历史版本的同日期冗余图谱文件",
    )
    parser.add_argument(
        "--plan-output",
        default="state/historical_graph_plan.json",
        help="历史图谱更新计划输出路径",
    )
    args = parser.parse_args()
    selected = set(args.dates) if args.dates else None
    snapshots = report_snapshots()
    if not snapshots:
        raise SystemExit("错误：未找到可重建的历史周报")

    total_nodes = 0
    total_edges = 0
    previous_supply: dict[str, Any] | None = None
    previous_product: dict[str, Any] | None = None
    latest_supply_date: str | None = None
    latest_product_date: str | None = None
    plans: dict[str, Any] = {}
    for report_date, commit in snapshots:
        supply_data = load_snapshot(commit, "state/supply_graph_baseline.json")
        product_data = load_snapshot(commit, f"state/product_relationships_{report_date[:4]}.json")
        plan = build_graph_plan_from_data(
            report_date,
            supply_data,
            product_data,
            previous_supply,
            previous_product,
            latest_supply_date,
            latest_product_date,
        )
        apply_plan_overrides(report_date, plan, supply_data)
        plans[report_date] = {"source_commit": commit, **plan}
        should_rebuild = selected is None or report_date in selected
        summaries: dict[str, dict[str, int] | None] = {"product": None, "supply": None}
        for kind, builder, data in (
            ("product", build_product_canvas, product_data),
            ("supply", build_supply_canvas, supply_data),
        ):
            graph_plan = plan[kind]
            if graph_plan["action"] == "generate":
                if should_rebuild:
                    summaries[kind] = write_canvas_and_svg(
                        builder(data),
                        ROOT / graph_plan["canvas"],
                        ROOT / graph_plan["svg"],
                    )
                    total_nodes += summaries[kind]["nodes"]
                    total_edges += summaries[kind]["edges"]
                if kind == "product":
                    latest_product_date = report_date
                else:
                    latest_supply_date = report_date
            elif not (ROOT / graph_plan["canvas"]).exists() or not (ROOT / graph_plan["svg"]).exists():
                raise SystemExit(f"错误：{report_date} 计划沿用但历史图谱不存在：{graph_plan}")

        if args.prune_redundant and selected is None:
            for kind in ("product", "supply"):
                graph_plan = plan[kind]
                if graph_plan["action"] != "reuse" or graph_plan["asset_date"] == report_date:
                    continue
                for suffix in (".canvas", ".svg"):
                    redundant = ROOT / "assets" / f"{report_date}_{kind}_relationships{suffix}"
                    if redundant.exists():
                        redundant.unlink()

        rendered = []
        for kind in ("product", "supply"):
            graph_plan = plan[kind]
            summary = summaries[kind]
            detail = f" {summary['nodes']}/{summary['edges']}" if summary else ""
            rendered.append(f"{kind}={graph_plan['action']}:{graph_plan['asset_date']}{detail}")
        print(f"{report_date} <- {commit[:10]}: " + ", ".join(rendered))
        previous_supply = supply_data
        previous_product = product_data

    output_path = ROOT / args.plan_output
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy": "weekly_supply_material_change_and_quarterly_or_material_product_refresh",
                "reports": plans,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"历史图重建完成：reports={len(snapshots)} nodes={total_nodes} edges={total_edges} "
        f"plan={output_path.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()

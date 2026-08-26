#!/usr/bin/env python3
"""一键运行周报提交前质量闸门。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from graph_update_policy import build_graph_plan, extract_graph_asset_date, is_schema_v2


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def report_from_latest() -> Path:
    latest = ROOT / "reports" / "latest.md"
    text = latest.read_text(encoding="utf-8")
    match = re.search(r"\[[^\]]+\]\(([^)]+)\)", text)
    if not match:
        raise SystemExit("错误：reports/latest.md 没有可用的周报链接")
    return (latest.parent / match.group(1)).resolve()


def latest_target(latest: Path) -> Path:
    text = latest.read_text(encoding="utf-8")
    match = re.search(r"\[[^\]]+\]\(([^)]+)\)", text)
    if not match:
        raise SystemExit("错误：latest 文件没有可用的周报链接")
    return (latest.parent / match.group(1)).resolve()


def report_date(report: Path) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", report.name)
    if not match:
        raise SystemExit(f"错误：无法从周报文件名识别日期：{report}")
    return match.group(1)


def ensure_clean_git() -> None:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True, text=True, capture_output=True)
    if result.stdout.strip():
        raise SystemExit("错误：工作区存在未提交变更，不能确认发布状态")


def ensure_pushed() -> None:
    run(["git", "fetch", "origin"])
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()
    origin = subprocess.run(["git", "rev-parse", "origin/main"], cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()
    if head != origin:
        raise SystemExit("错误：HEAD 与 origin/main 不一致，尚未确认推送成功")


def require_artifact_pair(svg_path: Path, canvas_path: Path, label: str) -> None:
    missing = [str(path) for path in (svg_path, canvas_path) if not (ROOT / path).exists()]
    if missing:
        raise SystemExit(f"错误：{label}计划要求沿用既有图，但文件不存在：{', '.join(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="运行图生成、来源审查、主校验和 diff 检查。")
    parser.add_argument("--report", help="周报路径；默认读取 reports/latest.md 指向的文件")
    parser.add_argument("--baseline", default="state/supply_graph_baseline.json")
    parser.add_argument("--latest", default="reports/latest.md")
    parser.add_argument("--expected-report-date", help="期望周报日期，例如 2026-07-06")
    parser.add_argument("--require-clean-git", action="store_true", help="只检查工作区是否干净，不重新生成文件；适合提交/推送后复核")
    parser.add_argument("--require-pushed", action="store_true", help="只检查 HEAD 是否已推送到 origin/main，不重新生成文件；适合推送后复核")
    args = parser.parse_args()

    if args.report:
        report_arg = Path(args.report)
        report = report_arg if report_arg.is_absolute() else ROOT / report_arg
        report = report.resolve()
    else:
        report = report_from_latest()
    date = report_date(report)
    if args.expected_report_date and date != args.expected_report_date:
        raise SystemExit(f"错误：周报日期 {date} 与期望日期 {args.expected_report_date} 不一致")
    year = date[:4]
    baseline = Path(args.baseline)
    latest = Path(args.latest)
    product_graph = Path(f"state/product_relationships_{year}.json")
    report_text = report.read_text(encoding="utf-8")
    schema_v2 = is_schema_v2(report_text)
    graph_plan = None
    if schema_v2:
        try:
            graph_plan = build_graph_plan(ROOT, date, baseline, product_graph)
        except ValueError as exc:
            raise SystemExit(f"错误：图表更新策略校验失败：{exc}") from exc
        for kind in ("product", "supply"):
            referenced_date = extract_graph_asset_date(report_text, kind)
            expected_date = str(graph_plan[kind]["asset_date"])
            if referenced_date != expected_date:
                action = graph_plan[kind]["action"]
                reason = graph_plan[kind]["reason"]
                raise SystemExit(
                    f"错误：周报 {kind} 图引用日期应为 {expected_date}，实际为 {referenced_date}；"
                    f"策略={action}，原因={reason}"
                )
        product_image = Path(graph_plan["product"]["svg"])
        product_canvas = Path(graph_plan["product"]["canvas"])
        supply_image = Path(graph_plan["supply"]["svg"])
        supply_canvas = Path(graph_plan["supply"]["canvas"])
        print(json.dumps(graph_plan, ensure_ascii=False, indent=2))
    else:
        product_image = Path(f"assets/{date}_product_relationships.svg")
        product_canvas = Path(f"assets/{date}_product_relationships.canvas")
        supply_image = Path(f"assets/{date}_supply_relationships.svg")
        supply_canvas = Path(f"assets/{date}_supply_relationships.canvas")
    source_audit = Path(f"logs/{date}_source_audit.json")
    if latest_target(ROOT / latest).resolve() != report.resolve():
        raise SystemExit("错误：latest.md 未指向当前待校验周报")

    python = sys.executable
    baseline_data = json.loads((ROOT / baseline).read_text(encoding="utf-8"))
    if baseline_data.get("generation_date") != date:
        raise SystemExit("错误：供应关系基线 generation_date 与周报日期不一致")
    validator_command = [
        python,
        "scripts/validate_weekly_brief.py",
        "--report",
        str(report.relative_to(ROOT)),
        "--baseline",
        str(baseline),
        "--latest",
        str(latest),
        "--source-audit",
        str(source_audit),
        "--product-graph",
        str(product_graph),
        "--product-image",
        str(product_image),
        "--product-canvas",
        str(product_canvas),
        "--supply-image",
        str(supply_image),
        "--supply-canvas",
        str(supply_canvas),
    ]
    if schema_v2:
        validator_command.append("--expected-changed-edge-ids")
        validator_command.extend(str(edge_id) for edge_id in graph_plan["supply"]["changed_edge_ids"])
    if args.require_clean_git or args.require_pushed:
        run(validator_command)
        run(["git", "diff", "--check"])
        if args.require_clean_git:
            ensure_clean_git()
        if args.require_pushed:
            ensure_pushed()
        print("发布状态检查通过")
        return

    generate_product = not schema_v2 or graph_plan["product"]["action"] == "generate"
    generate_supply = not schema_v2 or graph_plan["supply"]["action"] == "generate"
    if generate_product:
        command = [
            python,
            "scripts/build_product_graph_svg.py",
            "--input",
            str(product_graph),
            "--output",
            str(product_image),
            "--canvas-output",
            str(product_canvas),
        ]
        if schema_v2:
            command.extend(["--snapshot-date", date])
        run(command)
    else:
        require_artifact_pair(product_image, product_canvas, "产品图")
        print(f"沿用产品图：{product_image}")
    if generate_supply:
        run(
            [
                python,
                "scripts/build_supply_graph_svg.py",
                "--input",
                str(baseline),
                "--output",
                str(supply_image),
                "--canvas-output",
                str(supply_canvas),
            ]
        )
    else:
        require_artifact_pair(supply_image, supply_canvas, "供应图")
        print(f"沿用供应图：{supply_image}")
    run(
        [
            python,
            "scripts/audit_sources.py",
            "--report",
            str(report.relative_to(ROOT)),
            "--baseline",
            str(baseline),
            "--product-graph",
            str(product_graph),
            "--output",
            str(source_audit),
            "--strict",
        ]
    )
    run(validator_command)
    run(["git", "diff", "--check"])
    print("质量闸门全部通过")


if __name__ == "__main__":
    main()

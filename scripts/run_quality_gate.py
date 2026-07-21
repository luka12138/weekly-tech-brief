#!/usr/bin/env python3
"""一键运行周报提交前质量闸门。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


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
    product_image = Path(f"assets/{date}_product_relationships.svg")
    supply_image = Path(f"assets/{date}_supply_relationships.svg")
    source_audit = Path(f"logs/{date}_source_audit.json")
    if latest_target(ROOT / latest).resolve() != report.resolve():
        raise SystemExit("错误：latest.md 未指向当前待校验周报")

    python = sys.executable
    baseline_data = json.loads((ROOT / baseline).read_text(encoding="utf-8"))
    if baseline_data.get("generation_date") != date:
        raise SystemExit("错误：供应关系基线 generation_date 与周报日期不一致")
    if args.require_clean_git or args.require_pushed:
        run(
            [
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
                "--supply-image",
                str(supply_image),
            ]
        )
        run(["git", "diff", "--check"])
        if args.require_clean_git:
            ensure_clean_git()
        if args.require_pushed:
            ensure_pushed()
        print("发布状态检查通过")
        return

    run([python, "scripts/build_product_graph_svg.py", "--input", str(product_graph), "--output", str(product_image)])
    run([python, "scripts/build_supply_graph_svg.py", "--input", str(baseline), "--output", str(supply_image)])
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
    run(
        [
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
            "--supply-image",
            str(supply_image),
        ]
    )
    run(["git", "diff", "--check"])
    print("质量闸门全部通过")


if __name__ == "__main__":
    main()

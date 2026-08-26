#!/usr/bin/env python3
"""Print the graph generation/reuse plan for a weekly brief."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from graph_update_policy import build_graph_plan


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--baseline", default="state/supply_graph_baseline.json")
    parser.add_argument("--product-graph", help="默认按报告年份读取 state/product_relationships_YYYY.json")
    args = parser.parse_args()
    product_graph = args.product_graph or f"state/product_relationships_{args.report_date[:4]}.json"
    plan = build_graph_plan(ROOT, args.report_date, Path(args.baseline), Path(product_graph))
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

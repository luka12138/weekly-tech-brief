#!/usr/bin/env python3
"""Generate an Obsidian Canvas product graph and its SVG rendering."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from json_canvas_graphs import build_product_canvas, write_canvas_and_svg


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True, help="SVG output path")
    parser.add_argument("--canvas-output", help="Canvas output path; defaults to SVG path with .canvas suffix")
    parser.add_argument("--snapshot-date", help="Override the report snapshot date shown in the graph title")
    args = parser.parse_args()

    input_path = Path(args.input)
    svg_path = Path(args.output)
    canvas_path = Path(args.canvas_output) if args.canvas_output else svg_path.with_suffix(".canvas")
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if args.snapshot_date:
        data = dict(data)
        data["generated_for_report_date"] = args.snapshot_date
    summary = write_canvas_and_svg(build_product_canvas(data), canvas_path, svg_path)
    print(f"产品关系图已生成 {svg_path}；Canvas={canvas_path}；nodes={summary['nodes']} edges={summary['edges']}")


if __name__ == "__main__":
    main()

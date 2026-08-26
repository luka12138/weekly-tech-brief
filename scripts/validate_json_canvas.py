#!/usr/bin/env python3
"""Validate one or more JSON Canvas files against the project rules."""

from __future__ import annotations

import argparse
from pathlib import Path

from json_canvas_graphs import validate_canvas_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", help="Canvas files to validate")
    args = parser.parse_args()

    for raw_path in args.paths:
        path = Path(raw_path)
        summary = validate_canvas_file(path)
        print(f"Canvas 校验通过 {path}: nodes={summary['nodes']} edges={summary['edges']} groups={summary['groups']}")


if __name__ == "__main__":
    main()

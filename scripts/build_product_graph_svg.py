#!/usr/bin/env python3
"""Build an SVG product relationship graph from structured JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape


COLORS = {
    "device": "#dbeafe",
    "cloud_ai": "#dcfce7",
    "semiconductor": "#fef3c7",
    "memory": "#fae8ff",
    "auto_energy": "#fee2e2",
    "external": "#e5e7eb",
}

COMPANY_X = {
    "Apple": 70,
    "Microsoft": 70,
    "Alphabet / Google": 70,
    "Amazon / AWS": 70,
    "Meta": 70,
    "Tesla": 70,
    "NVIDIA": 470,
    "Samsung Electronics": 470,
    "SK Hynix": 470,
    "TSMC": 470,
}

COMPANY_Y = {
    "Apple": 90,
    "Microsoft": 200,
    "Alphabet / Google": 310,
    "Amazon / AWS": 420,
    "Meta": 530,
    "Tesla": 640,
    "NVIDIA": 120,
    "Samsung Electronics": 260,
    "SK Hynix": 400,
    "TSMC": 540,
}


def node_id(name: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_")


def wrap(text: str, limit: int = 26) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > limit and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:4]


def draw_node(company: dict[str, object], x: int, y: int) -> str:
    name = str(company["name"])
    category = str(company.get("category", "external"))
    products = [str(item) for item in company.get("main_products", [])]
    fill = COLORS.get(category, COLORS["external"])
    lines = [name] + wrap(", ".join(products), 42)
    height = 48 + 17 * max(1, len(lines) - 1)
    parts = [
        f'<rect id="{node_id(name)}" x="{x}" y="{y}" width="300" height="{height}" rx="10" fill="{fill}" stroke="#334155" stroke-width="1.4"/>',
        f'<text x="{x + 14}" y="{y + 23}" font-size="14" font-weight="700" fill="#0f172a">{escape(name)}</text>',
    ]
    for idx, line in enumerate(lines[1:], start=1):
        parts.append(f'<text x="{x + 14}" y="{y + 23 + idx * 17}" font-size="11" fill="#334155">{escape(line)}</text>')
    return "\n".join(parts)


def draw_edge(edge: dict[str, object], coords: dict[str, tuple[int, int]]) -> str:
    source = str(edge["source"])
    target = str(edge["target"])
    label = str(edge["product_or_service"])
    sx, sy = coords[source]
    tx, ty = coords[target]
    sx += 300
    sy += 28
    ty += 28
    color = "#475569"
    if str(edge.get("evidence_level")) == "official_current_year":
        color = "#166534"
    elif "media" in str(edge.get("evidence_level")):
        color = "#92400e"
    midx = (sx + tx) / 2
    midy = (sy + ty) / 2
    return "\n".join(
        [
            f'<path d="M {sx} {sy} C {midx} {sy}, {midx} {ty}, {tx} {ty}" fill="none" stroke="{color}" stroke-width="1.8" marker-end="url(#arrow)"/>',
            f'<text x="{midx - 80:.1f}" y="{midy - 4:.1f}" font-size="10" fill="{color}">{escape(label[:48])}</text>',
        ]
    )


def build_svg(data: dict[str, object]) -> str:
    companies = [dict(item) for item in data["companies"]]
    coords = {str(item["name"]): (COMPANY_X[str(item["name"])], COMPANY_Y[str(item["name"])]) for item in companies}
    width = 850
    height = 760
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs><marker id=\"arrow\" markerWidth=\"10\" markerHeight=\"10\" refX=\"8\" refY=\"3\" orient=\"auto\"><path d=\"M0,0 L0,6 L9,3 z\" fill=\"#475569\"/></marker></defs>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="32" y="34" font-size="20" font-weight="800" fill="#0f172a">{escape(str(data.get("title", "Product relationship graph")))}</text>',
        f'<text x="32" y="56" font-size="12" fill="#475569">Source baseline: {escape(str(data.get("source_baseline", "")))}</text>',
    ]
    for edge in data.get("relationships", []):
        parts.append(draw_edge(dict(edge), coords))
    for company in companies:
        name = str(company["name"])
        x, y = coords[name]
        parts.append(draw_node(company, x, y))
    parts.append('<text x="32" y="735" font-size="11" fill="#64748b">Green: official/current-year evidence. Brown: media-reported or weaker evidence. Public report, no confidential data.</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    svg = build_svg(data)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")
    print(f"product_graph_svg_ok {output}")


if __name__ == "__main__":
    main()

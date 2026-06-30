#!/usr/bin/env python3
"""Build an Obsidian-style SVG product relationship graph."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape


COMPANY_COLORS = {
    "device": "#60a5fa",
    "cloud_ai": "#34d399",
    "semiconductor": "#fbbf24",
    "memory": "#c084fc",
    "auto_energy": "#fb7185",
    "external": "#94a3b8",
}


def polar(cx: float, cy: float, r: float, angle: float) -> tuple[float, float]:
    return cx + r * math.cos(angle), cy + r * math.sin(angle)


def node_key(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")


def evidence_color(level: str) -> str:
    if "official_current_year" in level:
        return "#22c55e"
    if "official" in level:
        return "#38bdf8"
    if "media" in level:
        return "#f59e0b"
    return "#64748b"


def wrap_label(text: str, limit: int = 34) -> list[str]:
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
    return lines[:2]


def draw_edge(source: str, target: str, label: str, color: str, coords: dict[str, tuple[float, float]], cx: float, cy: float) -> str:
    sx, sy = coords[source]
    tx, ty = coords[target]
    mx, my = (sx + tx) / 2, (sy + ty) / 2
    qx, qy = (mx + cx) / 2, (my + cy) / 2
    label_x, label_y = (mx + qx) / 2, (my + qy) / 2
    return "\n".join(
        [
            f'<path d="M {sx:.1f} {sy:.1f} Q {qx:.1f} {qy:.1f} {tx:.1f} {ty:.1f}" fill="none" stroke="{color}" stroke-width="1.45" stroke-opacity="0.68"/>',
            f'<text x="{label_x:.1f}" y="{label_y:.1f}" font-size="9" fill="{color}" fill-opacity="0.92">{escape(label[:42])}</text>',
        ]
    )


def draw_node(name: str, category: str, products: list[str], x: float, y: float) -> str:
    color = COMPANY_COLORS.get(category, COMPANY_COLORS["external"])
    product_line = ", ".join(products[:4])
    lines = wrap_label(product_line, 38)
    parts = [
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="27" fill="{color}" fill-opacity="0.22" stroke="{color}" stroke-width="2.2"/>',
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.2" fill="{color}"/>',
        f'<text x="{x:.1f}" y="{y - 38:.1f}" text-anchor="middle" font-size="13" font-weight="700" fill="#e5e7eb">{escape(name)}</text>',
    ]
    for idx, line in enumerate(lines):
        parts.append(f'<text x="{x:.1f}" y="{y + 43 + idx * 13:.1f}" text-anchor="middle" font-size="9.5" fill="#94a3b8">{escape(line)}</text>')
    return "\n".join(parts)


def build_svg(data: dict[str, object]) -> str:
    width, height = 1180, 860
    cx, cy = width / 2, height / 2 + 12
    radius = 315
    companies = [dict(item) for item in data["companies"]]
    coords: dict[str, tuple[float, float]] = {}
    for idx, company in enumerate(companies):
        angle = -math.pi / 2 + (2 * math.pi * idx / len(companies))
        coords[str(company["name"])] = polar(cx, cy, radius, angle)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0f172a"/>',
        '<circle cx="590" cy="442" r="160" fill="none" stroke="#334155" stroke-width="1" stroke-opacity="0.75"/>',
        '<circle cx="590" cy="442" r="250" fill="none" stroke="#334155" stroke-width="1" stroke-opacity="0.55"/>',
        '<circle cx="590" cy="442" r="335" fill="none" stroke="#334155" stroke-width="1" stroke-opacity="0.35"/>',
        f'<text x="40" y="44" font-size="22" font-weight="800" fill="#f8fafc">{escape(str(data.get("title", "Product relationship graph")))}</text>',
        f'<text x="40" y="68" font-size="12" fill="#94a3b8">Obsidian-style graph view. Source baseline: {escape(str(data.get("source_baseline", ""))[:150])}</text>',
        '<text x="40" y="820" font-size="11" fill="#94a3b8">Edge colors: green=current-year official, blue=official baseline, amber=media/needs revalidation.</text>',
    ]

    for edge in data.get("relationships", []):
        item = dict(edge)
        source = str(item["source"])
        target = str(item["target"])
        if source in coords and target in coords:
            parts.append(draw_edge(source, target, f'{item["edge_id"]} {item["product_or_service"]}', evidence_color(str(item.get("evidence_level", ""))), coords, cx, cy))

    for company in companies:
        name = str(company["name"])
        x, y = coords[name]
        parts.append(draw_node(name, str(company.get("category", "external")), [str(p) for p in company.get("main_products", [])], x, y))

    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_svg(data), encoding="utf-8")
    print(f"product_graph_svg_ok {output}")


if __name__ == "__main__":
    main()

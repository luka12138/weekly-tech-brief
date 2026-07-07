#!/usr/bin/env python3
"""生成 Obsidian 风格的每周供应关系 SVG 图。"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape


COVERED = [
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

ALIASES = {
    "NVIDIA and AI accelerator customers": "NVIDIA",
    "NVIDIA/AI 加速器客户": "NVIDIA",
    "NVIDIA 与 AI 加速器客户": "NVIDIA",
    "AI startups and cloud customers": "外部:AI客户",
    "AI 初创企业/客户": "外部:AI客户",
    "AI 初创企业与云客户": "外部:AI客户",
    "创意专业用户": "外部:创意专业用户",
    "企业 AI 客户": "外部:企业AI客户",
    "OpenAI": "外部:OpenAI",
    "KDDI": "外部:KDDI",
    "EssilorLuxottica": "外部:EssilorLuxottica",
    "ASML/EUV": "外部:ASML/EUV",
}


def canonical(name: str) -> str:
    return ALIASES.get(name, name)


def polar(cx: float, cy: float, r: float, angle: float) -> tuple[float, float]:
    return cx + r * math.cos(angle), cy + r * math.sin(angle)


def edge_color(edge: dict[str, object]) -> str:
    status = str(edge.get("status", ""))
    source_type = str(edge.get("source_type", ""))
    changed = str(edge.get("changed_this_week", ""))
    if changed == "new" or status == "new":
        return "#22c55e"
    joined = " ".join((status, source_type, changed))
    if "risk" in joined or "media" in joined or status.startswith("continued_no_weekly"):
        return "#f59e0b"
    if changed.startswith("strengthened") or status.startswith("strengthened"):
        return "#38bdf8"
    return "#64748b"


def draw_edge(edge: dict[str, object], coords: dict[str, tuple[float, float]], cx: float, cy: float) -> str:
    source = canonical(str(edge["supplier"]))
    target = canonical(str(edge["customer"]))
    if source not in coords or target not in coords:
        return ""
    sx, sy = coords[source]
    tx, ty = coords[target]
    mx, my = (sx + tx) / 2, (sy + ty) / 2
    qx, qy = (mx + cx) / 2, (my + cy) / 2
    color = edge_color(edge)
    label = f'{edge["edge_id"]} {edge["product_or_service"]}'
    return "\n".join(
        [
            f'<path d="M {sx:.1f} {sy:.1f} Q {qx:.1f} {qy:.1f} {tx:.1f} {ty:.1f}" fill="none" stroke="{color}" stroke-width="1.5" stroke-opacity="0.72"/>',
            f'<text x="{((mx + qx) / 2):.1f}" y="{((my + qy) / 2):.1f}" font-size="9" fill="{color}">{escape(label[:44])}</text>',
        ]
    )


def draw_node(name: str, x: float, y: float) -> str:
    external = name.startswith("外部:")
    color = "#94a3b8" if external else "#a78bfa"
    radius = 22 if external else 29
    label = name.replace("外部:", "")
    return "\n".join(
        [
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}" fill-opacity="0.20" stroke="{color}" stroke-width="2"/>',
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}"/>',
            f'<text x="{x:.1f}" y="{y - radius - 10:.1f}" text-anchor="middle" font-size="13" font-weight="700" fill="#e5e7eb">{escape(label)}</text>',
        ]
    )


def build_svg(data: dict[str, object]) -> str:
    width, height = 1180, 860
    cx, cy = width / 2, height / 2 + 18
    covered_radius = 315
    external_radius = 390
    nodes = list(COVERED)
    edges = [dict(edge) for edge in data.get("edges", [])]
    for edge in edges:
        for endpoint in (canonical(str(edge["supplier"])), canonical(str(edge["customer"]))):
            if endpoint not in nodes:
                nodes.append(endpoint)

    coords: dict[str, tuple[float, float]] = {}
    for idx, node in enumerate(COVERED):
        coords[node] = polar(cx, cy, covered_radius, -math.pi / 2 + 2 * math.pi * idx / len(COVERED))
    external_nodes = [node for node in nodes if node not in COVERED]
    for idx, node in enumerate(external_nodes):
        coords[node] = polar(cx, cy, external_radius, -math.pi / 2 + 2 * math.pi * (idx + 0.5) / max(1, len(external_nodes)))

    period = data.get("coverage_period", {})
    title = f"本周供应关系图 {period.get('start', '')} 至 {period.get('end', '')}"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0f172a"/>',
        '<circle cx="590" cy="448" r="160" fill="none" stroke="#334155" stroke-width="1" stroke-opacity="0.75"/>',
        '<circle cx="590" cy="448" r="250" fill="none" stroke="#334155" stroke-width="1" stroke-opacity="0.55"/>',
        '<circle cx="590" cy="448" r="335" fill="none" stroke="#334155" stroke-width="1" stroke-opacity="0.35"/>',
        f'<text x="40" y="44" font-size="22" font-weight="800" fill="#f8fafc">{escape(title)}</text>',
        '<text x="40" y="68" font-size="12" fill="#94a3b8">Obsidian 风格网络图，基于 state/supply_graph_baseline.json 生成。</text>',
        '<text x="40" y="820" font-size="11" fill="#94a3b8">边颜色：绿色=新增，蓝色=强化，橙色=风险/媒体报道，灰色=基线关系。</text>',
    ]
    for edge in edges:
        line = draw_edge(edge, coords, cx, cy)
        if line:
            parts.append(line)
    for node, (x, y) in coords.items():
        parts.append(draw_node(node, x, y))
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
    print(f"供应关系图已生成 {output}")


if __name__ == "__main__":
    main()

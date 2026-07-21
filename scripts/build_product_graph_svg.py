#!/usr/bin/env python3
"""生成 Obsidian 风格的年度产品关系 SVG 图。"""

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
    if revalidation_needed(level):
        return "#f59e0b"
    if "official_current_year" in level or "本年度官方证据" in level:
        return "#22c55e"
    if "official" in level or "官方" in level:
        return "#38bdf8"
    if "media" in level:
        return "#f59e0b"
    return "#64748b"


def revalidation_needed(level: str) -> bool:
    markers = ("market_consensus", "historical", "needs", "待复核", "待直接证据", "市场共识", "历史基线")
    return any(marker in level for marker in markers)


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


def draw_company_anchor(name: str, category: str, x: float, y: float) -> str:
    color = COMPANY_COLORS.get(category, COMPANY_COLORS["external"])
    return "\n".join(
        [
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="31" fill="{color}" fill-opacity="0.20" stroke="{color}" stroke-width="2.4"/>',
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}"/>',
            f'<text x="{x:.1f}" y="{y - 42:.1f}" text-anchor="middle" font-size="14" font-weight="800" fill="#f8fafc">{escape(name)}</text>',
        ]
    )


def draw_product_node(node: dict[str, object], x: float, y: float) -> str:
    color = COMPANY_COLORS.get(str(node.get("category", "external")), COMPANY_COLORS["external"])
    product = str(node["product"])
    return "\n".join(
        [
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="13" fill="{color}" fill-opacity="0.18" stroke="{color}" stroke-width="1.4"/>',
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"/>',
            f'<text x="{x:.1f}" y="{y + 25:.1f}" text-anchor="middle" font-size="9.2" fill="#cbd5e1">{escape(product)}</text>',
        ]
    )


def draw_product_edge(
    edge: dict[str, object],
    coords: dict[str, tuple[float, float]],
    cx: float,
    cy: float,
) -> str:
    source = str(edge["source_node"])
    target = str(edge["target_node"])
    if source not in coords or target not in coords:
        return ""
    sx, sy = coords[source]
    tx, ty = coords[target]
    mx, my = (sx + tx) / 2, (sy + ty) / 2
    qx, qy = (mx + cx) / 2, (my + cy) / 2
    color = evidence_color(str(edge.get("evidence_level", "")))
    cross_company = edge.get("source_company") != edge.get("target_company")
    opacity = "0.72" if cross_company else "0.33"
    width = "1.5" if cross_company else "0.9"
    parts = [
        f'<path d="M {sx:.1f} {sy:.1f} Q {qx:.1f} {qy:.1f} {tx:.1f} {ty:.1f}" fill="none" stroke="{color}" stroke-width="{width}" stroke-opacity="{opacity}"/>',
    ]
    if cross_company:
        label = f'{edge["edge_id"]} {edge["product_or_service"]}'
        parts.append(
            f'<text x="{((mx + qx) / 2):.1f}" y="{((my + qy) / 2):.1f}" font-size="8.4" fill="{color}" fill-opacity="0.95">{escape(label[:48])}</text>'
        )
    return "\n".join(parts)


def build_product_level_svg(data: dict[str, object]) -> str:
    width, height = 1500, 1100
    cx, cy = width / 2, height / 2 + 20
    company_radius = 375
    product_radius = 82
    companies = [dict(item) for item in data["companies"]]
    company_by_name = {str(company["name"]): company for company in companies}
    company_coords: dict[str, tuple[float, float]] = {}
    for idx, company in enumerate(companies):
        angle = -math.pi / 2 + (2 * math.pi * idx / len(companies))
        company_coords[str(company["name"])] = polar(cx, cy, company_radius, angle)

    product_nodes = [dict(item) for item in data.get("product_nodes", [])]
    grouped: dict[str, list[dict[str, object]]] = {}
    for node in product_nodes:
        grouped.setdefault(str(node["company"]), []).append(node)

    product_coords: dict[str, tuple[float, float]] = {}
    for company_name, nodes in grouped.items():
        anchor_x, anchor_y = company_coords[company_name]
        company_angle = math.atan2(anchor_y - cy, anchor_x - cx)
        for idx, node in enumerate(nodes):
            local_angle = company_angle - math.pi / 2 + (2 * math.pi * idx / max(1, len(nodes)))
            product_coords[str(node["node_id"])] = polar(anchor_x, anchor_y, product_radius, local_angle)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0f172a"/>',
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="180" fill="none" stroke="#334155" stroke-width="1" stroke-opacity="0.75"/>',
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="300" fill="none" stroke="#334155" stroke-width="1" stroke-opacity="0.55"/>',
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="455" fill="none" stroke="#334155" stroke-width="1" stroke-opacity="0.35"/>',
        f'<text x="44" y="48" font-size="24" font-weight="800" fill="#f8fafc">{escape(str(data.get("title", "年度主营产品上下游关系图")))}</text>',
        f'<text x="44" y="74" font-size="12" fill="#94a3b8">产品级 Obsidian 风格网络图：公司为大节点，主营产品为小节点，跨公司供应关系以标签标出。</text>',
        '<text x="44" y="1050" font-size="11" fill="#94a3b8">边颜色：绿色=本年度官方证据，蓝色=官方基线，橙色=市场共识或待直接证据；淡线=公司内部产品栈。</text>',
    ]
    for edge in data.get("product_edges", []):
        line = draw_product_edge(dict(edge), product_coords, cx, cy)
        if line:
            parts.append(line)
    for company_name, (x, y) in company_coords.items():
        category = str(company_by_name[company_name].get("category", "external"))
        parts.append(draw_company_anchor(company_name, category, x, y))
    for node in product_nodes:
        x, y = product_coords[str(node["node_id"])]
        parts.append(draw_product_node(node, x, y))
    parts.append("</svg>")
    return "\n".join(parts)


def build_svg(data: dict[str, object]) -> str:
    if data.get("product_nodes") and data.get("product_edges"):
        return build_product_level_svg(data)

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
        f'<text x="40" y="44" font-size="22" font-weight="800" fill="#f8fafc">{escape(str(data.get("title", "年度主营产品上下游关系图")))}</text>',
        f'<text x="40" y="68" font-size="12" fill="#94a3b8">Obsidian 风格网络图。来源基线：{escape(str(data.get("source_baseline", ""))[:150])}</text>',
        '<text x="40" y="820" font-size="11" fill="#94a3b8">边颜色：绿色=本年度官方证据，蓝色=官方基线，橙色=媒体报道或待复核。</text>',
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
    print(f"产品关系图已生成 {output}")


if __name__ == "__main__":
    main()

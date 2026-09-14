#!/usr/bin/env python3
"""Build, validate, and render Obsidian JSON Canvas relationship graphs."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape


NODE_TYPES = {"text", "file", "link", "group"}
SIDES = {"top", "right", "bottom", "left"}
ENDS = {"none", "arrow"}
PRESET_COLORS = {
    "1": "#ef4444",
    "2": "#f59e0b",
    "3": "#eab308",
    "4": "#22c55e",
    "5": "#06b6d4",
    "6": "#8b5cf6",
}
COMPANY_COLORS = {
    "device": "#60a5fa",
    "cloud_ai": "#34d399",
    "model_ai": "#22d3ee",
    "semiconductor": "#fbbf24",
    "memory": "#c084fc",
    "auto_energy": "#fb7185",
    "external": "#94a3b8",
}
COMPANY_ORDER = [
    "TSMC",
    "SK Hynix",
    "Samsung Electronics",
    "NVIDIA",
    "Apple",
    "Microsoft",
    "Alphabet / Google",
    "Amazon / AWS",
    "Meta",
    "Tesla",
    "OpenAI",
    "Anthropic",
]
ENDPOINT_ALIASES = {
    "NVIDIA and AI accelerator customers": "NVIDIA",
    "NVIDIA/AI 加速器客户": "NVIDIA",
    "NVIDIA 与 AI 加速器客户": "NVIDIA",
}


def stable_id(namespace: str, value: str) -> str:
    """Return the deterministic 16-character lowercase hex ID required by Canvas."""

    return hashlib.blake2b(f"{namespace}:{value}".encode("utf-8"), digest_size=8).hexdigest()


def canonical_endpoint(name: str, covered: set[str]) -> str:
    normalized = ENDPOINT_ALIASES.get(name.strip(), name.strip())
    if normalized in covered or normalized.startswith("外部:"):
        return normalized
    return f"外部:{normalized}"


def canvas_color(value: Any, fallback: str = "#64748b") -> str:
    if not value:
        return fallback
    raw = str(value)
    return PRESET_COLORS.get(raw, raw)


def supply_edge_color(edge: dict[str, Any]) -> str:
    status = str(edge.get("status", "")).lower()
    source_type = str(edge.get("source_type", "")).lower()
    changed = str(edge.get("changed_this_week", "")).lower()
    joined = " ".join((status, source_type, changed))
    if changed.startswith("no_new"):
        return "#f59e0b" if "risk" in joined or "media" in joined else "#64748b"
    if changed == "new" or status.startswith("new"):
        return "#22c55e"
    if "risk" in joined or "media" in joined:
        return "#f59e0b"
    if changed.startswith("strengthened") or status.startswith("strengthened"):
        return "#38bdf8"
    return "#64748b"


def product_edge_color(level: str) -> str:
    lowered = level.lower()
    if any(marker in lowered for marker in ("market_consensus", "historical", "待复核", "待直接证据", "市场共识", "历史基线")):
        return "#f59e0b"
    if "official_current_year" in lowered or "本年度官方证据" in lowered:
        return "#22c55e"
    if "official" in lowered or "官方" in lowered:
        return "#38bdf8"
    if "media" in lowered or "媒体" in lowered:
        return "#f59e0b"
    return "#64748b"


def text_node(
    namespace: str,
    key: str,
    x: int,
    y: int,
    width: int,
    height: int,
    text: str,
    color: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": stable_id(namespace, key),
        "type": "text",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "text": text,
    }
    if color:
        node["color"] = color
    return node


def group_node(
    namespace: str,
    key: str,
    x: int,
    y: int,
    width: int,
    height: int,
    label: str,
    color: str,
) -> dict[str, Any]:
    return {
        "id": stable_id(namespace, key),
        "type": "group",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "label": label,
        "color": color,
    }


def edge_sides(source: dict[str, Any], target: dict[str, Any]) -> tuple[str, str]:
    sx = source["x"] + source["width"] / 2
    sy = source["y"] + source["height"] / 2
    tx = target["x"] + target["width"] / 2
    ty = target["y"] + target["height"] / 2
    if abs(tx - sx) >= abs(ty - sy):
        return ("right", "left") if tx >= sx else ("left", "right")
    return ("bottom", "top") if ty >= sy else ("top", "bottom")


def canvas_edge(
    namespace: str,
    key: str,
    source: dict[str, Any],
    target: dict[str, Any],
    color: str,
    label: str | None = None,
) -> dict[str, Any]:
    from_side, to_side = edge_sides(source, target)
    edge: dict[str, Any] = {
        "id": stable_id(namespace, key),
        "fromNode": source["id"],
        "fromSide": from_side,
        "toNode": target["id"],
        "toSide": to_side,
        "toEnd": "arrow",
        "color": color,
    }
    if label:
        edge["label"] = label
    return edge


def chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def build_supply_canvas(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    covered_names = [str(name) for name in data.get("companies", [])]
    covered = set(covered_names)
    source_edges = [dict(edge) for edge in data.get("edges", [])]
    normalized_edges: list[tuple[dict[str, Any], str, str]] = []
    all_names = set(covered_names)
    incoming: dict[str, int] = {name: 0 for name in covered_names}
    outgoing: dict[str, int] = {name: 0 for name in covered_names}

    for edge in source_edges:
        supplier = canonical_endpoint(str(edge["supplier"]), covered)
        customer = canonical_endpoint(str(edge["customer"]), covered)
        normalized_edges.append((edge, supplier, customer))
        all_names.update((supplier, customer))
        outgoing[supplier] = outgoing.get(supplier, 0) + 1
        incoming[customer] = incoming.get(customer, 0) + 1
        incoming.setdefault(supplier, 0)
        outgoing.setdefault(customer, 0)

    def name_key(name: str) -> tuple[int, int, str]:
        base = name.replace("外部:", "")
        try:
            order = covered_names.index(base)
        except ValueError:
            order = len(covered_names)
        return (1 if name.startswith("外部:") else 0, order, base.casefold())

    columns: dict[str, list[str]] = {"supplier": [], "both": [], "customer": []}
    for name in sorted(all_names, key=name_key):
        has_in = incoming.get(name, 0) > 0
        has_out = outgoing.get(name, 0) > 0
        if has_out and not has_in:
            columns["supplier"].append(name)
        elif has_in and not has_out:
            columns["customer"].append(name)
        else:
            columns["both"].append(name)

    title = "本周供应关系图"
    period = data.get("coverage_period", {})
    if period.get("start") and period.get("end"):
        title += f" · {period['start']} 至 {period['end']}"

    nodes: list[dict[str, Any]] = [
        text_node("supply-node", "title", 80, 20, 1700, 90, f"# {title}"),
        text_node(
            "supply-node",
            "legend",
            80,
            160,
            1700,
            90,
            "绿色=本周新增 · 蓝色=本周强化 · 橙色=风险或媒体证据 · 灰色=基线无新增证据\n边标签对应周报 6.2 与供应关系 JSON 的 Edge ID。",
            "#475569",
        ),
    ]
    node_by_name: dict[str, dict[str, Any]] = {}
    group_x = {"supplier": 80, "both": 720, "customer": 1360}
    group_label = {
        "supplier": "供应方 / 能力提供方",
        "both": "双重角色 / 覆盖公司",
        "customer": "客户 / 使用方",
    }
    group_color = {"supplier": "#22c55e", "both": "#8b5cf6", "customer": "#38bdf8"}
    card_width = 500
    card_height = 100
    row_step = 160
    group_top = 320
    group_heights: list[int] = []

    for column in ("supplier", "both", "customer"):
        names = columns[column]
        height = max(240, 120 + len(names) * row_step)
        group_heights.append(height)
        nodes.append(
            group_node(
                "supply-group",
                column,
                group_x[column],
                group_top,
                580,
                height,
                group_label[column],
                group_color[column],
            )
        )
        for index, name in enumerate(names):
            display = name
            role_bits = []
            if outgoing.get(name, 0):
                role_bits.append(f"输出 {outgoing[name]}")
            if incoming.get(name, 0):
                role_bits.append(f"输入 {incoming[name]}")
            role = " · ".join(role_bits) or "本期孤立节点"
            kind = "覆盖公司" if name in covered else "外部节点"
            color = "#8b5cf6" if name in covered else "#64748b"
            card = text_node(
                "supply-entity",
                name,
                group_x[column] + 40,
                group_top + 80 + index * row_step,
                card_width,
                card_height,
                f"**{display}**\n{kind} · {role}",
                color,
            )
            nodes.append(card)
            node_by_name[name] = card

    canvas_edges: list[dict[str, Any]] = []
    for edge, supplier, customer in normalized_edges:
        if supplier not in node_by_name or customer not in node_by_name:
            continue
        semantic_id = str(edge["edge_id"])
        canvas_edges.append(
            canvas_edge(
                "supply-edge",
                semantic_id,
                node_by_name[supplier],
                node_by_name[customer],
                supply_edge_color(edge),
                semantic_id,
            )
        )
        if edge.get("direction") == "bidirectional":
            canvas_edges[-1]["fromEnd"] = "arrow"
        source = node_by_name[supplier]
        target = node_by_name[customer]
        if source["x"] == target["x"]:
            side = "right" if target["y"] > source["y"] else "left"
            canvas_edges[-1].update(fromSide=side, toSide=side)

    index_top = group_top + max(group_heights) + 100
    for index, batch in enumerate(chunks(normalized_edges, 8)):
        lines = ["## 关系索引"]
        for edge, supplier, customer in batch:
            product = str(edge.get("product_or_service", ""))
            lines.append(f"**{edge['edge_id']}** · {supplier} → {customer}\n{product}")
        nodes.append(
            text_node(
                "supply-index",
                str(index),
                80 + index * 640,
                index_top,
                580,
                90 + len(batch) * 70,
                "\n\n".join(lines),
                "#334155",
            )
        )

    return {"nodes": nodes, "edges": canvas_edges}


def ordered_companies(companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {str(company["name"]): company for company in companies}
    ordered = [by_name[name] for name in COMPANY_ORDER if name in by_name]
    ordered.extend(company for company in companies if str(company["name"]) not in COMPANY_ORDER)
    return ordered


def build_product_canvas(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    companies = ordered_companies([dict(company) for company in data.get("companies", [])])
    product_nodes = [dict(node) for node in data.get("product_nodes", [])]
    product_edges = [dict(edge) for edge in data.get("product_edges", [])]
    has_product_graph = bool(product_nodes and product_edges)
    products_by_company: dict[str, list[dict[str, Any]]] = {str(company["name"]): [] for company in companies}

    if has_product_graph:
        for product in product_nodes:
            products_by_company.setdefault(str(product["company"]), []).append(product)
    else:
        for company in companies:
            name = str(company["name"])
            for index, product in enumerate(company.get("main_products", []), start=1):
                products_by_company[name].append(
                    {
                        "node_id": f"fallback-{index}",
                        "company": name,
                        "product": str(product),
                        "category": str(company.get("category", "external")),
                    }
                )

    title = str(data.get("title", "年度主营产品上下游关系图"))
    snapshot = str(data.get("generated_for_report_date", ""))
    if snapshot:
        title = f"{title} · {snapshot} 快照"

    nodes: list[dict[str, Any]] = [
        text_node("product-node", "title", 80, 20, 2460, 90, f"# {title}"),
        text_node(
            "product-node",
            "legend",
            80,
            160,
            2460,
            90,
            "公司分组内为主营产品节点；淡色边为内部产品栈，带 Edge ID 的边为跨公司依赖。\n绿色=本年度官方证据 · 蓝色=官方基线 · 橙色=市场共识、历史基线或待直接证据。",
            "#475569",
        ),
    ]
    company_headers: dict[str, dict[str, Any]] = {}
    product_cards: dict[str, dict[str, Any]] = {}
    group_width = 560
    group_height = 600
    group_gap_x = 100
    group_gap_y = 100
    group_left = 80
    group_top = 320
    column_count = min(4, max(1, len(companies)))

    for index, company in enumerate(companies):
        name = str(company["name"])
        category = str(company.get("category", "external"))
        color = COMPANY_COLORS.get(category, COMPANY_COLORS["external"])
        row, column = divmod(index, column_count)
        x = group_left + column * (group_width + group_gap_x)
        y = group_top + row * (group_height + group_gap_y)
        nodes.append(group_node("product-group", name, x, y, group_width, group_height, name, color))
        header = text_node(
            "product-company",
            name,
            x + 50,
            y + 50,
            460,
            70,
            f"## {name}\n{category.replace('_', ' ')}",
            color,
        )
        nodes.append(header)
        company_headers[name] = header
        for product_index, product in enumerate(products_by_company.get(name, [])):
            product_row, product_column = divmod(product_index, 2)
            card = text_node(
                "product-item",
                f"{name}:{product['node_id']}:{product['product']}",
                x + 50 + product_column * 270,
                y + 180 + product_row * 140,
                190,
                80,
                f"**{product['product']}**",
                color,
            )
            nodes.append(card)
            product_cards[str(product["node_id"])] = card

    canvas_edges: list[dict[str, Any]] = []
    index_relations: list[tuple[str, str, str, str]] = []
    if has_product_graph:
        for edge in product_edges:
            source = product_cards.get(str(edge["source_node"]))
            target = product_cards.get(str(edge["target_node"]))
            if not source or not target:
                continue
            cross_company = edge.get("source_company") != edge.get("target_company")
            semantic_id = str(edge["edge_id"])
            canvas_edges.append(
                canvas_edge(
                    "product-edge",
                    semantic_id,
                    source,
                    target,
                    product_edge_color(str(edge.get("evidence_level", ""))),
                    semantic_id if cross_company else None,
                )
            )
            if edge.get("direction") == "bidirectional":
                canvas_edges[-1]["fromEnd"] = "arrow"
            if cross_company:
                index_relations.append(
                    (
                        semantic_id,
                        str(edge.get("source_company", "")),
                        str(edge.get("target_company", "")),
                        str(edge.get("product_or_service", "")),
                    )
                )
    else:
        external_names: list[str] = []
        for relation in data.get("relationships", []):
            target_name = str(relation["target"])
            if target_name not in company_headers and target_name not in external_names:
                external_names.append(target_name)
        external_cards: dict[str, dict[str, Any]] = {}
        if external_names:
            external_x = group_left + column_count * (group_width + group_gap_x)
            external_height = max(220, 100 + len(external_names) * 150)
            nodes.append(group_node("product-group", "external", external_x, group_top, 500, external_height, "外部节点", "#64748b"))
            for index, name in enumerate(external_names):
                card = text_node(
                    "product-external",
                    name,
                    external_x + 50,
                    group_top + 70 + index * 150,
                    400,
                    90,
                    f"**{name}**",
                    "#64748b",
                )
                nodes.append(card)
                external_cards[name] = card
        for relation in data.get("relationships", []):
            source = company_headers.get(str(relation["source"]))
            target = company_headers.get(str(relation["target"])) or external_cards.get(str(relation["target"]))
            if not source or not target:
                continue
            semantic_id = str(relation["edge_id"])
            canvas_edges.append(
                canvas_edge(
                    "product-edge",
                    semantic_id,
                    source,
                    target,
                    product_edge_color(str(relation.get("evidence_level", ""))),
                    semantic_id,
                )
            )
            index_relations.append(
                (
                    semantic_id,
                    str(relation["source"]),
                    str(relation["target"]),
                    str(relation.get("product_or_service", "")),
                )
            )

    row_count = math.ceil(len(companies) / column_count)
    index_top = group_top + row_count * group_height + max(0, row_count - 1) * group_gap_y + 100
    for index, batch in enumerate(chunks(index_relations, 8)):
        lines = ["## 跨公司关系索引"]
        for edge_id, source, target, product in batch:
            lines.append(f"**{edge_id}** · {source} → {target}\n{product}")
        nodes.append(
            text_node(
                "product-index",
                str(index),
                80 + index * 860,
                index_top,
                800,
                90 + len(batch) * 70,
                "\n\n".join(lines),
                "#334155",
            )
        )

    return {"nodes": nodes, "edges": canvas_edges}


def _valid_color(value: Any) -> bool:
    return value in PRESET_COLORS or bool(re.fullmatch(r"#[0-9A-Fa-f]{6}", str(value)))


def _contains(outer: dict[str, Any], inner: dict[str, Any]) -> bool:
    return (
        inner["x"] >= outer["x"]
        and inner["y"] >= outer["y"]
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"]
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"]
    )


def _overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


def validate_canvas(canvas: dict[str, Any]) -> dict[str, int]:
    if not isinstance(canvas, dict):
        raise ValueError("Canvas top level must be an object")
    nodes = canvas.get("nodes", [])
    edges = canvas.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("Canvas nodes and edges must be arrays")

    seen: set[str] = set()
    node_by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        for field in ("id", "type", "x", "y", "width", "height"):
            if field not in node:
                raise ValueError(f"Canvas node missing {field}: {node}")
        node_id = str(node["id"])
        if not re.fullmatch(r"[0-9a-f]{16}", node_id):
            raise ValueError(f"Canvas node ID must be 16 lowercase hex characters: {node_id}")
        if node_id in seen:
            raise ValueError(f"Duplicate Canvas ID: {node_id}")
        seen.add(node_id)
        node_type = node["type"]
        if node_type not in NODE_TYPES:
            raise ValueError(f"Unsupported Canvas node type: {node_type}")
        required_by_type = {"text": "text", "file": "file", "link": "url"}
        required = required_by_type.get(node_type)
        if required and required not in node:
            raise ValueError(f"Canvas {node_type} node missing {required}: {node_id}")
        for field in ("x", "y", "width", "height"):
            if not isinstance(node[field], int):
                raise ValueError(f"Canvas node {field} must be an integer: {node_id}")
            if node[field] % 10 != 0:
                raise ValueError(f"Canvas node {field} must align to the 10px grid: {node_id}")
        if node["width"] <= 0 or node["height"] <= 0:
            raise ValueError(f"Canvas node dimensions must be positive: {node_id}")
        if "color" in node and not _valid_color(node["color"]):
            raise ValueError(f"Invalid Canvas node color: {node['color']}")
        node_by_id[node_id] = node

    for edge in edges:
        for field in ("id", "fromNode", "toNode"):
            if field not in edge:
                raise ValueError(f"Canvas edge missing {field}: {edge}")
        edge_id = str(edge["id"])
        if not re.fullmatch(r"[0-9a-f]{16}", edge_id):
            raise ValueError(f"Canvas edge ID must be 16 lowercase hex characters: {edge_id}")
        if edge_id in seen:
            raise ValueError(f"Duplicate Canvas ID: {edge_id}")
        seen.add(edge_id)
        if edge["fromNode"] not in node_by_id or edge["toNode"] not in node_by_id:
            raise ValueError(f"Canvas edge has a dangling node reference: {edge_id}")
        for field in ("fromSide", "toSide"):
            if field in edge and edge[field] not in SIDES:
                raise ValueError(f"Invalid Canvas edge side: {edge_id} {field}={edge[field]}")
        for field in ("fromEnd", "toEnd"):
            if field in edge and edge[field] not in ENDS:
                raise ValueError(f"Invalid Canvas edge end: {edge_id} {field}={edge[field]}")
        if "color" in edge and not _valid_color(edge["color"]):
            raise ValueError(f"Invalid Canvas edge color: {edge['color']}")

    groups = [node for node in nodes if node["type"] == "group"]
    content = [node for node in nodes if node["type"] != "group"]
    for index, first in enumerate(content):
        for second in content[index + 1 :]:
            if _overlaps(first, second):
                raise ValueError(f"Overlapping Canvas nodes: {first['id']} and {second['id']}")
    for index, first in enumerate(groups):
        for second in groups[index + 1 :]:
            if _overlaps(first, second):
                raise ValueError(f"Overlapping Canvas groups: {first['id']} and {second['id']}")
    for node in content:
        containers = [group for group in groups if _contains(group, node)]
        if len(containers) > 1:
            raise ValueError(f"Canvas node belongs to multiple groups: {node['id']}")
        for group in groups:
            if _overlaps(group, node) and group not in containers:
                raise ValueError(f"Canvas node partially overlaps a group: {node['id']} and {group['id']}")

    return {"nodes": len(nodes), "edges": len(edges), "groups": len(groups)}


def validate_canvas_file(path: Path) -> dict[str, int]:
    return validate_canvas(json.loads(path.read_text(encoding="utf-8")))


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F", "A"} else 1 for char in text)


def _wrap_text(text: str, limit: int) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    last_space = -1
    for char in text:
        candidate = current + char
        if _display_width(candidate) <= limit:
            current = candidate
            if char.isspace():
                last_space = len(current) - 1
            continue
        if last_space > 0:
            lines.append(current[:last_space].rstrip())
            current = current[last_space + 1 :] + char
        else:
            lines.append(current.rstrip())
            current = char.lstrip()
        last_space = current.rfind(" ")
    if current:
        lines.append(current.rstrip())
    return lines or [""]


def _plain_markdown(text: str) -> str:
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", text)


def _anchor(node: dict[str, Any], side: str | None) -> tuple[float, float]:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["width"])
    height = float(node["height"])
    return {
        "left": (x, y + height / 2),
        "right": (x + width, y + height / 2),
        "top": (x + width / 2, y),
        "bottom": (x + width / 2, y + height),
    }.get(side or "", (x + width / 2, y + height / 2))


def _bezier_points(
    source: tuple[float, float],
    target: tuple[float, float],
    from_side: str | None,
    to_side: str | None,
) -> tuple[tuple[float, float], tuple[float, float]]:
    sx, sy = source
    tx, ty = target
    distance = max(80.0, min(320.0, math.hypot(tx - sx, ty - sy) * 0.35))
    if from_side == to_side and from_side in {"left", "right"}:
        distance = 100.0
    vectors = {
        "left": (-distance, 0.0),
        "right": (distance, 0.0),
        "top": (0.0, -distance),
        "bottom": (0.0, distance),
    }
    first = vectors.get(from_side or "", ((tx - sx) * 0.3, (ty - sy) * 0.3))
    second = vectors.get(to_side or "", ((sx - tx) * 0.3, (sy - ty) * 0.3))
    return (sx + first[0], sy + first[1]), (tx + second[0], ty + second[1])


def _bezier_midpoint(
    start: tuple[float, float],
    control1: tuple[float, float],
    control2: tuple[float, float],
    end: tuple[float, float],
    t: float = 0.38,
) -> tuple[float, float]:
    one = 1 - t
    return (
        one**3 * start[0] + 3 * one**2 * t * control1[0] + 3 * one * t**2 * control2[0] + t**3 * end[0],
        one**3 * start[1] + 3 * one**2 * t * control1[1] + 3 * one * t**2 * control2[1] + t**3 * end[1],
    )


def _render_text_node(node: dict[str, Any]) -> str:
    x, y = node["x"], node["y"]
    width, height = node["width"], node["height"]
    raw = str(node.get("text", ""))
    color = canvas_color(node.get("color"), "#64748b")
    is_title = raw.startswith("# ")
    is_heading = raw.startswith("## ")
    is_index = raw.startswith("## 关系") or raw.startswith("## 跨公司")
    fill = "#0b0f14" if is_title else "#111827"
    fill_opacity = "0" if is_title else ("0.97" if is_index else "0.94")
    stroke_opacity = "0" if is_title else "0.78"
    parts = [
        f'<g><title>{escape(_plain_markdown(raw).replace(chr(10), " · "))}</title>',
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="8" fill="{fill}" fill-opacity="{fill_opacity}" stroke="{escape(color)}" stroke-opacity="{stroke_opacity}" stroke-width="1.5"/>',
    ]
    source_lines = raw.splitlines()
    rendered: list[tuple[str, int, str]] = []
    for line_index, source_line in enumerate(source_lines):
        plain = _plain_markdown(source_line).strip()
        if not plain:
            rendered.append(("", 8, "#94a3b8"))
            continue
        if is_title and line_index == 0:
            size, line_color = 34, "#f8fafc"
            limit = max(20, int((width - 30) / 18))
        elif is_heading and line_index == 0:
            size, line_color = 20, "#f8fafc"
            limit = max(16, int((width - 28) / 11))
        elif line_index == 0 and raw.startswith("**"):
            size, line_color = 16, "#f8fafc"
            limit = max(14, int((width - 28) / 8.5))
        else:
            size, line_color = 13, "#cbd5e1"
            limit = max(18, int((width - 28) / 7))
        for wrapped in _wrap_text(plain, limit):
            rendered.append((wrapped, size, line_color))

    current_y = y + (42 if is_title else 28)
    max_y = y + height - 14
    visible: list[tuple[str, int, str, float]] = []
    for line, size, line_color in rendered:
        advance = 14 if not line else size + 8
        if current_y > max_y:
            if visible:
                previous = visible[-1]
                visible[-1] = (previous[0].rstrip("…") + "…", previous[1], previous[2], previous[3])
            break
        if line:
            visible.append((line, size, line_color, current_y))
        current_y += advance
    for line, size, line_color, line_y in visible:
        weight = "750" if size >= 16 else "500"
        parts.append(
            f'<text x="{x + 16}" y="{line_y}" font-size="{size}" font-weight="{weight}" fill="{line_color}">{escape(line)}</text>'
        )
    parts.append("</g>")
    return "\n".join(parts)


def _edge_label_position(
    start: tuple[float, float],
    control1: tuple[float, float],
    control2: tuple[float, float],
    end: tuple[float, float],
    width: float,
    occupied: list[dict[str, Any]],
    viewport: tuple[float, float, float, float],
) -> tuple[float, float, tuple[float, float] | None]:
    # Keep badges on their curve while avoiding nodes and earlier badges.
    for t in sorted((i / 100 for i in range(5, 96)), key=lambda value: abs(value - 0.38)):
        x, y = _bezier_midpoint(start, control1, control2, end, t)
        bounds = {"x": x - width / 2 - 4, "y": y - 16, "width": width + 8, "height": 32}
        if not any(_overlaps(bounds, rectangle) for rectangle in occupied):
            occupied.append(bounds)
            return x, y, None
    # Legacy layouts can have fully blocked curves; use a nearby badge with a leader.
    midpoint = _bezier_midpoint(start, control1, control2, end)
    left, top, right, bottom = viewport
    for radius in range(20, 801, 20):
        for dx in range(-radius, radius + 1, 20):
            dy = radius - abs(dx)
            for offset_y in sorted({-dy, dy}):
                x, y = midpoint[0] + dx, midpoint[1] + offset_y
                bounds = {"x": x - width / 2 - 4, "y": y - 16, "width": width + 8, "height": 32}
                if not (left <= bounds["x"] and top <= bounds["y"]
                        and bounds["x"] + bounds["width"] <= right
                        and bounds["y"] + bounds["height"] <= bottom):
                    continue
                if not any(_overlaps(bounds, rectangle) for rectangle in occupied):
                    occupied.append(bounds)
                    return x, y, midpoint
    raise ValueError("Cannot place an edge label without overlapping a node or another label")


def render_canvas_svg(canvas: dict[str, Any]) -> str:
    validate_canvas(canvas)
    nodes = [dict(node) for node in canvas.get("nodes", [])]
    edges = [dict(edge) for edge in canvas.get("edges", [])]
    if not nodes:
        raise ValueError("Cannot render an empty Canvas")
    min_x = min(node["x"] for node in nodes) - 50
    min_y = min(node["y"] for node in nodes) - 40
    max_x = max(node["x"] + node["width"] for node in nodes) + 50
    max_y = max(node["y"] + node["height"] for node in nodes) + 60
    width = max_x - min_x
    height = max_y - min_y
    node_by_id = {node["id"]: node for node in nodes}
    edge_colors = sorted({canvas_color(edge.get("color")) for edge in edges})
    marker_ids = {color: f"arrow-{stable_id('marker', color)}" for color in edge_colors}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="{min_x} {min_y} {width} {height}">',
        "<defs>",
        '<pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M 20 0 L 0 0 0 20" fill="none" stroke="#1e293b" stroke-width="0.6" stroke-opacity="0.38"/></pattern>',
    ]
    for color, marker_id in marker_ids.items():
        parts.append(
            f'<marker id="{marker_id}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{escape(color)}"/></marker>'
        )
    parts.extend(
        [
            "</defs>",
            f'<rect x="{min_x}" y="{min_y}" width="{width}" height="{height}" fill="#0b0f14"/>',
            f'<rect x="{min_x}" y="{min_y}" width="{width}" height="{height}" fill="url(#grid)"/>',
            '<g font-family="-apple-system, BlinkMacSystemFont, PingFang SC, Noto Sans CJK SC, Segoe UI, sans-serif">',
        ]
    )

    for node in nodes:
        if node["type"] != "group":
            continue
        color = canvas_color(node.get("color"))
        parts.extend(
            [
                f'<rect x="{node["x"]}" y="{node["y"]}" width="{node["width"]}" height="{node["height"]}" rx="8" fill="{escape(color)}" fill-opacity="0.045" stroke="{escape(color)}" stroke-opacity="0.52" stroke-width="2" stroke-dasharray="8 8"/>',
                f'<text x="{node["x"] + 18}" y="{node["y"] + 30}" font-size="15" font-weight="700" fill="{escape(color)}">{escape(str(node.get("label", "")))}</text>',
            ]
        )

    label_occupied = [node for node in nodes if node["type"] != "group"]
    label_occupied.extend(
        {"x": node["x"] + 12, "y": node["y"] + 6, "width": node["width"] - 24, "height": 36}
        for node in nodes if node["type"] == "group"
    )
    label_parts: list[str] = []
    for edge in edges:
        source_node = node_by_id[edge["fromNode"]]
        target_node = node_by_id[edge["toNode"]]
        start = _anchor(source_node, edge.get("fromSide"))
        end = _anchor(target_node, edge.get("toSide"))
        control1, control2 = _bezier_points(start, end, edge.get("fromSide"), edge.get("toSide"))
        color = canvas_color(edge.get("color"))
        marker = f' marker-end="url(#{marker_ids[color]})"' if edge.get("toEnd", "arrow") == "arrow" else ""
        if edge.get("fromEnd") == "arrow":
            marker += f' marker-start="url(#{marker_ids[color]})"'
        parts.append(
            f'<path d="M {start[0]:.1f} {start[1]:.1f} C {control1[0]:.1f} {control1[1]:.1f}, {control2[0]:.1f} {control2[1]:.1f}, {end[0]:.1f} {end[1]:.1f}" fill="none" stroke="{escape(color)}" stroke-width="2" stroke-opacity="0.68"{marker}/>'
        )
        label = str(edge.get("label", ""))
        if label:
            badge_width = max(42, 11 * len(label) + 16)
            label_x, label_y, leader = _edge_label_position(
                start, control1, control2, end, badge_width, label_occupied,
                (min_x, min_y, max_x, max_y),
            )
            if leader is not None:
                parts.append(
                    f'<path d="M {leader[0]:.1f} {leader[1]:.1f} L {label_x:.1f} {label_y:.1f}" fill="none" stroke="{escape(color)}" stroke-width="1" stroke-dasharray="3 3"/>'
                )
            label_parts.extend(
                [
                    f'<rect x="{label_x - badge_width / 2:.1f}" y="{label_y - 12:.1f}" width="{badge_width}" height="24" rx="5" fill="#0b0f14" stroke="{escape(color)}" stroke-width="1.2"/>',
                    f'<text x="{label_x:.1f}" y="{label_y + 4.5:.1f}" text-anchor="middle" font-size="12" font-weight="750" fill="{escape(color)}">{escape(label)}</text>',
                ]
            )

    for node in nodes:
        if node["type"] == "text":
            parts.append(_render_text_node(node))
    parts.extend(label_parts)
    parts.extend(["</g>", "</svg>"])
    return "\n".join(parts)


def write_canvas_and_svg(canvas: dict[str, Any], canvas_path: Path, svg_path: Path) -> dict[str, int]:
    summary = validate_canvas(canvas)
    canvas_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    canvas_path.write_text(json.dumps(canvas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    svg_path.write_text(render_canvas_svg(canvas), encoding="utf-8")
    return summary


def validate_many(paths: Iterable[Path]) -> dict[str, dict[str, int]]:
    return {str(path): validate_canvas_file(path) for path in paths}

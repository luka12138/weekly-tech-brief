#!/usr/bin/env python3
"""Decide whether weekly relationship visuals should be regenerated or reused."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any


SCHEMA_V2_MARKER = "<!-- weekly-brief-schema: 2 -->"
MEANINGFUL_CHANGE_MARKERS = (
    "new",
    "strengthen",
    "weaken",
    "risk",
    "remove",
    "新增",
    "强化",
    "弱化",
    "风险",
    "移除",
)
NO_CHANGE_MARKERS = (
    "no_new",
    "no change",
    "unchanged",
    "baseline",
    "continued",
    "none",
    "无新增",
    "无变化",
    "基线",
    "延续",
)
SUPPLY_MATERIAL_FIELDS = (
    "supplier",
    "customer",
    "product_or_service",
    "relationship_type",
)
PRODUCT_RELATIONSHIP_FIELDS = (
    "edge_id",
    "source",
    "target",
    "product_or_service",
    "relationship_type",
    "evidence_level",
)
PRODUCT_NODE_FIELDS = ("node_id", "company", "product", "category")
PRODUCT_EDGE_FIELDS = (
    "edge_id",
    "source_node",
    "target_node",
    "source_company",
    "target_company",
    "product_or_service",
    "relationship_type",
    "evidence_level",
)


def is_schema_v2(report_text: str) -> bool:
    return SCHEMA_V2_MARKER in report_text


def is_quarterly_refresh(report_date: date) -> bool:
    """Refresh on the first Monday of each calendar quarter."""

    return report_date.month in {1, 4, 7, 10} and report_date.day <= 7 and report_date.weekday() == 0


def has_meaningful_supply_change(edge: dict[str, Any]) -> bool:
    marker = str(edge.get("changed_this_week", "")).strip().lower()
    if not marker or any(token in marker for token in NO_CHANGE_MARKERS):
        return False
    return any(token in marker for token in MEANINGFUL_CHANGE_MARKERS)


def _edge_map(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(edge["edge_id"]): dict(edge) for edge in data.get("edges", [])}


def _supply_material(edge: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(edge.get(field, "")).strip() for field in SUPPLY_MATERIAL_FIELDS)


def supply_changed_edge_ids(
    current: dict[str, Any],
    previous: dict[str, Any] | None = None,
    *,
    enforce_markers: bool = False,
) -> list[str]:
    """Return current Edge IDs with a meaningful weekly relationship change."""

    current_edges = _edge_map(current)
    changed = {edge_id for edge_id, edge in current_edges.items() if has_meaningful_supply_change(edge)}
    if previous is None:
        return sorted(changed)

    previous_edges = _edge_map(previous)
    removed = sorted(set(previous_edges) - set(current_edges))
    if removed and enforce_markers:
        raise ValueError(
            "供应关系不能直接从基线删除；应至少保留一期并标记为 weakened/removed："
            + ", ".join(removed)
        )

    for edge_id, edge in current_edges.items():
        old = previous_edges.get(edge_id)
        material_change = old is None or _supply_material(edge) != _supply_material(old)
        if not material_change:
            continue
        if enforce_markers and not has_meaningful_supply_change(edge):
            raise ValueError(f"供应关系 {edge_id} 已发生实质变化，但 changed_this_week 未标记新增/强化/弱化/风险")
        changed.add(edge_id)
    return sorted(changed)


def _select_fields(item: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: item.get(field) for field in fields if field in item}


def product_material_view(data: dict[str, Any]) -> dict[str, Any]:
    """Remove dates, source URLs, and prose so only graph topology/content remains."""

    companies = [
        {
            "name": company.get("name"),
            "category": company.get("category"),
            "main_products": list(company.get("main_products", [])),
        }
        for company in data.get("companies", [])
    ]
    relationships = [
        _select_fields(dict(item), PRODUCT_RELATIONSHIP_FIELDS)
        for item in data.get("relationships", [])
    ]
    product_nodes = [
        _select_fields(dict(item), PRODUCT_NODE_FIELDS)
        for item in data.get("product_nodes", [])
    ]
    product_edges = [
        _select_fields(dict(item), PRODUCT_EDGE_FIELDS)
        for item in data.get("product_edges", [])
    ]
    return {
        "companies": sorted(companies, key=lambda item: str(item.get("name", ""))),
        "relationships": sorted(relationships, key=lambda item: str(item.get("edge_id", ""))),
        "product_nodes": sorted(product_nodes, key=lambda item: str(item.get("node_id", ""))),
        "product_edges": sorted(product_edges, key=lambda item: str(item.get("edge_id", ""))),
    }


def _relative_path(root: Path, path: Path) -> str:
    resolved = path if path.is_absolute() else root / path
    return str(resolved.resolve().relative_to(root.resolve()))


def load_head_json(root: Path, path: Path) -> dict[str, Any] | None:
    relative = _relative_path(root, path)
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative}"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def latest_asset_date(root: Path, kind: str, before: date) -> str | None:
    candidates: list[str] = []
    for svg_path in (root / "assets").glob(f"*_{kind}_relationships.svg"):
        match = re.fullmatch(rf"(\d{{4}}-\d{{2}}-\d{{2}})_{re.escape(kind)}_relationships\.svg", svg_path.name)
        if not match:
            continue
        asset_date = date.fromisoformat(match.group(1))
        canvas_path = svg_path.with_suffix(".canvas")
        if asset_date < before and canvas_path.exists():
            candidates.append(match.group(1))
    return max(candidates) if candidates else None


def extract_graph_asset_date(report_text: str, kind: str) -> str | None:
    matches = set(
        re.findall(
            rf"(?:\.\./)?assets/(\d{{4}}-\d{{2}}-\d{{2}})_{re.escape(kind)}_relationships\.svg",
            report_text,
        )
    )
    if len(matches) > 1:
        raise ValueError(f"周报引用了多个 {kind} 图日期：{sorted(matches)}")
    return next(iter(matches), None)


def _artifact_paths(kind: str, asset_date: str) -> dict[str, str]:
    stem = f"assets/{asset_date}_{kind}_relationships"
    return {"asset_date": asset_date, "svg": f"{stem}.svg", "canvas": f"{stem}.canvas"}


def build_graph_plan_from_data(
    report_date_value: str,
    current_supply: dict[str, Any],
    current_product: dict[str, Any],
    previous_supply: dict[str, Any] | None,
    previous_product: dict[str, Any] | None,
    latest_supply_asset_date: str | None,
    latest_product_asset_date: str | None,
    *,
    enforce_supply_markers: bool = False,
    enforce_product_marker: bool = False,
) -> dict[str, Any]:
    """Build a plan from explicit snapshots, including historical migrations."""

    report_date = date.fromisoformat(report_date_value)
    changed_supply_ids = supply_changed_edge_ids(
        current_supply,
        previous_supply,
        enforce_markers=enforce_supply_markers and previous_supply is not None,
    )
    if latest_supply_asset_date is None:
        supply_action = "generate"
        supply_reason = "没有可沿用的历史供应图"
        supply_asset_date = report_date_value
    elif changed_supply_ids:
        supply_action = "generate"
        supply_reason = "存在实质变化关系：" + ", ".join(changed_supply_ids)
        supply_asset_date = report_date_value
    else:
        supply_action = "reuse"
        supply_reason = "本周无新增、强化、弱化或风险关系"
        supply_asset_date = latest_supply_asset_date

    quarterly = is_quarterly_refresh(report_date)
    product_changed = (
        previous_product is not None
        and product_material_view(current_product) != product_material_view(previous_product)
    )
    refresh_marker = str(current_product.get("generated_for_report_date", ""))
    if enforce_product_marker and product_changed and refresh_marker != report_date_value:
        raise ValueError(
            "年度产品关系发生实质变化时，必须将 generated_for_report_date 更新为本期报告日期"
        )
    if latest_product_asset_date is None:
        product_action = "generate"
        product_reason = "没有可沿用的历史产品图"
        product_asset_date = report_date_value
    elif quarterly:
        product_action = "generate"
        product_reason = "季度首个周一例行刷新"
        product_asset_date = report_date_value
    elif refresh_marker == report_date_value or (product_changed and not enforce_product_marker):
        product_action = "generate"
        product_reason = "主营产品或跨公司产品关系发生实质变化"
        product_asset_date = report_date_value
    else:
        product_action = "reuse"
        product_reason = "未到季度刷新点且产品关系无实质变化"
        product_asset_date = latest_product_asset_date

    product_plan = {"action": product_action, "reason": product_reason}
    product_plan.update(_artifact_paths("product", product_asset_date))
    supply_plan = {
        "action": supply_action,
        "reason": supply_reason,
        "changed_edge_ids": changed_supply_ids,
    }
    supply_plan.update(_artifact_paths("supply", supply_asset_date))
    return {
        "schema_version": 2,
        "report_date": report_date_value,
        "product": product_plan,
        "supply": supply_plan,
    }


def build_graph_plan(
    root: Path,
    report_date_value: str,
    baseline_path: Path,
    product_graph_path: Path,
) -> dict[str, Any]:
    report_date = date.fromisoformat(report_date_value)
    baseline_file = baseline_path if baseline_path.is_absolute() else root / baseline_path
    product_file = product_graph_path if product_graph_path.is_absolute() else root / product_graph_path
    current_supply = json.loads(baseline_file.read_text(encoding="utf-8"))
    current_product = json.loads(product_file.read_text(encoding="utf-8"))
    previous_supply = load_head_json(root, baseline_file)
    previous_product = load_head_json(root, product_file)

    latest_supply = latest_asset_date(root, "supply", report_date)
    latest_product = latest_asset_date(root, "product", report_date)
    return build_graph_plan_from_data(
        report_date_value,
        current_supply,
        current_product,
        previous_supply,
        previous_product,
        latest_supply,
        latest_product,
        enforce_supply_markers=True,
        enforce_product_marker=True,
    )

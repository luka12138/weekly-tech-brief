#!/usr/bin/env python3
"""Apply documented corrections after loading immutable historical snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from graph_update_policy import supply_changed_edge_ids


ROOT = Path(__file__).resolve().parents[1]
OVERRIDES_PATH = ROOT / "state" / "historical_snapshot_overrides.json"


def replacements_for_date(report_date: str) -> dict[str, str]:
    if not OVERRIDES_PATH.exists():
        return {}
    payload = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    report = payload.get("reports", {}).get(report_date, {})
    replacements = {
        str(key): str(value) for key, value in payload.get("global_replacements", {}).items()
    }
    replacements.update(
        {str(key): str(value) for key, value in report.get("replacements", {}).items()}
    )
    return replacements


def apply_text_overrides(report_date: str, text: str) -> str:
    for old, new in replacements_for_date(report_date).items():
        text = text.replace(old, new)
    return text


def _replace_data_strings(report_date: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _replace_data_strings(report_date, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_data_strings(report_date, item) for item in value]
    if isinstance(value, str):
        return apply_text_overrides(report_date, value)
    return value


def apply_data_overrides(report_date: str, value: Any) -> Any:
    result = _replace_data_strings(report_date, value)
    if not isinstance(result, dict) or "edges" not in result or not OVERRIDES_PATH.exists():
        return result
    correction = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8")).get("reports", {}).get(report_date, {})
    patches = correction.get("edge_overrides", {})
    edges = {edge["edge_id"]: edge for edge in result["edges"]}
    if set(patches) - set(edges):
        raise ValueError(f"Unknown correction Edge IDs: {sorted(set(patches) - set(edges))}")
    for edge_id, patch in patches.items():
        if "edge_id" in patch:
            raise ValueError("A correction cannot change an Edge ID")
        edges[edge_id].update(patch)
    if patches:
        result["sources"] = sorted({url for edge in result["edges"] for url in edge.get("sources", [])})
    return result


def apply_plan_overrides(report_date: str, plan: dict[str, Any], supply: dict[str, Any]) -> None:
    if not OVERRIDES_PATH.exists():
        return
    correction = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8")).get("reports", {}).get(report_date, {})
    if not correction.get("use_explicit_weekly_changes"):
        return
    # Legacy Edge IDs were reassigned across weeks; structural diffs alone are not new evidence.
    ids = sorted(supply_changed_edge_ids(supply))
    if not ids or plan["supply"]["action"] != "generate":
        raise ValueError("纠错图计划须显式审核生成/沿用决定，不能自动覆盖")
    plan["supply"]["changed_edge_ids"] = ids
    plan["supply"]["reason"] = "纠错后按已核当周显式标记生成；历史 Edge ID 重排不构成新增证据"

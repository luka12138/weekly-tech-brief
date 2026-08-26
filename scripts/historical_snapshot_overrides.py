#!/usr/bin/env python3
"""Apply documented corrections after loading immutable historical snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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


def apply_data_overrides(report_date: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {key: apply_data_overrides(report_date, item) for key, item in value.items()}
    if isinstance(value, list):
        return [apply_data_overrides(report_date, item) for item in value]
    if isinstance(value, str):
        return apply_text_overrides(report_date, value)
    return value

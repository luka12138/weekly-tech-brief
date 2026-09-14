from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from graph_update_policy import (  # noqa: E402
    build_graph_plan,
    is_quarterly_refresh,
    product_material_view,
    supply_changed_edge_ids,
)


def supply_edge(edge_id: str, changed: str, product: str = "GPU") -> dict[str, object]:
    return {
        "edge_id": edge_id,
        "supplier": "NVIDIA",
        "customer": "Microsoft",
        "product_or_service": product,
        "relationship_type": "accelerator_supply",
        "changed_this_week": changed,
    }


class GraphUpdatePolicyTests(unittest.TestCase):
    def test_frozen_comparison_uses_verified_previous_week(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "archives").mkdir()
            old_supply = {"generation_date": "2026-09-07", "edges": [supply_edge("E01", "new")]}
            old_product = {"generated_for_report_date": "2026-09-07", "companies": []}
            bindings = {}
            for kind, data in (("supply", old_supply), ("product", old_product)):
                raw = json.dumps(data).encode()
                (root / f"archives/{kind}.json").write_bytes(raw)
                bindings[kind] = {"path": f"archives/{kind}.json", "sha256": hashlib.sha256(raw).hexdigest()}
            current = {"generation_date": "2026-09-14", "edges": [supply_edge("E01", "no_new_weekly_evidence")], "comparison_snapshots": bindings}
            (root / "supply.json").write_text(json.dumps(current))
            (root / "product.json").write_text(json.dumps(old_product))
            with patch("graph_update_policy.load_head_json", return_value=None):
                plan = build_graph_plan(root, "2026-09-14", Path("supply.json"), Path("product.json"))
                self.assertEqual(plan["supply"]["changed_edge_ids"], [])
                (root / "archives/supply.json").write_text("tampered")
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    build_graph_plan(root, "2026-09-14", Path("supply.json"), Path("product.json"))

    def test_quarterly_refresh_is_first_monday(self) -> None:
        self.assertTrue(is_quarterly_refresh(date(2026, 10, 5)))
        self.assertFalse(is_quarterly_refresh(date(2026, 8, 31)))
        self.assertFalse(is_quarterly_refresh(date(2026, 10, 12)))

    def test_supply_graph_reuses_when_no_meaningful_change(self) -> None:
        previous = {"edges": [supply_edge("E01", "new")]}
        current = {"edges": [supply_edge("E01", "no_new_weekly_evidence")]}
        self.assertEqual(supply_changed_edge_ids(current, previous, enforce_markers=True), [])

    def test_supply_change_requires_explicit_marker(self) -> None:
        previous = {"edges": [supply_edge("E01", "no_new_weekly_evidence")]}
        current = {"edges": [supply_edge("E01", "no_new_weekly_evidence", product="GPU and networking")]}
        with self.assertRaisesRegex(ValueError, "changed_this_week"):
            supply_changed_edge_ids(current, previous, enforce_markers=True)

    def test_new_and_strengthened_edges_trigger_update(self) -> None:
        previous = {"edges": [supply_edge("E01", "no_new_weekly_evidence")]}
        current = {
            "edges": [
                supply_edge("E01", "strengthened_official_evidence"),
                supply_edge("E02", "new"),
            ]
        }
        self.assertEqual(
            supply_changed_edge_ids(current, previous, enforce_markers=True),
            ["E01", "E02"],
        )

    def test_product_signature_ignores_sources_but_detects_products(self) -> None:
        first = {
            "title": "old",
            "companies": [{"name": "Apple", "category": "device", "main_products": ["iPhone"], "official_sources": ["a"]}],
            "relationships": [],
            "product_nodes": [],
            "product_edges": [],
        }
        second = {
            **first,
            "title": "new",
            "companies": [{"name": "Apple", "category": "device", "main_products": ["iPhone"], "official_sources": ["b"]}],
        }
        self.assertEqual(product_material_view(first), product_material_view(second))
        second["companies"][0]["main_products"].append("Mac")
        self.assertNotEqual(product_material_view(first), product_material_view(second))

    def test_full_plan_reuses_both_graphs_when_week_has_no_change(self) -> None:
        supply = {"edges": [supply_edge("E01", "no_new_weekly_evidence")]}
        product = {
            "generated_for_report_date": "2026-08-24",
            "companies": [{"name": "Apple", "category": "device", "main_products": ["iPhone"]}],
            "relationships": [],
            "product_nodes": [],
            "product_edges": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state").mkdir()
            (root / "state" / "supply.json").write_text(json.dumps(supply), encoding="utf-8")
            (root / "state" / "product.json").write_text(json.dumps(product), encoding="utf-8")
            with (
                patch("graph_update_policy.load_head_json", side_effect=[supply, product]),
                patch("graph_update_policy.latest_asset_date", return_value="2026-08-24"),
            ):
                plan = build_graph_plan(
                    root,
                    "2026-08-31",
                    Path("state/supply.json"),
                    Path("state/product.json"),
                )
        self.assertEqual(plan["product"]["action"], "reuse")
        self.assertEqual(plan["supply"]["action"], "reuse")
        self.assertEqual(plan["product"]["asset_date"], "2026-08-24")


if __name__ == "__main__":
    unittest.main()

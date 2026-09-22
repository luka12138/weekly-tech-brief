from __future__ import annotations

import hashlib
import json
import sys
import tarfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from graph_update_policy import supply_changed_edge_ids
from validate_report_vintage import check_vintage


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


class CorrectionArtifactTests(unittest.TestCase):
    def test_original_archive_and_current_vintages_are_bound(self):
        entries = read_json("state/report_vintages.json")["reports"]
        original_days = {"2026-07-06", "2026-07-27"}
        self.assertTrue(original_days <= set(entries))
        for day, entry in entries.items():
            with tarfile.open(ROOT / entry["archive_path"]) as archive:
                with self.subTest(day=day):
                    original = archive.extractfile(entry["path"]).read()
                    self.assertEqual(hashlib.sha256(original).hexdigest(), entry["pre_correction_sha256"])
                    report = ROOT / entry["path"]
                    self.assertIn("版本隔离校验通过", check_vintage(report))
                    with self.assertRaisesRegex(ValueError, "禁止作为原周一"):
                        check_vintage(report, for_backtest=True)
                    if day in original_days - {"2026-07-06", "2026-07-27"}:
                        self.assertEqual(original.decode().split("## 1.", 1)[1], report.read_text().split("## 1.", 1)[1])

    def test_correction_evidence_binds_reports_inventory_and_artifacts(self):
        for day, count in (("2026-07-06", 6), ("2026-07-27", 9)):
            evidence = read_json(f"logs/{day}_correction_evidence.json")
            self.assertEqual(evidence["temporal_certification"], "legacy_unverified")
            self.assertFalse(evidence["backtest_eligible_for_original_report_time"])
            self.assertEqual(hashlib.sha256((ROOT / evidence["report_path"]).read_bytes()).hexdigest(), evidence["report_sha256"])
            for relative, expected in evidence["input_and_artifact_hashes"].items():
                # The shared correction registry may gain entries for other periods later.
                if relative == "state/historical_snapshot_overrides.json":
                    continue
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)
            targets = read_json(f"logs/{day}_correction_inventory.json")["targets"]
            self.assertEqual(sum(key.startswith("headline:") for key in targets), count)
            for correction in evidence["corrections"]:
                self.assertTrue(set(correction.get("targets", [])) <= set(targets))

    def test_old_aws_agreement_is_background_in_data_report_and_canvas(self):
        day = "2026-07-06"
        data = read_json(f"state/historical/{day}_supply.json")
        edges = {edge["edge_id"]: edge for edge in data["edges"]}
        changed = supply_changed_edge_ids(data)
        canvas = read_json(f"assets/{day}_supply_relationships.canvas")
        for edge_id in ("E03", "E05"):
            self.assertEqual(edges[edge_id]["evidence_date"], "2025-11-03")
            self.assertNotIn(edge_id, changed)
            visual = next(edge for edge in canvas["edges"] if edge.get("label") == edge_id)
            self.assertEqual(visual["color"], "#64748b")
        targets = read_json(f"logs/{day}_correction_inventory.json")["targets"]
        headlines = "\n".join(text for key, text in targets.items() if key.startswith("headline:"))
        self.assertNotIn("OpenAI", headlines)

    def test_alphabet_numbers_are_single_quarter_and_unit_conversion_is_exact(self):
        review = read_json("logs/2026-07-27_correction_evidence.json")["financial_review"]
        values = {(row["scope"], row["metric"]): row["source_value"] for row in review["alphabet"]}
        self.assertEqual(values[("Google Cloud", "Revenue")], 24768)
        self.assertEqual(values[("consolidated", "Operating income")], 40770)
        self.assertEqual(values[("consolidated", "Operating cash flow")] - values[("consolidated", "Purchases of property and equipment")], values[("consolidated", "Free cash flow")])
        for row in review["alphabet"] + review["tesla"]:
            self.assertEqual(row["period"], "three months ended 2026-06-30")
            self.assertEqual(row["period_type"], "single_quarter")
            self.assertEqual(Decimal(str(row["source_value"])) / 100, Decimal(row["display_value"]))
        self.assertEqual(review["discarded_guidance"]["period"], "full year 2025")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_report_vintage import MARKER, check_vintage
from historical_snapshot_overrides import apply_data_overrides, apply_plan_overrides
import migrate_historical_briefs_v2 as migration
import run_quality_gate as gate


class ReportVintageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("reports", "state", "archives"):
            (self.root / name).mkdir()
        self.report = self.root / "reports/2026-07-06_weekly_morning_brief.md"
        self.report.write_text(MARKER + "\n禁止作为原周一实时回测输入\n", encoding="utf-8")
        self.archive = self.root / "archives/original.tar.gz"
        self.archive.write_bytes(b"original archive fixture")
        self.entry = {
            "version_type": "retrospective_revision",
            "revised_at": "2026-09-07T12:00:00+08:00",
            "backtest_eligible_for_original_report_time": False,
            "current_sha256": hashlib.sha256(self.report.read_bytes()).hexdigest(),
            "original_snapshot_commit": "original",
            "pre_correction_sha256": "original-hash",
            "archive_path": "archives/original.tar.gz",
            "archive_sha256": hashlib.sha256(self.archive.read_bytes()).hexdigest(),
        }
        self.registry = self.root / "state/report_vintages.json"
        self.save()

    def save(self):
        self.registry.write_text(json.dumps({"reports": {"2026-07-06": self.entry}}))

    def test_display_valid_but_original_time_backtest_rejected(self):
        self.assertIn("版本隔离校验通过", check_vintage(self.report))
        with self.assertRaisesRegex(ValueError, "事后修订"):
            check_vintage(self.report, for_backtest=True)

    def test_missing_registry_never_assumes_original_time(self):
        self.registry.unlink()
        with self.assertRaisesRegex(ValueError, "版本登记"):
            check_vintage(self.report)
        self.report.write_text("unmarked legacy report")
        self.assertEqual(check_vintage(self.report), "")
        with self.assertRaises(ValueError):
            check_vintage(self.report, for_backtest=True)

    def test_stale_report_hash_is_rejected(self):
        self.report.write_text(self.report.read_text() + "changed")
        with self.assertRaisesRegex(ValueError, "哈希已过期"):
            check_vintage(self.report)

    def test_tampered_archive_is_rejected(self):
        self.archive.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "归档"):
            check_vintage(self.report)

    def test_missing_warning_is_rejected(self):
        self.report.write_text(MARKER)
        self.entry["current_sha256"] = hashlib.sha256(self.report.read_bytes()).hexdigest()
        self.save()
        with self.assertRaisesRegex(ValueError, "回测限制"):
            check_vintage(self.report)

    def test_naive_or_backdated_revision_is_rejected(self):
        for timestamp in ("2026-09-07T12:00:00", "2026-07-05T12:00:00+08:00", "unknown"):
            self.entry["revised_at"] = timestamp
            self.save()
            with self.assertRaises(ValueError):
                check_vintage(self.report)

    def test_revised_report_cannot_be_registered_as_backtest_eligible(self):
        self.entry["backtest_eligible_for_original_report_time"] = True
        self.save()
        with self.assertRaisesRegex(ValueError, "回测资格"):
            check_vintage(self.report)

    def test_historical_gate_rejects_noncanonical_path_before_running(self):
        other = self.root / "elsewhere/2026-07-06_weekly_morning_brief.md"
        with patch.object(gate, "ROOT", self.root), patch.object(gate, "run") as run, patch.object(sys, "argv", ["gate", "--historical", "--report", str(other)]):
            with self.assertRaisesRegex(SystemExit, "规范报告路径"):
                gate.main()
            run.assert_not_called()

    def test_historical_gate_only_runs_read_only_validation(self):
        with patch.object(gate, "ROOT", self.root), patch.object(gate, "run") as run, patch.object(gate, "build_graph_plan") as plan, patch.object(sys, "argv", ["gate", "--historical", "--report", str(self.report)]):
            gate.main()
            self.assertEqual(len(run.call_args_list), 2)
            self.assertIn("scripts/validate_historical_briefs.py", run.call_args_list[0].args[0])
            plan.assert_not_called()

    def test_migration_stops_before_loading_or_overwriting_any_report(self):
        (self.root / "state/historical_graph_plan.json").write_text('{"reports": {}}')
        before = self.report.read_bytes()
        with patch.object(migration, "ROOT", self.root), patch.object(migration, "report_snapshots", return_value=[("2026-07-06", "original")]), patch.object(migration, "load_snapshot") as load, patch.object(sys, "argv", ["migrate"]):
            with self.assertRaisesRegex(SystemExit, "已有纠错"):
                migration.main()
            load.assert_not_called()
        self.assertEqual(before, self.report.read_bytes())


class StructuredCorrectionTests(unittest.TestCase):
    def test_overrides_do_not_mutate_original_and_rebuild_source_union(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "overrides.json"
            config.write_text(json.dumps({"reports": {"2026-07-06": {"edge_overrides": {"E03": {"changed_this_week": "no_new_weekly_evidence", "sources": ["old-announcement"]}}, "use_explicit_weekly_changes": True}}}))
            original = {"edges": [{"edge_id": "E03", "changed_this_week": "new", "sources": ["wrong"]}, {"edge_id": "E04", "changed_this_week": "new", "sources": ["release"]}]}
            with patch("historical_snapshot_overrides.OVERRIDES_PATH", config):
                revised = apply_data_overrides("2026-07-06", original)
                self.assertEqual(original["edges"][0]["changed_this_week"], "new")
                self.assertEqual(revised["sources"], ["old-announcement", "release"])
                plan = {"supply": {"action": "generate", "changed_edge_ids": ["E03", "E04"]}}
                apply_plan_overrides("2026-07-06", plan, revised)
                self.assertEqual(plan["supply"]["changed_edge_ids"], ["E04"])
                self.assertEqual(apply_data_overrides("2026-07-06", {"relationships": []}), {"relationships": []})

    def test_unknown_or_mutated_edge_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "overrides.json"
            for overrides in ({"E99": {}}, {"E03": {"edge_id": "E99"}}):
                config.write_text(json.dumps({"reports": {"2026-07-06": {"edge_overrides": overrides}}}))
                with patch("historical_snapshot_overrides.OVERRIDES_PATH", config), self.assertRaises(ValueError):
                    apply_data_overrides("2026-07-06", {"edges": [{"edge_id": "E03"}]})


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from json_canvas_graphs import supply_edge_color


class WeeklyGraphColorTests(unittest.TestCase):
    def test_old_new_or_strengthened_status_does_not_color_current_week(self):
        for status in ("new_relationship", "strengthened_official_evidence"):
            self.assertEqual(supply_edge_color({"status": status, "changed_this_week": "no_new_weekly_evidence"}), "#64748b")

    def test_retained_risk_is_not_hidden_by_no_new(self):
        self.assertEqual(supply_edge_color({"status": "ongoing_risk", "changed_this_week": "no_new_weekly_evidence"}), "#f59e0b")

    def test_actual_current_strengthening_is_blue(self):
        self.assertEqual(supply_edge_color({"changed_this_week": "strengthened"}), "#38bdf8")

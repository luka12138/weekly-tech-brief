import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from json_canvas_graphs import build_supply_canvas, render_canvas_svg


class DirectionTests(unittest.TestCase):
    def test_bidirectional_capability_has_two_arrowheads(self):
        data = {"generation_date": "2026-09-07", "companies": ["Microsoft", "Amazon / AWS"],
                "coverage_period": {"start": "2026-08-31", "end": "2026-09-06"},
                "edges": [{"edge_id": "E29", "supplier": "Amazon / AWS", "customer": "Microsoft",
                           "product_or_service": "Bidirectional preview, not procurement",
                           "direction": "bidirectional", "confidence": "high", "changed_this_week": "new"}]}
        canvas = build_supply_canvas(data)
        edge = next(e for e in canvas["edges"] if e.get("label") == "E29")
        self.assertEqual((edge["fromEnd"], edge["toEnd"]), ("arrow", "arrow"))
        paths = ET.fromstring(render_canvas_svg(canvas)).findall(".//{http://www.w3.org/2000/svg}path")
        self.assertTrue(any(p.get("marker-start") and p.get("marker-end") for p in paths))
        del data["edges"][0]["direction"]
        single = build_supply_canvas(data)
        self.assertNotIn("fromEnd", next(e for e in single["edges"] if e.get("label") == "E29"))

from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from json_canvas_graphs import _overlaps, render_canvas_svg


class GraphLabelTests(unittest.TestCase):
    def test_labels_remain_visible_around_an_intervening_node(self) -> None:
        nodes = [
            {"id": f"{i:016x}", "type": "text", "x": 0, "y": y,
             "width": 200, "height": 100, "text": f"Node {i}"}
            for i, y in enumerate((0, 220, 520), start=1)
        ]
        edges = [
            {"id": f"{i + 10:016x}", "fromNode": nodes[0]["id"],
             "toNode": nodes[2]["id"], "fromSide": "bottom", "toSide": "top",
             "label": f"E{i:02}"}
            for i in range(1, 4)
        ]
        root = ET.fromstring(render_canvas_svg({"nodes": nodes, "edges": edges}))
        badges = [
            {key: float(rect.attrib[key]) for key in ("x", "y", "width", "height")}
            for rect in root.findall(".//{http://www.w3.org/2000/svg}rect")
            if rect.get("rx") == "5"
        ]
        self.assertEqual(len(badges), 3)
        for index, badge in enumerate(badges):
            self.assertFalse(any(_overlaps(badge, node) for node in nodes))
            self.assertFalse(any(_overlaps(badge, other) for other in badges[:index]))

        blocked_nodes = [
            dict(nodes[0], x=0, y=0, width=600, height=280),
            dict(nodes[2], x=0, y=300, width=600, height=280),
        ]
        fallback = ET.fromstring(render_canvas_svg({"nodes": blocked_nodes, "edges": edges[:1]}))
        leaders = [p for p in fallback.findall(".//{http://www.w3.org/2000/svg}path")
                   if p.get("stroke-dasharray") == "3 3"]
        self.assertEqual(len(leaders), 1)
        for rect in fallback.findall(".//{http://www.w3.org/2000/svg}rect"):
            if rect.get("rx") != "5":
                continue
            badge = {key: float(rect.attrib[key]) for key in ("x", "y", "width", "height")}
            self.assertFalse(any(_overlaps(badge, node) for node in blocked_nodes))
            self.assertGreaterEqual(badge["y"], -40)
            self.assertLessEqual(badge["y"] + badge["height"], 640)


if __name__ == "__main__":
    unittest.main()

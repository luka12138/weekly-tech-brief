import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from json_canvas_graphs import build_product_canvas, validate_canvas


class ProductGroupCapacityTests(unittest.TestCase):
    def test_extra_products_stay_inside_their_company(self):
        for count in (6, 7, 9):
            with self.subTest(count=count):
                canvas = build_product_canvas({
                    "companies": [{"name": "Microsoft", "category": "cloud_ai",
                                   "main_products": [f"Product {i}" for i in range(count)]}],
                    "relationships": [],
                })
                validate_canvas(canvas)
                group = next(n for n in canvas["nodes"] if n["type"] == "group")
                cards = [n for n in canvas["nodes"] if n.get("text", "").startswith("**Product ")]
                self.assertEqual(len(cards), count)
                for node in cards:
                    self.assertGreaterEqual(node["x"], group["x"])
                    self.assertGreaterEqual(node["y"], group["y"])
                    self.assertLessEqual(node["x"] + node["width"], group["x"] + group["width"])
                    self.assertLessEqual(node["y"] + node["height"], group["y"] + group["height"])


if __name__ == "__main__":
    unittest.main()

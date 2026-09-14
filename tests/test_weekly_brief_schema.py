from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from validate_weekly_brief import (  # noqa: E402
    DEFAULT_FORMAT_LIMITS,
    REQUIRED_COMPANIES,
    validate_headlines,
    validate_v2_compactness,
    validate_v2_company_details,
    validate_report,
    validate_v2_structure,
)
from graph_update_policy import extract_graph_asset_date, has_meaningful_supply_change  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


def valid_report(changed_edge_ids: list[str] | None = None) -> str:
    changed_edge_ids = changed_edge_ids or ["E01"]
    headlines = "\n".join(
        f"{index}. **Apple：事件 {index}。** 重要性：改变收入预期。[来源](https://example.com/{index})"
        for index in range(1, 11)
    )
    table_rows = "\n".join(
        f"| {company} | {'重大变化' if company == 'Apple' else '无重大变化'} | 收入 | 高于预期 | 正面 | 下周公告 |"
        for company in REQUIRED_COMPANIES
    )
    unchanged = "、".join(company for company in REQUIRED_COMPANIES if company != "Apple")
    changed_rows = "\n".join(f"| {edge_id} | 新增 |" for edge_id in changed_edge_ids)
    changed_summary = "、".join(changed_edge_ids)
    return f"""# 周一晨间科技巨头简报
<!-- weekly-brief-schema: 2 -->
- 覆盖期间：2026-08-17 至 2026-08-23（Asia/Shanghai）
- 生成时间：2026-08-24 09:00（Asia/Shanghai）
## 1. 本周最重要的 10 件事
{headlines}
## 2. 投资判断速览
| 公司 | 本周变化 | 影响指标 | 预期差 | 判断 | 验证条件 |
| --- | --- | --- | --- | --- | --- |
{table_rows}
## 3. 发生变化的公司
### 3.1 Apple
- 日期：2026-08-24
- 事件：发布新产品
- 投资影响：提高服务收入
- 影响指标：服务收入增速
- 预期差：高于市场预期
- 验证条件：下季度财报披露增速
- 可信度：已确认
- 来源：[来源](https://example.com/apple)
### 3.2 无重大变化公司
- {unchanged}：未发现可确认重大事件。
## 4. 跨公司与产业链判断
1. 第一条判断。
2. 第二条判断。
3. 第三条判断。
## 5. 下周催化与验证条件
1. **财报。** 触发条件：公司发布财报。可能影响：收入预期。
## 6. 研究附录：产业链与图谱
### 6.1 图谱更新状态与可视化
- 产品图：沿用 2026-08-17。
- 供应图：本期更新。
![产品图](../assets/2026-08-24_product_relationships.svg)
[产品 Canvas](../assets/2026-08-24_product_relationships.canvas)
![供应图](../assets/2026-08-24_supply_relationships.svg)
[供应 Canvas](../assets/2026-08-24_supply_relationships.canvas)
### 6.2 本周供应关系变化表
| Edge ID | 变化类型 |
| --- | --- |
{changed_rows}
### 6.3 与上周的区别
- 新增关系：{changed_summary}。
## 7. 本期自检
- 通过。
"""


class WeeklyBriefSchemaTests(unittest.TestCase):
    def test_top5_selection_accepts_five_and_rejects_six(self) -> None:
        report = valid_report() + "\n<!-- company-selection: top5 -->\n"
        start = report.index("- 日期：", report.index("### 3.1 Apple"))
        end = report.index("### 3.2 无重大变化公司")
        event = report[start:end]
        validate_v2_company_details(report[:start] + event * 5 + report[end:], REQUIRED_COMPANIES)
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            validate_v2_company_details(report[:start] + event * 6 + report[end:], REQUIRED_COMPANIES)

    def test_more_than_four_company_events_keep_all_eight_fields(self) -> None:
        report = valid_report()
        start = report.index("- 日期：", report.index("### 3.1 Apple"))
        end = report.index("### 3.2 无重大变化公司")
        event = report[start:end]
        expanded = report[:start] + event * 5 + report[end:]
        validate_v2_company_details(expanded, REQUIRED_COMPANIES)
        broken = expanded.replace("- 验证条件：下季度财报披露增速\n", "", 1)
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            validate_v2_company_details(broken, REQUIRED_COMPANIES)

    def test_twelve_headlines_and_fact_driven_length_are_permanent(self) -> None:
        items = "\n".join(f"{i}. 事件{i}。重要性：独立事实。[来源](https://example.com/{i})" for i in range(1, 13))
        report = f"## 1. 本周最重要的 12 件事\n{items}\n## 2. 投资判断速览"
        validate_headlines(report, True)
        validate_v2_compactness("正文\n" * 300)
        validate_v2_compactness("长" * 24001)
        validate_v2_compactness("完整事实\n" * 20000)

    def test_explicit_historical_character_limit_is_still_enforced(self) -> None:
        limits = {**DEFAULT_FORMAT_LIMITS, "core_chars": 24000}
        validate_v2_compactness("长" * 24000, limits)
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            validate_v2_compactness("长" * 24001, limits)

    def setUp(self) -> None:
        self.baseline = {"edges": [{"edge_id": "E01", "changed_this_week": "new"}]}

    def test_valid_v2_structure(self) -> None:
        report = valid_report()
        validate_headlines(report, schema_v2=True)
        validate_v2_structure(report, self.baseline, REQUIRED_COMPANIES)

    def test_up_to_twelve_headlines_are_allowed(self) -> None:
        for count in (1, 3, 8, 10, 11, 12):
            with self.subTest(count=count):
                items = "\n".join(
                    f"{i}. **公司：事件 {i}。** 重要性：有直接证据。[来源](https://example.com/{i})"
                    for i in range(1, count + 1)
                )
                validate_headlines(f"## 1. 本周最重要的 {count} 件事\n{items}\n## 2. 投资判断速览", True)

    def test_zero_headlines_require_explicit_statement(self) -> None:
        validate_headlines("## 1. 本周重大事件\n本周未发现可确认重大事件。\n## 2. 投资判断速览", True)
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            validate_headlines("## 1. 本周重大事件\n\n## 2. 投资判断速览", True)

    def test_wrong_count_skipped_number_and_more_than_twelve_fail(self) -> None:
        cases = [
            "## 1. 本周最重要的 10 件事\n1. One",
            "## 1. 本周最重要的 2 件事\n1. One\n3. Three",
            "## 1. 本周最重要的 13 件事\n" + "\n".join(f"{i}. Item" for i in range(1, 14)),
        ]
        for report in cases:
            with self.subTest(report=report), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                validate_headlines(report + "\n## 2. 投资判断速览", True)

    def test_identical_headlines_cannot_fill_slots(self) -> None:
        item = "**公司：同一事件。** 重要性：同一影响。[来源](https://example.com/)"
        report = f"## 1. 本周最重要的 2 件事\n1. {item}\n2. {item}\n## 2. 投资判断速览"
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            validate_headlines(report, True)

    def test_mermaid_is_rejected_in_v2(self) -> None:
        report = valid_report().replace("## 7. 本期自检", "```mermaid\nflowchart LR\n```\n## 7. 本期自检")
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            validate_v2_structure(report, self.baseline, REQUIRED_COMPANIES)

    def _validate_large_baseline(self, duplicate_id: bool = False) -> None:
        template = {
            "supplier": "Apple", "customer": "Ford", "product_or_service": "Maps",
            "relationship_type": "software", "evidence_date": "2026-08-18",
            "source_type": "official", "last_seen": "2026-08-24", "status": "confirmed",
            "confidence": "high", "confidence_reason": "Official announcement",
            "markdown_section_ref": "6.2 E01", "sources": ["https://www.apple.com/"],
        }
        edges = [
            dict(template, edge_id=f"E{index:02}", changed_this_week="new" if index == 1 else "no_new")
            for index in range(1, 29)
        ]
        if duplicate_id:
            edges[-1]["edge_id"] = edges[-2]["edge_id"]
        baseline = {
            "coverage_period": {"start": "2026-08-17", "end": "2026-08-23"},
            "companies": REQUIRED_COMPANIES, "edges": edges,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "2026-08-24_weekly_morning_brief.md"
            report.write_text(valid_report(), encoding="utf-8")
            state = root / "baseline.json"
            state.write_text(json.dumps(baseline), encoding="utf-8")
            latest = root / "latest.md"
            latest.write_text(f"[latest]({report.name})", encoding="utf-8")
            validate_report(report, state, latest)

    def test_v2_cumulative_baseline_can_exceed_25_edges(self) -> None:
        self._validate_large_baseline()

    def test_v2_large_baseline_still_rejects_duplicate_edge_ids(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            self._validate_large_baseline(duplicate_id=True)

    def test_v2_report_validates_against_current_graph_artifacts(self) -> None:
        import json

        baseline_path = ROOT / "state" / "supply_graph_baseline.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        changed_ids = {
            str(edge["edge_id"])
            for edge in baseline["edges"]
            if has_meaningful_supply_change(edge)
        }
        report_date = str(baseline["generation_date"])
        report_path = ROOT / "reports" / f"{report_date}_weekly_morning_brief.md"
        report_text = report_path.read_text(encoding="utf-8")
        product_asset_date = extract_graph_asset_date(report_text, "product")
        supply_asset_date = extract_graph_asset_date(report_text, "supply")
        self.assertIsNotNone(product_asset_date)
        self.assertIsNotNone(supply_asset_date)

        validate_report(
            report_path,
            baseline_path,
            ROOT / "reports" / "latest.md",
            product_graph_path=Path("state/product_relationships_2026.json"),
            product_image_path=Path(f"assets/{product_asset_date}_product_relationships.svg"),
            product_canvas_path=Path(f"assets/{product_asset_date}_product_relationships.canvas"),
            supply_image_path=Path(f"assets/{supply_asset_date}_supply_relationships.svg"),
            supply_canvas_path=Path(f"assets/{supply_asset_date}_supply_relationships.canvas"),
            expected_changed_edge_ids=changed_ids,
        )


if __name__ == "__main__":
    unittest.main()

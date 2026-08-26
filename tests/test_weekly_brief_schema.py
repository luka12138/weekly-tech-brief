from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from validate_weekly_brief import (  # noqa: E402
    REQUIRED_COMPANIES,
    validate_headlines,
    validate_report,
    validate_v2_structure,
)


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
    def setUp(self) -> None:
        self.baseline = {"edges": [{"edge_id": "E01", "changed_this_week": "new"}]}

    def test_valid_v2_structure(self) -> None:
        report = valid_report()
        validate_headlines(report, schema_v2=True)
        validate_v2_structure(report, self.baseline, REQUIRED_COMPANIES)

    def test_mermaid_is_rejected_in_v2(self) -> None:
        report = valid_report().replace("## 7. 本期自检", "```mermaid\nflowchart LR\n```\n## 7. 本期自检")
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            validate_v2_structure(report, self.baseline, REQUIRED_COMPANIES)

    def test_v2_report_validates_against_current_graph_artifacts(self) -> None:
        import json

        baseline_path = ROOT / "state" / "supply_graph_baseline.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        changed_ids = [
            str(edge["edge_id"])
            for edge in baseline["edges"]
            if edge.get("changed_this_week") in {"new", "strengthened", "risk", "weakened"}
        ]
        report_text = valid_report(changed_ids)
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory) / "reports"
            reports.mkdir()
            report_path = reports / "2026-08-24_weekly_morning_brief.md"
            report_path.write_text(report_text, encoding="utf-8")
            latest_path = reports / "latest.md"
            latest_path.write_text("[latest](2026-08-24_weekly_morning_brief.md)\n", encoding="utf-8")
            validate_report(
                report_path,
                baseline_path,
                latest_path,
                product_graph_path=Path("state/product_relationships_2026.json"),
                product_image_path=Path("assets/2026-08-24_product_relationships.svg"),
                product_canvas_path=Path("assets/2026-08-24_product_relationships.canvas"),
                supply_image_path=Path("assets/2026-08-24_supply_relationships.svg"),
                supply_canvas_path=Path("assets/2026-08-24_supply_relationships.canvas"),
            )


if __name__ == "__main__":
    unittest.main()

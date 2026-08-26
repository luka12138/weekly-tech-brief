# 周一晨间科技巨头简报
<!-- weekly-brief-schema: 2 -->
- 覆盖期间：YYYY-MM-DD 至 YYYY-MM-DD（Asia/Shanghai）
- 生成时间：YYYY-MM-DD HH:mm（Asia/Shanghai）
- 本期文件：reports/YYYY-MM-DD_weekly_morning_brief.md

## 1. 本周最重要的 10 件事
1. **公司：事件一句话。** 重要性：说明相对市场预期和投资含义。[来源](https://example.com)
2. 按同一格式写至第 10 项；每项只保留事件、重要性和来源。

## 2. 投资判断速览
| 公司 | 本周变化 | 影响指标 | 预期差 | 判断 | 验证条件 |
| --- | --- | --- | --- | --- | --- |
| Apple | 重大变化或无重大变化 | 收入/毛利率/capex/出货量等 | 高于/低于/符合/尚未形成预期 | 正面/负面/混合/中性 | 可观察且带时间窗口的条件 |
| Microsoft |  |  |  |  |  |
| Alphabet / Google |  |  |  |  |  |
| Amazon / AWS |  |  |  |  |  |
| Meta |  |  |  |  |  |
| NVIDIA |  |  |  |  |  |
| Tesla |  |  |  |  |  |
| OpenAI |  |  |  |  |  |
| Anthropic |  |  |  |  |  |
| Samsung Electronics |  |  |  |  |  |
| SK Hynix |  |  |  |  |  |
| TSMC |  |  |  |  |  |

## 3. 发生变化的公司
只为存在可确认重大变化的公司创建小节，每家公司通常 1-4 条。

### 3.1 Company
- 日期：YYYY-MM-DD
- 事件：发生了什么
- 投资影响：对业务、竞争、供应链、监管或资本开支的影响
- 影响指标：收入、毛利率、资本开支、出货量、利用率、市场份额等
- 预期差：高于/低于/符合市场预期，或尚未形成可验证预期
- 验证条件：下一项可观察证据及时间窗口
- 可信度：已确认 / 多源确认 / 未确认但值得关注 / 媒体报道待确认
- 来源：[原始或权威来源](https://example.com)

### 3.N 无重大变化公司
- Company A、Company B：未发现可确认重大事件；只用一行汇总，不为每家公司重复创建空小节。

## 4. 跨公司与产业链判断
1. 保留 3-5 条真正改变行业判断的横向结论。
2. 每条说明受益方、承压方及需要继续验证的变量。
3. 不复述第 3 节新闻。

## 5. 下周催化与验证条件
1. **事项。** 触发条件：可观察的公告、数据或时间点。可能影响：对应公司和指标。

## 6. 研究附录：产业链与图谱
### 6.1 图谱更新状态与可视化
- 产品图：本期更新 / 沿用 YYYY-MM-DD。原因：来自 `scripts/plan_graph_updates.py` 的决策。

![主营产品上下游关系图](../assets/PRODUCT_GRAPH_DATE_product_relationships.svg)

[Obsidian Canvas 源文件](../assets/PRODUCT_GRAPH_DATE_product_relationships.canvas)

- 供应图：本期更新 / 沿用 YYYY-MM-DD。原因：来自 `scripts/plan_graph_updates.py` 的决策。

![供应关系图](../assets/SUPPLY_GRAPH_DATE_supply_relationships.svg)

[Obsidian Canvas 源文件](../assets/SUPPLY_GRAPH_DATE_supply_relationships.canvas)

### 6.2 本周供应关系变化表
只列 `changed_this_week` 为新增、强化、弱化或风险的关系；完整基线保留在 JSON，不再复制完整关系表或 Mermaid。

| Edge ID | 变化类型 | 供应方 -> 客户 | 产品/服务 | 投资影响 | 本周证据与限制 | 来源 |
| --- | --- | --- | --- | --- | --- | --- |
| E00 | 新增/强化/弱化/风险 | Supplier -> Customer | 具体产品或服务 | 影响指标和方向 | 直接证据与限制 | [来源](https://example.com) |

若无变化，改写为：本周无供应关系实质变化；沿用上一期供应图。

### 6.3 与上周的区别
- 新增关系：只写本周新增。
- 强化关系：只写本周强化。
- 弱化或风险关系：只写本周新增风险。
- 无明显变化：一句话说明，不重复完整基线。

## 7. 本期自检
- 日期范围和 12 家公司覆盖正确；第 1 节恰好 10 件事。
- 变化公司事件均包含影响指标、预期差、验证条件和来源。
- 无重大变化公司已在一个小节集中汇总。
- 图谱生成/沿用状态与 `scripts/plan_graph_updates.py` 一致；Canvas/SVG 可解析。
- 本周变化表只包含实质变化 Edge ID；完整关系以 JSON 为准。
- 来源审查和质量闸门状态如实记录。

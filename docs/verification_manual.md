# 查验手册与成型流程

本文档用于检查每周晨报是否“能读、能查、能复盘、能自动延续”。

## 一、成型流程总览

每周周报必须按以下顺序形成：

1. 确定覆盖周期
2. 读取上一期基线
3. 联网检索本周重大事件
4. 写入周报正文
5. 更新供应关系基线
6. 更新年度产品关系基线
7. 运行图表更新计划，仅生成需要变化的 Canvas/SVG
8. 审查消息来源真实性
9. 运行主质量闸门
10. 提交并推送 GitHub

任何一步失败，都不能在周报中写“已完成”。

## 二、覆盖周期查验

周一 09:00 生成时，覆盖周期应为上一完整自然周：

```text
周一 00:00 至周日 23:59
时区：Asia/Shanghai
```

查验点：

- 周报开头是否写明日期范围
- `state/supply_graph_baseline.json` 的 `coverage_period` 是否一致
- 周报事件日期是否落在覆盖周期内
- 若事件早于覆盖周期，是否写明“覆盖周外但本周延续跟踪”或“本周新进展”

## 三、来源真实性审查

来源审查脚本：

```bash
python3 scripts/audit_sources.py \
  --report reports/YYYY-MM-DD_weekly_morning_brief.md \
  --baseline state/supply_graph_baseline.json \
  --product-graph state/product_relationships_YYYY.json \
  --output logs/YYYY-MM-DD_source_audit.json
```

查验点：

- 所有 URL 必须为 HTTPS
- 来源链接必须可达，或明确为付费墙/访问受限
- 来源域名必须被分类
- 官方来源优先于媒体来源
- 媒体报道必须在正文标注“媒体报道待确认”
- 年度产品关系图中的 `official_sources` 必须纳入同一份来源审查
- 带有 `claim_keywords` 的核心事实必须通过来源正文关键词匹配；若官方页面访问受限，必须在人工事实复核摘要中说明

注意：来源审查不是事实真伪的最终证明。它用于排除死链、低质量域名、伪来源、不可追溯引用，以及“链接存在但正文不支持核心事实”的常见错误。

来源审查日志必须绑定当前文件：

- `report_sha256` 必须等于当前周报文件的 SHA-256
- `baseline_sha256` 必须等于当前供应关系基线的 SHA-256
- `product_graph_sha256` 必须等于当前年度产品关系图 JSON 的 SHA-256
- `audited_urls` 必须等于当前周报、供应关系基线和年度产品关系图中抽取出的 URL 清单
- `summary.claim_failed` 必须为 0

若任一项不一致，说明审查日志已过期，必须重新运行来源审查。

## 四、逐条事实核验表

来源可达不等于事实成立。每条重大事件在写入周报前，应按下表核验：

| 事件编号 | 公司 | 周报结论 | 来源链接 | 来源类型 | 来源原文支持点摘要 | 是否覆盖周期内 | 是否需要降级措辞 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F01 | 示例公司 | 示例结论 | https://example.com | 官方/媒体/监管 | 用一句中文概括来源中直接支持结论的内容 | 是/否 | 否/媒体报道待确认/基线不足 |

填写规则：

- 官方来源能直接支持的结论，可以写为“已宣布”“已披露”
- 媒体来源支持但官方未确认的结论，必须写“媒体报道”“待官方确认”
- 来源只支持背景或趋势，不能写成具体订单、具体客户或具体金额
- 覆盖周期外事件只能作为延续跟踪，不能写成本周新增事件
- 付费墙或访问受限来源要在摘要中写明可见信息来自标题、摘要、公开片段还是已有订阅访问

## 五、周报正文查验

schema v2 正文必须包含：

- 本周最重要的 10 件事
- 12 家公司投资判断速览
- 仅展开存在重大变化的公司
- 无重大变化公司集中一行汇总
- 跨公司与产业链判断
- 下周催化与验证条件
- 研究附录
- 本期自检

每条事件必须有：

```text
日期
事件
投资影响
影响指标
预期差
验证条件
可信度
来源
```

不允许：

- 没来源的结论
- 把传闻写成事实
- 把股价波动本身当成重大事件，除非有明确催化因素
- 为了凑数写入小新闻

## 六、供应关系查验

schema v2 的供应关系分为两个职责清晰的层：

1. `state/supply_graph_baseline.json` 保存完整事实基线
2. Canvas/SVG 提供唯一可视化；周报 6.2 只列本周实质变化

不再保留 Mermaid，也不在周报中复制完整关系表。

查验命令：

```bash
python3 scripts/validate_weekly_brief.py \
  --report reports/YYYY-MM-DD_weekly_morning_brief.md \
  --baseline state/supply_graph_baseline.json \
  --latest reports/latest.md \
  --source-audit logs/YYYY-MM-DD_source_audit.json \
  --product-graph state/product_relationships_YYYY.json \
  --product-image assets/PRODUCT_GRAPH_DATE_product_relationships.svg \
  --product-canvas assets/PRODUCT_GRAPH_DATE_product_relationships.canvas \
  --supply-image assets/SUPPLY_GRAPH_DATE_supply_relationships.svg \
  --supply-canvas assets/SUPPLY_GRAPH_DATE_supply_relationships.canvas
```

查验点：

- Canvas 中全部 Edge ID 必须存在于 JSON
- 6.2 只包含本周新增、强化、弱化或风险 Edge ID
- 无本周直接证据的长期关系不能标为“新增”或“增强”
- 低置信度关系必须解释限制条件

## 七、Canvas 与图片查验

每期必须引用一份产品图和一份供应图，但不要求每周创建新文件。先运行：

```bash
python3 scripts/plan_graph_updates.py --report-date YYYY-MM-DD
```

策略规则：

- 供应图仅在关系新增、强化、弱化或出现新风险时生成
- 产品图仅在季度首个周一或产品关系实质变化时生成
- 其余周沿用最近一期 `.canvas` 与 `.svg`

只有计划返回 `action: generate` 时才运行相应生成命令；返回 `reuse` 时不得复制出新的日期文件。

生成命令：

```bash
python3 scripts/build_product_graph_svg.py \
  --input state/product_relationships_YYYY.json \
  --output assets/YYYY-MM-DD_product_relationships.svg \
  --canvas-output assets/YYYY-MM-DD_product_relationships.canvas

python3 scripts/build_supply_graph_svg.py \
  --input state/supply_graph_baseline.json \
  --output assets/YYYY-MM-DD_supply_relationships.svg \
  --canvas-output assets/YYYY-MM-DD_supply_relationships.canvas

python3 scripts/validate_json_canvas.py assets/YYYY-MM-DD_*.canvas
```

查验点：

- 两张图都能在 GitHub 页面渲染
- `.canvas` 文件符合 JSON Canvas 1.0，使用唯一 16 位小写十六进制 ID
- 所有 Canvas 边引用有效，节点不重叠，并留有 50-100px 间距
- 两张 SVG 与对应 Canvas 使用同一布局和 Edge ID
- 年度产品图必须包含公司节点、主营产品节点和产品级 `PX` 关系边
- 周报 6.1 引用计划指定日期的产品图和供应图
- 图片背后的 JSON 存在且可解析

重建全部历史产物时必须使用 `state/historical_snapshot_map.json` 中的不可变 Git 快照，不得以当前基线覆盖历史关系，也不得依赖迁移后的最新提交反推旧状态。已核实的历史 URL 或事实措辞修订必须写入 `state/historical_snapshot_overrides.json`，不能静默改写原提交：

```bash
python3 scripts/rebuild_historical_obsidian_graphs.py --prune-redundant
python3 scripts/migrate_historical_briefs_v2.py
python3 scripts/rebuild_historical_source_audits.py --allow-cache-fallback
python3 scripts/validate_json_canvas.py assets/*.canvas
python3 scripts/validate_historical_briefs.py --require-source-audits
```

历史来源批量审计会对 URL 去重。仅当实时网络瞬时失败且同一 URL 或同一 claim 过去已经成功时，`--allow-cache-fallback` 才允许复用，并在日志中保留 `cache_fallback` 与实时失败原因；没有既往成功记录的来源仍然失败。

## 八、年度产品关系基线查验

文件：

```text
state/product_relationships_YYYY.json
```

查验点：

- 包含 12 家覆盖公司
- 每家公司有主营产品列表
- 每家公司有官方来源
- `product_nodes` 必须覆盖每家公司全部主营产品
- 每个主营产品节点必须至少进入一条 `product_edges`
- 产品级边使用 `PX01`、`PX02` 等 Edge ID
- 每条产品关系有 `P01`、`P02` 等 Edge ID
- 每条关系有 `evidence_level`
- 证据不足的关系不能标为 confirmed
- 缺少直接证据的历史关系必须使用 `market_consensus_needs_direct_source` 或类似弱证据等级
- 无法找到直接证据的边应从主图删除，改为正文背景说明

优先来源：

- 年报
- 投资者关系页面
- 监管文件
- 公司新闻稿

## 九、提交前最终检查

提交前必须执行：

```bash
python3 scripts/run_quality_gate.py
```

如需分步排错，执行：

```bash
python3 scripts/audit_sources.py \
  --report reports/YYYY-MM-DD_weekly_morning_brief.md \
  --baseline state/supply_graph_baseline.json \
  --product-graph state/product_relationships_YYYY.json \
  --output logs/YYYY-MM-DD_source_audit.json

python3 scripts/validate_weekly_brief.py \
  --report reports/YYYY-MM-DD_weekly_morning_brief.md \
  --baseline state/supply_graph_baseline.json \
  --latest reports/latest.md \
  --source-audit logs/YYYY-MM-DD_source_audit.json \
  --product-graph state/product_relationships_YYYY.json \
  --product-image assets/PRODUCT_GRAPH_DATE_product_relationships.svg \
  --product-canvas assets/PRODUCT_GRAPH_DATE_product_relationships.canvas \
  --supply-image assets/SUPPLY_GRAPH_DATE_supply_relationships.svg \
  --supply-canvas assets/SUPPLY_GRAPH_DATE_supply_relationships.canvas

git diff --check
git status
```

全部通过后再提交：

```bash
git add reports/ assets/ state/ logs/ scripts/ docs/ README.md
git commit -m "chore: add weekly brief YYYY-MM-DD"
git push
```

## 十、失败处理

如果来源审查失败：

- 检查是否为死链
- 检查是否为付费墙
- 尝试替换为官方来源或其他权威来源
- 不要删除失败来源后继续保留无来源结论

如果主校验失败：

- 先按错误信息修复
- 不要绕过脚本
- 不要提交半成品

如果 GitHub 推送失败：

- 检查网络和代理
- 检查 `gh auth status`
- 检查 GitHub token 权限
- 本地提交可以保留，但周报自检不能写“已推送成功”

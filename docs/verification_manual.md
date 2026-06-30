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
7. 生成两张 SVG 图片
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
  --output logs/YYYY-MM-DD_source_audit.json
```

查验点：

- 所有 URL 必须为 HTTPS
- 来源链接必须可达，或明确为付费墙/访问受限
- 来源域名必须被分类
- 官方来源优先于媒体来源
- 媒体报道必须在正文标注“媒体报道待确认”

注意：来源审查不是事实真伪的最终证明。它用于排除死链、低质量域名、伪来源和不可追溯引用。

来源审查日志必须绑定当前文件：

- `report_sha256` 必须等于当前周报文件的 SHA-256
- `baseline_sha256` 必须等于当前供应关系基线的 SHA-256
- `audited_urls` 必须等于当前周报和基线中抽取出的 URL 清单

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

正文必须包含：

- 本周最重要的 5-8 件事
- 10 家公司影响力速览
- 每家公司单独小节
- 跨公司与产业链观察
- 下周需关注
- 供应关系图谱与周度变化
- 本期自检

每条事件必须有：

```text
日期
事件
影响
可信度
来源
```

不允许：

- 没来源的结论
- 把传闻写成事实
- 把股价波动本身当成重大事件，除非有明确催化因素
- 为了凑数写入小新闻

## 六、供应关系查验

供应关系有三层：

1. Markdown 中的 Mermaid 图
2. 周报 6.2 的供应关系明细表
3. `state/supply_graph_baseline.json`

三者必须使用同一组 `Edge ID`。

查验命令：

```bash
python3 scripts/validate_weekly_brief.py \
  --report reports/YYYY-MM-DD_weekly_morning_brief.md \
  --baseline state/supply_graph_baseline.json \
  --latest reports/latest.md \
  --source-audit logs/YYYY-MM-DD_source_audit.json \
  --product-graph state/product_relationships_YYYY.json \
  --product-image assets/YYYY-MM-DD_product_relationships.svg \
  --supply-image assets/YYYY-MM-DD_supply_relationships.svg
```

查验点：

- Mermaid 中每条边都有 `E01`、`E02` 等 Edge ID
- 6.2 表格中存在相同 Edge ID
- JSON 中存在相同 Edge ID
- 无本周直接证据的长期关系不能标为“新增”或“增强”
- 低置信度关系必须解释限制条件

## 七、两张图片查验

每周必须生成两张图：

```text
assets/YYYY-MM-DD_product_relationships.svg
assets/YYYY-MM-DD_supply_relationships.svg
```

生成命令：

```bash
python3 scripts/build_product_graph_svg.py \
  --input state/product_relationships_YYYY.json \
  --output assets/YYYY-MM-DD_product_relationships.svg

python3 scripts/build_supply_graph_svg.py \
  --input state/supply_graph_baseline.json \
  --output assets/YYYY-MM-DD_supply_relationships.svg
```

查验点：

- 两张图都能在 GitHub 页面渲染
- 两张图都采用 Obsidian 风格网络图
- 周报 6.0 引用产品上下游图
- 周报 6.1 引用供应关系图
- 图片背后的 JSON 存在且可解析

## 八、年度产品关系基线查验

文件：

```text
state/product_relationships_YYYY.json
```

查验点：

- 包含 10 家覆盖公司
- 每家公司有主营产品列表
- 每家公司有官方来源
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
  --output logs/YYYY-MM-DD_source_audit.json

python3 scripts/validate_weekly_brief.py \
  --report reports/YYYY-MM-DD_weekly_morning_brief.md \
  --baseline state/supply_graph_baseline.json \
  --latest reports/latest.md \
  --source-audit logs/YYYY-MM-DD_source_audit.json \
  --product-graph state/product_relationships_YYYY.json \
  --product-image assets/YYYY-MM-DD_product_relationships.svg \
  --supply-image assets/YYYY-MM-DD_supply_relationships.svg

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

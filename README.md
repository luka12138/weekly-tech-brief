# 每周科技巨头晨间简报

这个仓库用于保存每周一生成的中文科技行业晨报，以及支撑周度对比的结构化供应链数据、来源审查日志和可视化图。

现行执行规则见[项目 skill](.agents/skills/weekly-tech-brief/SKILL.md)、[时点规范](docs/point_in_time_policy.md)和[有限筛选规范](docs/research_coverage.md)。每家公司0-5条重要信息，不凑数；时点证据和具体版本必须核实，机器通过不等于零遗漏。

最新晨报入口：

- [reports/latest.md](reports/latest.md)

本项目当前覆盖 12 家公司：

- Apple
- Microsoft
- Alphabet / Google
- Amazon / AWS
- Meta
- NVIDIA
- Tesla
- OpenAI
- Anthropic
- Samsung Electronics
- SK Hynix
- TSMC

## 当前产物

- 周报正文：[reports/2026-09-14_weekly_morning_brief.md](reports/2026-09-14_weekly_morning_brief.md)
- 年度主营产品上下游图：[assets/2026-09-14_product_relationships.svg](assets/2026-09-14_product_relationships.svg)
- 年度产品关系 Canvas：[assets/2026-09-14_product_relationships.canvas](assets/2026-09-14_product_relationships.canvas)
- 本周供应关系图：[assets/2026-09-14_supply_relationships.svg](assets/2026-09-14_supply_relationships.svg)
- 本周供应关系 Canvas：[assets/2026-09-14_supply_relationships.canvas](assets/2026-09-14_supply_relationships.canvas)
- 来源审查日志：[logs/2026-09-14_source_audit.json](logs/2026-09-14_source_audit.json)
- 查验手册：[docs/verification_manual.md](docs/verification_manual.md)

## 目录结构

```text
reports/
  latest.md                          # 最新周报入口
  YYYY-MM-DD_weekly_morning_brief.md # 按日期保存的周报正文

assets/
  YYYY-MM-DD_product_relationships.canvas # Obsidian 年度产品关系源图
  YYYY-MM-DD_product_relationships.svg    # GitHub 可见的年度产品关系渲染图
  YYYY-MM-DD_supply_relationships.canvas  # Obsidian 本周供应关系源图
  YYYY-MM-DD_supply_relationships.svg     # GitHub 可见的本周供应关系渲染图

state/
  supply_graph_baseline.json          # 下周对比用的供应关系基线
  historical_snapshot_map.json        # 历史周报到不可变 Git 快照的映射
  historical_snapshot_overrides.json  # 历史快照的有据可查 URL/事实更正
  historical_graph_plan.json          # 历史图谱生成/沿用决策记录
  product_relationships_YYYY.json     # 本年度产品上下游关系基线

logs/
  YYYY-MM-DD_source_audit.json         # 来源真实性/可达性审查日志

scripts/
  audit_sources.py                     # 来源审查脚本
  json_canvas_graphs.py                # Canvas 构建、SVG 渲染与规范校验
  build_product_graph_svg.py           # 生成年度产品 Canvas 与 SVG
  build_supply_graph_svg.py            # 生成本周供应 Canvas 与 SVG
  graph_update_policy.py               # 决定本期生成新图或沿用历史图
  plan_graph_updates.py                # 输出机器可读图表更新计划
  rebuild_historical_obsidian_graphs.py # 按各期 Git 快照重建全部历史图
  migrate_historical_briefs_v2.py      # 按历史快照重建 schema v2 周报
  rebuild_historical_source_audits.py  # 去重访问并重建全部历史来源日志
  validate_historical_briefs.py        # 用各期快照批量执行联合校验
  validate_json_canvas.py              # 独立 Canvas 校验器
  validate_weekly_brief.py             # 主质量闸门
  run_quality_gate.py                  # 单入口质量闸门

docs/
  verification_manual.md               # 查验手册与成型流程
  weekly_brief_template_v2.md          # 精简版周报结构模板

tests/
  test_graph_update_policy.py          # 图表更新策略测试
  test_weekly_brief_schema.py          # 周报 schema v2 测试
```

## 周报应包含什么

新周报使用 `<!-- weekly-brief-schema: 2 -->`，必须包含：

1. 本周最重要的至多12件事，只提炼已入选事项
2. 12 家公司的投资判断速览
3. 每家公司0-5条重要独立事项；无合格入选信息时说明有限筛选范围
4. 跨公司与产业链判断
5. 下周催化与验证条件
6. 研究附录：图谱、变化关系和上周对比
7. 本期自检

每条重大事件除日期、事件、可信度和来源外，还必须包含：

- 投资影响
- 影响指标
- 相对市场预期的预期差
- 带时间窗口的验证条件

完整模板见：[docs/weekly_brief_template_v2.md](docs/weekly_brief_template_v2.md)。仓库内历史周报已统一迁移为 schema v2；校验器仍保留 schema v1 兼容路径，用于识别尚未迁移的外部旧文件。

## 图表更新策略

完成正文预检和逐条证据后，查看图表计划：

```bash
python3 scripts/plan_graph_updates.py --report-date YYYY-MM-DD
```

- 供应图只在出现新增、强化、弱化或风险关系时生成；否则沿用最近一期图。
- 产品图只在季度首个周一或主营产品/产品级关系实质变化时生成。
- 完整供应关系只保存在 `state/supply_graph_baseline.json`；周报附录只列本周变化关系。
- schema v2 不再生成 Mermaid。JSON 是关系事实源，Canvas/SVG 是唯一可视化层。
- SVG 必须由同一 `.canvas` 布局渲染，不单独维护图数据。

## 质量闸门

生成周报后，推荐先运行单入口质量闸门：

```bash
python3 scripts/run_quality_gate.py
```

它会依次执行：

1. 正文格式预检
2. 有限筛选与逐条时点证据校验
3. 计算图表计划，只生成需要更新的 Canvas 与 SVG
4. 来源审查和主校验
5. `git diff --check`；真实提交和远端回执另验

如需分步排错，可使用下面的命令。

来源审查：

```bash
python3 scripts/audit_sources.py \
  --report reports/YYYY-MM-DD_weekly_morning_brief.md \
  --baseline state/supply_graph_baseline.json \
  --product-graph state/product_relationships_YYYY.json \
  --output logs/YYYY-MM-DD_source_audit.json
```

主校验：

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

主校验会检查：

- JSON 能否解析
- 覆盖日期是否写入周报
- 12 家公司是否全部覆盖
- 第1节是否按实际数量连续编号，最多12件，不凑数
- `reports/latest.md` 是否指向真实文件
- 入选事件八字段与关键限制完整，不设行数或字符硬上限
- 变化公司是否包含影响指标、预期差和验证条件
- 无重大变化公司是否集中汇总，而非重复创建空小节
- 6.2 是否只列本周实质变化的 `Edge ID`
- 是否移除了与 JSON/Canvas 重复的 Mermaid 层
- 低置信度、媒体报道、基线不足关系是否明确标注
- 来源审查是否存在且没有不可达或未分类来源
- 来源审查日志是否由当前周报、当前供应关系基线和当前年度产品关系图生成
- 来源审查是否纳入年度产品关系图官方来源
- 核心事实 claim 是否通过来源正文关键词匹配，或被标记为官方访问受限需人工复核
- 策略决定生成或沿用的 SVG/Canvas 是否存在，并被周报正确引用
- 两个 Canvas 是否符合 JSON Canvas 1.0，且 ID 唯一、节点引用有效、节点不重叠
- 供应关系 Canvas 的 Edge ID 是否与基线 JSON 完全一致
- 年度产品关系 JSON 是否包含 12 家公司、全部主营产品节点、产品级关系边及官方来源
- 周报文件日期是否为周一，覆盖周期是否等于上一完整自然周

## 手动生成流程

完整流程见：[docs/verification_manual.md](docs/verification_manual.md)

简化流程如下；图表文件日期以计划输出为准，不一定等于本期周报日期：

```bash
python3 scripts/plan_graph_updates.py --report-date YYYY-MM-DD
python3 scripts/run_quality_gate.py --report reports/YYYY-MM-DD_weekly_morning_brief.md
python3 -m unittest discover -s tests -v
```

仓库级历史迁移使用固定快照映射，避免新提交覆盖原始状态定位。完整顺序为：

```bash
python3 scripts/rebuild_historical_obsidian_graphs.py --prune-redundant
python3 scripts/migrate_historical_briefs_v2.py
python3 scripts/rebuild_historical_source_audits.py --allow-cache-fallback
python3 scripts/validate_json_canvas.py assets/*.canvas
python3 scripts/validate_historical_briefs.py --require-source-audits
```

缓存回退只允许复用相同 URL 或相同结构化 claim 的既有成功结果，并会在审计 JSON 中写入 `cache_fallback`；从未验证成功的来源不能借此通过。

通过后再提交：

```bash
git status
# 逐项暂存本期清单，不暂存整个目录或夹带历史改稿
# git add -- <本期报告、证据、状态、图谱和必要依赖文件>
git commit -m "chore: add weekly brief YYYY-MM-DD"
git push
```

## 自动化运行方式

目标运行方式：

1. Windows 台式机每周一 09:00（Asia/Shanghai）触发 Codex 自动化。
2. 自动化读取上一期 `reports/latest.md` 和 `state/supply_graph_baseline.json`。
3. 读取项目skill，有限官方筛选加独立重要性校准，生成每家0-5条的新周报。
4. 更新供应关系 JSON；只有产品关系实质变化时才更新产品关系 JSON 的刷新日期。
5. 先预检正文并绑定逐条时点证据，再运行图表计划生成或沿用图。
6. 执行来源审查，并写入当前周报、供应关系基线和年度产品关系图的 SHA-256。
7. 执行主质量闸门，确认来源审查日志与当前文件一致，并检查核心事实 claim。
8. 校验通过后提交并推送到 GitHub。
9. Mac 或其他设备通过 GitHub 查看 `reports/latest.md`。

Mac 查看：

```bash
cd "/Users/qzdmbp/Documents/每周简报"
git pull
open reports/latest.md
```

## 证据规则

优先使用：

- 公司官网新闻稿
- 投资者关系页面
- 财报、电话会材料、年报
- SEC、交易所、监管机构、法院或政府文件
- Reuters、Bloomberg、WSJ、FT、Nikkei Asia、CNBC、The Information、财新等权威媒体

媒体报道、市场观点、供应链传闻必须明确标注，不能写成已确认事实。

## 公开仓库注意事项

本仓库当前为公开仓库。不要提交：

- GitHub token
- API key
- `.env`
- 本地 Codex 配置
- Cookie 或浏览器凭据
- 未脱敏的私人资料

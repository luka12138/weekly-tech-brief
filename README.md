# 每周科技巨头晨间简报

这个仓库用于保存每周一生成的中文科技行业晨报，以及支撑周度对比的结构化供应链数据、来源审查日志和可视化图。

最新晨报入口：

- [reports/latest.md](reports/latest.md)

本项目当前覆盖 10 家公司：

- Apple
- Microsoft
- Alphabet / Google
- Amazon / AWS
- Meta
- NVIDIA
- Tesla
- Samsung Electronics
- SK Hynix
- TSMC

## 当前产物

- 周报正文：[reports/2026-07-20_weekly_morning_brief.md](reports/2026-07-20_weekly_morning_brief.md)
- 年度主营产品上下游图：[assets/2026-07-20_product_relationships.svg](assets/2026-07-20_product_relationships.svg)
- 本周供应关系图：[assets/2026-07-20_supply_relationships.svg](assets/2026-07-20_supply_relationships.svg)
- 来源审查日志：[logs/2026-07-20_source_audit.json](logs/2026-07-20_source_audit.json)
- 人工事实复核摘要：[logs/2026-07-20_fact_check.md](logs/2026-07-20_fact_check.md)
- 查验手册：[docs/verification_manual.md](docs/verification_manual.md)

## 目录结构

```text
reports/
  latest.md                          # 最新周报入口
  YYYY-MM-DD_weekly_morning_brief.md # 按日期保存的周报正文

assets/
  YYYY-MM-DD_product_relationships.svg # 年度主营产品上下游图
  YYYY-MM-DD_supply_relationships.svg  # 本周供应关系图

state/
  supply_graph_baseline.json          # 下周对比用的供应关系基线
  product_relationships_YYYY.json     # 本年度产品上下游关系基线

logs/
  YYYY-MM-DD_source_audit.json         # 来源真实性/可达性审查日志

scripts/
  audit_sources.py                     # 来源审查脚本
  build_product_graph_svg.py           # 生成年度产品关系图
  build_supply_graph_svg.py            # 生成本周供应关系图
  validate_weekly_brief.py             # 主质量闸门
  run_quality_gate.py                  # 单入口质量闸门

docs/
  verification_manual.md               # 查验手册与成型流程
```

## 周报应包含什么

每期周报必须包含：

1. 本周最重要的 5-8 件事
2. 10 家公司的影响力速览
3. 按公司分组的重大事件
4. 跨公司与产业链观察
5. 下周需关注事项
6. 十家公司供应关系图谱与周度变化
7. 本期自检

第 6 节必须同时包含两张图：

- 年度主营产品上下游图：从 `state/product_relationships_YYYY.json` 生成
- 本周供应关系图：从 `state/supply_graph_baseline.json` 生成

两张图均采用类似 Obsidian 图谱视图的网络样式，便于在 GitHub 页面直接查看。

## 质量闸门

生成周报后，推荐先运行单入口质量闸门：

```bash
python3 scripts/run_quality_gate.py
```

它会依次执行：

1. 生成年度主营产品上下游图
2. 生成本周供应关系图
3. 执行来源审查
4. 执行主校验
5. 执行 `git diff --check`

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
  --product-image assets/YYYY-MM-DD_product_relationships.svg \
  --supply-image assets/YYYY-MM-DD_supply_relationships.svg
```

主校验会检查：

- JSON 能否解析
- 覆盖日期是否写入周报
- 10 家公司是否全部覆盖
- `reports/latest.md` 是否指向真实文件
- Mermaid 图、6.2 表格、JSON 基线的 `Edge ID` 是否一致
- 低置信度、媒体报道、基线不足关系是否明确标注
- 来源审查是否存在且没有不可达或未分类来源
- 来源审查日志是否由当前周报、当前供应关系基线和当前年度产品关系图生成
- 来源审查是否纳入年度产品关系图官方来源
- 核心事实 claim 是否通过来源正文关键词匹配，或被标记为官方访问受限需人工复核
- 两张 SVG 图片是否存在，并被周报引用
- 年度产品关系 JSON 是否包含 10 家公司、全部主营产品节点、产品级关系边及官方来源
- 周报文件日期是否为周一，覆盖周期是否等于上一完整自然周

## 手动生成流程

完整流程见：[docs/verification_manual.md](docs/verification_manual.md)

简化命令如下：

```bash
python3 scripts/build_product_graph_svg.py \
  --input state/product_relationships_YYYY.json \
  --output assets/YYYY-MM-DD_product_relationships.svg

python3 scripts/build_supply_graph_svg.py \
  --input state/supply_graph_baseline.json \
  --output assets/YYYY-MM-DD_supply_relationships.svg

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
  --product-image assets/YYYY-MM-DD_product_relationships.svg \
  --supply-image assets/YYYY-MM-DD_supply_relationships.svg
```

通过后再提交：

```bash
git status
git add reports/ assets/ state/ logs/ scripts/ docs/ README.md
git commit -m "chore: add weekly brief YYYY-MM-DD"
git push
```

## 自动化运行方式

目标运行方式：

1. Windows 台式机每周一 09:00（Asia/Shanghai）触发 Codex 自动化。
2. 自动化读取上一期 `reports/latest.md` 和 `state/supply_graph_baseline.json`。
3. 联网检索并生成新周报。
4. 更新产品关系 JSON 和供应关系 JSON。
5. 生成两张 Obsidian 风格 SVG。
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

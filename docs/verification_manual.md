# 查验手册与成型流程

本文档用于检查每周晨报是否“能读、能查、能复盘、能自动延续”。

**先读 [时点与事实核验规范](point_in_time_policy.md)。日期、网页版本、财报期间、旧闻、预测和历史回测以该文件为唯一维护正文；跨任务取舍见 [规则核对记录](rule_decisions.md)。本手册负责操作顺序。**

## 一、成型流程总览

定时执行及维护只在“每周科技巨头晨间简报”任务内继续。运行前读[单一任务交接](task_consolidation.md)；原“主对话”“小修小改”仅作历史查询，不能另行触发生成。原定时器 `automation` 已绑定保留任务，每周一上海 09:00 执行，不创建新一期任务。

每周周报必须按以下顺序形成：

1. 读 skill 和时点规范，确定覆盖周期及上海时区的排他截止点
2. 按[上下文与缓存输入控制](context_efficiency.md)读上期正文、完整基线索引并展开需核记录；未有可靠已读基线时分批读全量
3. 按[重大事件覆盖与监管防漏](research_coverage.md)的方案二和[官方来源入口表](research_source_routes.md)对12家公司有限筛选并作一轮独立重要性校准，兼看监管；每家入选0-5条。先排名，再恢复入选材料，只补明确缺口；未入选候选和不相关活跃事项不强制查完，不冒称不重大或已核
4. 每批核对原子事实、首次公开时间、财务口径及页面版本，保存并回读实际回执/字段/引用；未知保留draft，不能先攒大量未核条目到成稿后补造
5. 写正文和两类关系JSON的拟变更，修订先暂存，不提前覆盖正式基线；按claim ID检查各处依赖与更正传播
6. 初稿和每次修改后，执行 `validate_weekly_brief.py --preflight-only --report PATH --baseline PATH`。只读预检通过后再绑定最终证据、生成图或联网审查；不为压篇幅删除重大事实及限制
7. 运行完整inventory并按时点规范完成temporal evidence、覆盖闭环和四项实际语义复核，核对目标、具体版本和最终哈希；完整映射仍不是语义完成
8. 通过时点校验后运行图表更新计划、生成或沿用对应图谱并查看，再执行来源审查；暂存测试通过不代表正式发布
9. 对待发布内容运行完整主闸门及相关测试，保留任何失败。入口若尚不能验证暂存包，不得拿旧正式文件通过记录替代，也不得提前称新稿通过
10. 依授权和版本隔离规则归档/发布，核对真实commit与远端回执；审计、维护和历史修订不自动提交推送

任何一步失败，都不能在周报中写“已完成”。

外部文件受阻且用户没有材料时按coverage工作卡记录恢复条件，不重复向用户索取。校验失败须区分外部取证与内部未完成步骤；证据暂存版标draft，完整目标映射、格式通过或图谱已生成都不替代发布闸门。

2026-09-09起按用户授权区分未确认线索和已确认重大事件：前者只有满足覆盖规范的隔离契约，完整披露于第7节且不进入事实/判断/图谱，才可不阻断发布；后者的关键事实缺口仍阻断。最新口径不要求未入选项全部附录或补证；只对入选事实及可能误导本期结论的矛盾阻断相关断言，不要求历史待办清零。

### 共性故障与验收

2026-09-09按已记录问题归纳；对应skill九项执行规则。共性是将代理指标当作证据、把检查拖到最后以及更正未传遍依赖；也存在未执行已有规则的操作失误，不能全部归咎于skill或模型代际。以下是已知反例的归并，不声称覆盖未知故障或保证零遗漏。

| 对应规则 | 已观察的同类问题 | 必须验证的结果与工具边界 |
| --- | --- | --- |
| 1 结果级覆盖 | AI主题锚定漏监管；总新闻页替代业务入口；组合查询被另一公司占据；聚合IR漏申报；活跃事项缺本周检查 | 按实际官方筛选、独立重要性校准及入选事实验收，不强制全业务穷举；coverage脚本查结构/引用，人读实际范围 |
| 2 事件身份和重大性 | 不同案件/阶段混合；通用产品标题归错公司；重复头条；用未量化收入、未最终裁判或没有订单排除 | 核公司、产品/权利、案号/交易、阶段、本周增量；事件卡去重保留补充事实，重大性与证据充分性分开 |
| 3 断言边界 | Alphabet年份/分部/单位错；交易总额及组成混用；产品型号错；双方诉讼角色压缩反转；API保留/账号条件及安全修复撤回遗漏 | 回核原表、限定与否定段；一处多个事实分别取证；不以官方域名、AI摘要或关键词代替正文，机器不认证金额/法律语义 |
| 4 时点与版本 | 旧协议写本周；聚合器旧闻日期错；虚构午夜/日末/读取时刻；滚动页与推荐栏借母页日期；历史重建当实时输入 | 原日期和实际精度、具体段落版本、发生/公开/读取/生成分开；publication_bounds与vintage约束只是结构及边界校验 |
| 5 工具与持久化 | 字符串当对象、未知envelope、批次合计截断、猜行号/URL；回执仅ID、补零错、load副本未store、枚举写成说明；JSON/补丁返工 | 类型和合计载荷先检；落盘后解析回读精确ID和非空result；工作卡引用校验、适配器测试不等于来源已读 |
| 6 更正传播 | 下一事件注释挂上一目标；旧claim直接套新事件序号；只改正文未改头条/图谱；双向能力画成单向采购；弱基线被沿用升级 | 稳定claim到全部目标和E/P/PX的明确映射；重新核语义再哈希绑定；图表结构/箭头及实际渲染分别检查，旧错误留档 |
| 7 阶段验收 | 先耗时审来源后发现格式；大量工作claim到最后才验字段；130目标齐全却复核pending；图已生成冒称完成；外部受阻掩盖内部余项 | 当批检查、预检、覆盖、时点、图、来源、全闸门按依赖推进；draft不发布，完整测试真实失败不改绿 |
| 8 效率和计量 | 重复确认同一事实、失败页无条件重试、长日志重复载入；维护/补证混杂；局部载荷或缓存比例冒充整期降耗 | 每次请求有未解问题；同版本复用、无新条件不原样重试；真实阶段和全部失败总账，明确未结算与可比性 |
| 9 规则版本和权限 | 固定规则误作单期例外；十件/四条/字符限制残留；多任务重复入口；“规则已加”被当真实整期有效；模糊归罪旧模型 | 当前裁决置顶、细则唯一维护并检查所有调用入口；规则/测试/整期研究/降耗分级评价，单一任务及发布授权不变 |

核对来源：历史审计A01-A06见[历史时点审计](../logs/2026-09-07_historical_point_in_time_audit.md)；发现与执行问题见[监管诊断](../logs/2026-09-07_regulatory_omission_analysis.md)、[连续遗漏整改](../logs/2026-09-08_coverage_remediation.md)、[方案二回执](../logs/2026-09-08_source_plan2_validation.md)；后续具体错误见[工作证据errors](../logs/2026-09-08_finish64_evidence.json)和[续修检查点](../logs/2026-09-08_final_repair_checkpoint.md)。旧日志中的“当时通过”不覆盖后续发现。

按改动风险执行现有`test_point_in_time.py`、`test_research_coverage.py`、`test_graph_direction.py`、`test_tool_output.cjs`及适用完整测试。源码/字段检查能证明已知模式被拦截；实际检索归属、原子完整性、数字/法律语义、独立来源血缘和图谱事实仍须由当前代理读原文核验。不得虚构一个自动完成这些语义判断的工具。规则维护结束只报告本次规则和验证，不冒称未重跑周报已修完。

各家公司官方渠道必须保留为每期必查来源，检查范围和受阻处理按[官方渠道保留](research_coverage.md#官方渠道保留)执行；媒体已读不能记作官方已读。官方当周入口用于初筛；业务专页、IR/申报和状态原件按入选核验需要展开，不要求所有栏目逐项完成。官方页内自动AI摘要不代替正文与脚注；发生摘要/正文冲突须保留原文依据和排除理由。

每次先读本流程，随后展开适用章节；同轮已读未变部分不反复全文读取。索引不承担事实核验，所有变更/相关/弱证据记录必须完整读取，机器校验仍使用完整 JSON。例行执行只读 automation memory 的最新完整条目，未完成事项由交接记录接续；不重复载入归档任务全文。工具返回前按 `docs/tool_output_contract.md` 做类型检查和有效内容提取；按 `context_efficiency.md` 用真实阶段边界记录生产、额外补证、维护及未归类的完整token总账，失败返工不扣除。预检不代替以下核验；目标是减少不必要上下文，不是降低缓存命中率。

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
- “本周新进展”必须有该进展首次公开的本周证据，不是重写旧公告日期
- 截止为报告周一上海 00:00，不是生成完成时刻；时区或版本不确定时，不按已确认新事实纳入

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

**它不验证历史可得性或财报期间。** 401/403、同 URL 的缓存成功和关键词命中不能替代时点证据；来源不可读时补找原始公告或有日期的独立披露，否则保留未核验限制。

来源审查日志必须绑定当前文件：

- `report_sha256` 必须等于当前周报文件的 SHA-256
- `baseline_sha256` 必须等于当前供应关系基线的 SHA-256
- `product_graph_sha256` 必须等于当前年度产品关系图 JSON 的 SHA-256
- `audited_urls` 必须等于当前周报、供应关系基线和年度产品关系图中抽取出的 URL 清单
- `summary.claim_failed` 必须为 0

若任一项不一致，说明审查日志已过期，必须重新运行来源审查。

## 四、逐条事实核验表

来源可达不等于事实成立。每条重大事件在写入周报前，应按以下证据契约核验：

统一使用时点规范的 `claims` 契约，不另设只有“是/否”的日期表。每个原子断言关联 inventory 中的正文/供应边目标，记录首次公开时间、时区、版本位置和证据摘要。重要数字同时写财年/季度、单季/累计、实际/指引、币种/单位及原表行列。

原文明示公开日期但未知时区时，按`point_in_time_policy.md`记录完整`claim_first_public_interval`，不把数学上下界填成实际发布时间。仅完整区间在允许范围且正文版本已核时放行；跨边界仍补证。日期精度优化不代替来源、财务、覆盖和版本复核。

填写规则：

- 官方来源能直接支持的结论，可以写为“已宣布”“已披露”
- 媒体来源支持但官方未确认的结论，必须写“媒体报道”“待官方确认”
- 来源只支持背景或趋势，不能写成具体订单、具体客户或具体金额
- 覆盖周期外事件只能作为延续跟踪，不能写成本周新增事件
- 付费墙或访问受限来源要在摘要中写明可见信息来自标题、摘要、公开片段还是已有订阅访问

## 五、周报正文查验

schema v2 正文必须包含：

- 本周最重要的N件事（0-12，按实际数量，不凑数；零件用“本周重大事件”并明确无可确认重大事件）
- 12 家公司投资判断速览
- 仅展开有合格入选事项的公司，每家公司最多5条，不打包独立事项绕限
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
- 重复或拆分事项、旧闻重报、引用周一新消息来凑数；不足12件时按实际数量发布并说明

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

上述命令仅在获准重建时使用；审计不自动重写旧报告。缓存通过不构成历史快照，迁移版本不构成原始实时信号，补跑/更正必须保存真实版本时间。

已授权替换历史报告时，先归档旧报告、旧图和旧来源日志，登记真实修订时间；只替换受影响文件。更正当期冻结状态写入 `historical_snapshot_overrides.json`，不要覆盖现行供应基线。已登记的纠错版不能再次用旧迁移器覆盖。

完成图表与本次来源审查后，用 `python3 scripts/run_quality_gate.py --historical --report reports/YYYY-MM-DD_weekly_morning_brief.md` 做只读历史检查。遗留报告的定点纠错记录不等于全量时点证据，仍须保留 `legacy_unverified`。原始归档也须单独确认真实发布时点才能用于回测。

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
python3 scripts/validate_point_in_time.py --report reports/YYYY-MM-DD_weekly_morning_brief.md --baseline state/supply_graph_baseline.json --product-graph state/product_relationships_YYYY.json
python3 scripts/run_quality_gate.py
```

时点闸门只验证记录一致性，不能自动证明来源语义；日期/口径/产品关系仍须实际复核。`legacy_unverified` 只允许旧版本结构复查，不授权宣称无未来数据。审计与规则维护不自动提交推送。

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

适用闸门全部通过且当前任务已获发布授权后，只暂存本次已核实的具体文件；不要整目录加入其他任务的改动、重复副本或账号资料：

```bash
git add <本次已核实的具体文件>
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
## 固定篇幅规则

2026-09-09最新固定规则：每家公司最多5条重要独立事项，头条最多12件且只提炼已入选事项，不凑数。不要求所有重大候选写入正文；总行数/字符仍无硬上限，保留入选事实、八字段、口径和限制。预检和完整校验使用同一规则；不跳过时点、覆盖、来源、图谱或版本检查，不重写冻结实验。

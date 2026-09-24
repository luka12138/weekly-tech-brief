# 历史报告事后修订与版本隔离

下列当前展示路径是事后修订版，不代表修订内容在原周一已经可访问，也不能用于原周一实时回测。原 Git 提交未改写。

| 报告日 | 首次 Git 留痕（不是发布证明） | 原冻结快照 | 本次处理 |
| --- | --- | --- | --- |
| [2026-07-06](../reports/2026-07-06_weekly_morning_brief.md) | 2026-07-07T10:06:26+08:00 | `2c1fbaac39` | 正文、供应图与来源审计纠错 |
| [2026-07-27](../reports/2026-07-27_weekly_morning_brief.md) | 2026-07-27T10:01:04+08:00 | `ea3758d3ed` | 正文、供应图与来源审计纠错 |
| [2026-09-07](../reports/2026-09-07_weekly_morning_brief.md) | 2026-09-07T09:57:21+08:00 | `0d6033a12a` | 按每家公司最多 5 条的有限筛选口径重跑；绑定完整 PIT、研究覆盖、来源审计与冻结图谱状态 |

## 原件与证据

[替换前归档](../archives/2026-09-07_before_correction.tar.gz)保存原报告和相关历史产物；它还含其他日期的旧文件，本次未修改那些日期。原件与当前文件的哈希、修订时间和回测排除标记见[版本登记](../state/report_vintages.json)。逐项事实、财务换算、排除项和剩余限制见 [7/6 更正证据](../logs/2026-07-06_correction_evidence.json)及 [7/27 更正证据](../logs/2026-07-27_correction_evidence.json)。

9/7 的替换前文件与状态保存在[独立归档](../archives/2026-09-09_before_top5.tar.gz)。修订正文绑定 [PIT 证据](../logs/2026-09-07_temporal_evidence.json)、[研究覆盖](../logs/2026-09-07_research_coverage.json)、[来源审计](../logs/2026-09-07_source_audit.json)及 `state/historical/2026-09-07_{supply,product}.json`。这些冻结状态只用于该历史修订，不覆盖现行周报基线。

7/6 撤销 AWS/OpenAI 2025 年协议的当周新事件及 E03/E05 增量标记，去重后保留 6 件；同时更正 Apple 应用集成、Meta/NVIDIA 的上海日期和 Tesla 固定来源。7/27 依据 SEC 同期单季原表更正 Alphabet 数字，删除错误的 2026 年资本开支指引；同时修正 Apple 日期、AMD 产品路线及意向书/MOU 的承诺性质，排除未取得全文版本的 TSMC 报道，保留 9 件。

7/6 与 7/27 的更正证据不是完整 `temporal_evidence`。历史页面版本和部分首次公开时间仍未认证，两期均为 `legacy_unverified`。9/7 修订版的 PIT 记录只认证修订稿中事实相对 9/7 截止时点的证据绑定，不把 9/9 的修订稿倒推成 9/7 已发布。原始归档也须另核真实发布时点，不能自动作为回测输入。

## 版本校验

```bash
python3 scripts/validate_report_vintage.py --report reports/2026-07-06_weekly_morning_brief.md
python3 scripts/validate_report_vintage.py --report reports/2026-07-27_weekly_morning_brief.md
python3 scripts/validate_report_vintage.py --report reports/2026-09-07_weekly_morning_brief.md
python3 scripts/run_quality_gate.py --historical --report reports/2026-09-07_weekly_morning_brief.md
```

加 `--for-backtest` 时必须拒绝当前修订版。历史质量闸门检查结构、图谱、来源及版本隔离，但不认证原周一可得性。

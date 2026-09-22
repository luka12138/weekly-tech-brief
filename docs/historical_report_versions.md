# 2026-07-06 与 2026-07-27 历史报告版本隔离

这两期当前展示路径是 2026-09-07 的事后纠错版，不是原周一已可访问的报告，也不能用于原周一实时回测。原 Git 提交未改写。

| 报告日 | 首次 Git 留痕（不是发布证明） | 原冻结快照 | 本次处理 |
| --- | --- | --- | --- |
| [2026-07-06](../reports/2026-07-06_weekly_morning_brief.md) | 2026-07-07T10:06:26+08:00 | `2c1fbaac39` | 正文、供应图与来源审计纠错 |
| [2026-07-27](../reports/2026-07-27_weekly_morning_brief.md) | 2026-07-27T10:01:04+08:00 | `ea3758d3ed` | 正文、供应图与来源审计纠错 |

## 原件与证据

[替换前归档](../archives/2026-09-07_before_correction.tar.gz)保存原报告和相关历史产物；它还含其他日期的旧文件，本次未修改那些日期。原件与当前文件的哈希、修订时间和回测排除标记见[版本登记](../state/report_vintages.json)。逐项事实、财务换算、排除项和剩余限制见 [7/6 更正证据](../logs/2026-07-06_correction_evidence.json)及 [7/27 更正证据](../logs/2026-07-27_correction_evidence.json)。

7/6 撤销 AWS/OpenAI 2025 年协议的当周新事件及 E03/E05 增量标记，去重后保留 6 件；同时更正 Apple 应用集成、Meta/NVIDIA 的上海日期和 Tesla 固定来源。7/27 依据 SEC 同期单季原表更正 Alphabet 数字，删除错误的 2026 年资本开支指引；同时修正 Apple 日期、AMD 产品路线及意向书/MOU 的承诺性质，排除未取得全文版本的 TSMC 报道，保留 9 件。

更正证据不是完整 `temporal_evidence`。历史页面版本和部分首次公开时间仍未认证，两期均为 `legacy_unverified`。原始归档也须另核真实发布时点，不能自动作为回测输入。

## 版本校验

```bash
python3 scripts/validate_report_vintage.py --report reports/2026-07-06_weekly_morning_brief.md
python3 scripts/validate_report_vintage.py --report reports/2026-07-27_weekly_morning_brief.md
```

加 `--for-backtest` 时必须拒绝当前修订版。历史质量闸门检查结构、图谱、来源及版本隔离，但不认证原周一可得性。

# 10/26备份用途与复用

本期已在西部数据My Passport4TB保留独立副本，原本机资料继续保留。原始供应商行情和网页回执仅存本机与授权硬盘，GitHub发布阅读产物和核验元数据。

| 保存部分 | 必要性 | 复用方式 |
| --- | --- | --- |
| objects内容对象 | 保存实际API回包、网页正文、错误与新版本；相同字节去重 | 按manifest哈希读取，不能按当前同名文件替换旧对象 |
| runs及请求回执 | 保留真实开始/结束/封存时间、请求参数、失败与诊断 | 排查数据来源与迟到原因；诊断run不能自动替换已选run |
| issues、normalizations、report_inputs | 固定本期行情选择、转换版本、计算依赖和参数 | 读取10/26的指针与同源对象，重新计算同一期；新供应商版本另存 |
| 完整artifact包 | 将新闻证据、报告、规则/代码、图谱和检查一起留存 | 需要完整复盘时恢复383文件包；原输入小包保存较早展示标签，不覆盖它 |
| backup/restore回执 | 证明固定清单复制完整且能够实际恢复 | 先校验哈希再复算；复制成功不授予财务PIT资格 |

本期主报告提交5174888b760cfc861b6d946dd05fc9eb6ffbeb02。完整包路径：
`weekly_data/runs/2026-10-26/74efef4e-5053-473b-9187-b28db3610dee/artifacts/weekly_issue_final_v1.json`

恢复到一个尚不存在的新目录（将“新恢复目录”换成实际路径）：

```sh
python3 scripts/weekly_data_store.py restore-artifacts --store '/Volumes/My Passport/每周简报/weekly_data' --manifest '/Volumes/My Passport/每周简报/weekly_data/runs/2026-10-26/74efef4e-5053-473b-9187-b28db3610dee/artifacts/weekly_issue_final_v1.json' --destination '/新恢复目录'
```

在恢复目录运行`python3 scripts/investment_review.py --report reports/2026-10-26_weekly_morning_brief.md`，会校验并使用冻结代码与同源价格。新闻另用`validate_research_coverage.py`和`validate_point_in_time.py`按本期证据校验。渲染需要相应Python/Node运行库及字体，完整包不声称跨系统完全自包含。

下周在新报告周建立新run和新选择，继续跨期去重；不要覆盖10/26的选定对象或用当前API重取结果回填。10/26是实际迟到提取的价格观察，未认证09:00原生采集、含现金分红总回报或完整历史PIT。

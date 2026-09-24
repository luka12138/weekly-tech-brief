#!/usr/bin/env python3
"""Rebuild the selected, source-bounded September 21 brief."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-09-21"
COMPANIES = ["Apple", "Microsoft", "Alphabet / Google", "Amazon / AWS", "Meta", "NVIDIA", "Tesla", "OpenAI", "Anthropic", "Samsung Electronics", "SK Hynix", "TSMC"]

# A dated page is only used for a claim visible in the cited body/version.
EVENTS = [
 dict(id="APL-STORE", company="Apple", date="2026-09-18", title="iPhone 18 Pro系列进入门店销售", fact="Apple称iPhone 18 Pro和Pro Max于9月18日在其全球门店开售；活动照片和到店人流不能推算销量或收入。", impact="发布转入销售阶段，需求强度仍待经营数据。", metric="实际交付、产品组合、后续财报", verify="核对公司销量或财报口径，不用现场照片外推。", confidence="Apple具日期现场公告；没有销售量结论。", url="https://www.apple.com/uk/newsroom/2026/09/the-latest-iphone-apple-watch-and-airpods-lineups-arrive-in-stores-worldwide/", locator="9月18日正文首段，iPhone 18 Pro/Pro Max门店上市"),
 dict(id="MS-G7", company="Microsoft", date="2026-09-15", title="公布面向美国政府云的Microsoft 365 G7", fact="Microsoft宣布面向GCC的Microsoft 365 G7；G7和Agent 365计划10月1日起可购买，更多工作负载须分阶段完成GCC授权。", impact="政府AI套件采购入口将拓展，但本周尚未开始购买。", metric="GCC采购、授权进度、实际部署", verify="10月1日购买入口及后续授权工作负载。", confidence="Microsoft官方9月15日公告；区分公告与可购买。", url="https://www.microsoft.com/en-us/microsoft-cloud/blog/industry-government/government-operations-and-infrastructure/2026/09/15/introducing-microsoft-365-g7-intelligence-trust-for-the-mission-ahead/", locator="正文第33—35行，GCC与10月1日购买日期"),
 dict(id="MS-DIV", company="Microsoft", date="2026-09-15", title="季度股息上调至每股0.98美元", fact="董事会宣布每股0.98美元季度股息，较上一季度增加0.07美元、约8%；登记日为11月19日，支付日为12月10日。", impact="明确股东回报安排，不等同AI业务收入变化。", metric="每股股息、支付安排、自由现金流", verify="按公司披露核对登记和支付，不混同已支付。", confidence="Microsoft官方9月15日公告；金额单位为美元/股。", url="https://news.microsoft.com/source/2026/09/15/microsoft-announces-quarterly-dividend-increase-7/", locator="9月15日公告首段，股息、登记与支付日期"),
 dict(id="GOO-LIVE", company="Alphabet / Google", date="2026-09-15", title="公布Gemini 3.8 Live系列", fact="Google公布Gemini 3.8 Live与Live Extended Thinking，面向实时语音和更长推理；具体入口分产品和开发者渠道，不能把预览或订阅开放写成全面正式可用。", impact="实时交互模型的产品竞争加快，商业采用仍待验证。", metric="可用地区与层级、开发者使用、延迟", verify="分别核对API与应用的可用级别和后续采用。", confidence="Google 9月15日具日期公告；页面9月17日更新，保留版本敏感性。", url="https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-8-live-gemini-3-8-live-extended-thinking/", locator="9月15日公告标题及Availability段；9月17日页面更新"),
 dict(id="GOO-ADS", company="Alphabet / Google", date="2026-09-16", title="美国广告技术案救济细节公开", fact="美国司法部9月16日公布广告技术案救济安排，涉及互操作、数据共享、自我优待限制及监督；本周增量是救济细节，不是9月2日已作出的不拆分结论。", impact="广告技术经营约束进一步明确，实施和上诉仍需跟踪。", metric="合规措施、监督期限、广告平台规则", verify="核对法院命令实施、后续上诉与实际执行。", confidence="司法部官方9月16日公告；机构观点不扩大为终局无上诉裁判。", url="https://www.justice.gov/opa/pr/department-justice-again-wins-substantial-relief-against-google", locator="9月16日司法部公告救济要点，另以9月2日旧裁决作背景"),
 dict(id="AWS-GEN", company="Amazon / AWS", date="2026-09-16", title="Generac披露与Amazon的后备发电机供货协议", fact="Generac在SEC 8-K披露Amazon后备发电机供货协议，初始约24亿美元交付预计在2027—2028年；同时授予Amazon附条件认股权证，潜在股份和付款门槛不等于已交付或已实现收入。", impact="数据中心后备电力设备供应关系确定，但规模兑现仍在未来。", metric="交付、付款、产能、认股权证归属", verify="跟踪实际采购付款及2027—2028年交付。", confidence="Generac 9月16日SEC文件；未来交付与条件权益分列。", url="https://www.sec.gov/Archives/edgar/data/1474735/000143774926030550/gnrc20260915_8k.htm", locator="9月16日Form 8-K Item 1.01及附件摘要，供货、交付期与认股权证条件"),
 dict(id="META-ONE", company="Meta", date="2026-09-15", title="推出Meta One订阅服务", fact="Meta公布Meta One分层订阅，以更多AI功能和使用量为卖点，并称免费基本服务仍保留；开放节奏和权益按应用、地区与账号不同。", impact="为AI功能增加付费入口，付费转化尚未由公告证实。", metric="订阅采用、权益使用、地区扩展", verify="核对实际开放账户、价格与后续收入披露。", confidence="Meta具日期公告；不将既有总订阅试用数当作Meta One新增用户。", url="https://about.fb.com/news/2026/09/introducing-meta-one-subscription-service-more-features-ai/", locator="9月15日公告计划与免费服务、地区/账号限制段"),
 dict(id="NV-MLPERF", company="NVIDIA", date="2026-09-16", title="Vera Rubin公布MLPerf Inference预览结果", fact="NVIDIA发布Vera Rubin NVL72在MLPerf Inference v6.1的预览提交结果，所列性能倍数针对特定模型和比较基线；这是厂商测试表现，不是客户部署、收入或通用工作负载优势。", impact="展示下一代平台潜在推理效率，量产与实际成本待验证。", metric="独立基准、交付、实际推理成本", verify="核对正式产品交付和第三方同口径测试。", confidence="NVIDIA 9月16日博客的自报基准；明确预览。", url="https://blogs.nvidia.com/blog/vera-rubin-nvl72-mlperf-inference/", locator="9月16日正文preview submissions及Qwen3-VL/DeepSeek-R1比较段"),
 dict(id="TSLA-CERT", company="Tesla", date="2026-09-15", title="Cybercab认证调查答复要求进入公开报道", fact="Reuters报道美国NHTSA要求Tesla就Cybercab自我认证问题在9月30日前答复；调查与问询不等于认定车辆违规，命令发出日期不误写为9月15日。", impact="商业部署仍受认证审查和回应结果制约。", metric="答复、调查结论、实际获准部署", verify="查看NHTSA后续公开文件及Tesla答复。", confidence="Reuters 9月15日报道并引述NHTSA；不作违规裁决。", url="https://www.marketscreener.com/news/us-agency-orders-tesla-to-answer-questions-on-cybercab-certification-ce785bddde80f524", locator="Reuters 9月15日报道NHTSA公开答复要求；9月10日命令为先前动作", basis="dated_media"),
 dict(id="OA-MISALIGN", company="OpenAI", date="2026-09-16", title="发布模型失配报告框架", fact="OpenAI公布报告框架并讨论过去六个月训练和评估中的六项历史观察；六项不是本周发生的六起生产事故，也不能据此估计总体发生率。", impact="治理披露形式更具体，实际执行和外部可核验性仍待观察。", metric="披露频率、事件分类、外部核验", verify="跟踪后续按框架披露及独立复核。", confidence="OpenAI 9月16日原文；案例发生期与披露期分开。", url="https://openai.com/index/model-misalignment-reporting-framework/", locator="9月16日正文框架及six instances in training/evaluation段"),
 dict(id="OA-LAW", company="OpenAI", date="2026-09-17", title="推出法律行业Astra试点", fact="OpenAI公布Astra for Law，初期仅通过Trusted Access提供给选定律所；API计划稍后开放，产品测试或自测结果不代表所有法律场景已可用。", impact="垂直行业工作流试水，采用范围与可靠性需观察。", metric="准入律所、实际任务表现、API开放", verify="核对Trusted Access扩围与API正式开放。", confidence="OpenAI 9月17日公告；保留试点准入和未来API边界。", url="https://openai.com/index/astra-for-law/", locator="9月17日正文Trusted Access与API coming soon段"),
 dict(id="OA-ADS", company="OpenAI", date="2026-09-16", title="广告AI产品进入有限测试", fact="OpenAI公布广告AI方案，其中Sponsored Agents在美国选定广告主中测试；Shopify与HubSpot相关入口按各自开放条件推进，不等于全面商用或确认广告收入。", impact="广告客户工作流增加AI入口，商业模式兑现待验证。", metric="测试范围、广告主采用、可确认收入", verify="核对产品开放条件及后续收入披露。", confidence="OpenAI 9月16日公告；测试和可用入口分开。", url="https://openai.com/index/reimagining-advertising-with-ai/", locator="9月16日正文Sponsored Agents select US advertisers及Shopify/HubSpot段"),
 dict(id="AN-METRICS", company="Anthropic", date="2026-09-17", title="提出前沿实验室研发节奏指标", fact="Anthropic提出AI参与研发、自主代理监督和算力分配三类指标，并披露内部快照；其数据和评价方法由公司提出，跨实验室可比性与外部验证仍有限。", impact="提高治理透明度的可讨论口径，不能把自报数字当独立评估。", metric="方法公开、第三方核验、后续时间序列", verify="等待共同方法和外部复核。", confidence="Anthropic官方9月17日新闻索引及具体研究正文；不外推公司内部样本。", url="https://www.anthropic.com/institute/measuring-pace-of-ai-development", locator="9月17日News索引链接版本；正文三类measurement与方法限制"),
 dict(id="AN-ACC", company="Anthropic", date="2026-09-18", title="与Accenture合作开展嵌入式独立评估", fact="Anthropic称与Accenture合作开展嵌入式模型评估；双方各自预计五年投入至少10亿美元。安排非独家，访问和报告标准尚未确定，Anthropic将直接支付Accenture工作。", impact="安全评估投入承诺明确，但独立性和实际成果需制度化检验。", metric="实际支出、评估权限、公开报告", verify="核对合同实施、资金来源与第三方报告。", confidence="Anthropic 9月18日官方公告；数额是各自预期非已支付。", url="https://www.anthropic.com/news/accenture-embedded-evaluation", locator="9月18日正文第15—23行，双方各自预计投入与非独家/资助边界"),
 dict(id="SS-UI", company="Samsung Electronics", date="2026-09-16", title="One UI 9开始向更多Galaxy设备推送", fact="Samsung宣布9月16日起将One UI 9扩至Galaxy S26系列；此前已在Z Fold8 Ultra、Fold8和Flip8首发。功能按地区、型号和账号不同，不能宣称全部设备同步获得所有AI功能。", impact="既有设备的软件体验扩展，使用及留存效果待观察。", metric="实际推送覆盖、功能使用、设备留存", verify="按设备与地区核对推送及功能可用性。", confidence="Samsung 9月16日官方公告；保留机型与地区限制。", url="https://news.samsung.com/global/samsung-begins-official-rollout-of-one-ui-9-bringing-the-latest-galaxy-experiences-to-more-devices", locator="9月16日公告 rollout order及feature availability脚注"),
 dict(id="SK-INTEL", company="SK Hynix", date="2026-09-16", title="回应与Intel美国内存制造洽谈报道", fact="SK Hynix称正探索多种方案，但就媒体所述与Intel在美国制造内存芯片的洽谈，尚无具体计划、安排或决定；不能当作合资或建厂协议。", impact="本地制造选项仍在早期，资本投入不能据传闻量化。", metric="双方正式协议、投资额、工厂决策", verify="等待公司公告或监管备案，不以匿名报道确认为合同。", confidence="SK Hynix 9月16日官方回应，Reuters报道作报道对象。", url="https://news.skhynix.com/en/fact-10/", locator="9月16日Facts回应正文，exploring options与no concrete plan/arrangement/decision"),
]

HEADLINES = ["AWS-GEN", "GOO-ADS", "AN-ACC", "MS-G7", "NV-MLPERF", "OA-MISALIGN", "META-ONE", "APL-STORE", "TSLA-CERT", "SK-INTEL", "GOO-LIVE", "OA-LAW"]
ANALYSES = [
 ("公告、测试和商业交付必须分层。Microsoft G7的购买在10月、NVIDIA结果是预览基准、OpenAI法律与广告功能有选定用户边界；这些都不能合计为本周已实现收入。", ["MS-G7", "NV-MLPERF", "OA-LAW", "OA-ADS"]),
 ("基础设施和供应协议的金额需要按期间和条件理解。Generac初始供货预计2027—2028年履行，Amazon的认股权证归属附带付款条件；不能把未来交付或潜在权益记为本期现金收入。", ["AWS-GEN"]),
 ("治理消息的性质不同。Google广告技术案是救济细节，Tesla收到的是监管问询，OpenAI发布的是历史观察报告框架，Anthropic的嵌入式评估仍在设计标准。各项都需看执行证据。", ["GOO-ADS", "TSLA-CERT", "OA-MISALIGN", "AN-ACC"]),
]
CATALYSTS = [
 ("政府AI采购与有限试点。观察10月1日G7购买入口，以及Astra for Law和Sponsored Agents准入扩围；不预填付费转化。", ["MS-G7", "OA-LAW", "OA-ADS"]),
 ("数据中心后备设备。观察Generac与Amazon合同的实际付款、产能及未来交付进度；24亿美元仍为预计交付规模。", ["AWS-GEN"]),
 ("监管和治理。跟踪Google救济命令实施、Cybercab答复、OpenAI后续失配披露和Anthropic评估标准；问询不是违规裁决。", ["GOO-ADS", "TSLA-CERT", "OA-MISALIGN", "AN-ACC"]),
 ("产品采用与测试复核。核对iPhone 18 Pro实际销售披露、Gemini渠道可用性、Meta One付费采用及Vera Rubin第三方同口径表现。", ["APL-STORE", "GOO-LIVE", "META-ONE", "NV-MLPERF"]),
]

def main():
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    by_id = {e["id"]: e for e in EVENTS}
    lines = ["# 周一晨间科技巨头简报", "<!-- weekly-brief-schema: 2 -->", "<!-- company-selection: top5 -->", "<!-- point-in-time-policy: 1 -->",
             "- 覆盖期间：2026-09-14 至 2026-09-20（Asia/Shanghai）", f"- 生成时间：{now}（Asia/Shanghai）", "- 截止时点：2026-09-21 00:00（Asia/Shanghai，不含该时刻）", "- 本期文件：reports/2026-09-21_weekly_morning_brief.md", "- 阅读口径：12家公司各选0-5条重要独立事项；有限筛选而非零遗漏。消息、计划、自测与事实分别归因。", "- 时点限制：本报告在截止后制作，不宣称成稿在截止时已存在。仅将截止前具日期具体版本纳入事实。", "", "## 1. 本周最重要的 12 件事"]
    for i, cid in enumerate(HEADLINES, 1):
        e = by_id[cid]
        lines.append(f'{i}. **{e["company"]}：{e["title"]}。** 重要性：{e["impact"]} [来源]({e["url"]})')
    lines += ["", "## 2. 投资判断速览", "| 公司 | 本周变化 | 影响指标 | 预期差 | 判断 | 验证条件 |", "| --- | --- | --- | --- | --- | --- |"]
    for co in COMPANIES:
        es = [e for e in EVENTS if e["company"] == co]
        if es:
            change = "；".join(e["title"] for e in es)
            metric = "、".join(es[0]["metric"].split("、")[:2])
            lines.append(f'| {co} | {change} | {metric} | 暂不可验证 | 事实与条件分列，不给买卖评级 | {es[0]["verify"]} |')
        else:
            lines.append(f'| {co} | 本期未筛选到经核实的重要更新；有限范围见3节 | 沿用观察，不新增判断 | 暂不可验证 | 不等于没有变化或风险解除 | 新的具日期重要披露再更新 |')
    lines += ["", "## 3. 发生变化的公司"]
    section = 1
    for co in COMPANIES:
        es = [e for e in EVENTS if e["company"] == co]
        if not es:
            continue
        lines.append(f"### 3.{section} {co}")
        section += 1
        for e in es:
            lines += [f'<!-- candidate: {e["id"]} -->', f'- 日期：{e["date"]}（来源日期与时区不确定性见证据账）', f'- 事件：{e["fact"]}', f'- 投资影响：{e["impact"]}', f'- 影响指标：{e["metric"]}', '- 预期差：无同口径一致预期，暂不可验证。', f'- 验证条件：{e["verify"]}', f'- 可信度：{e["confidence"]}', f'- 来源：[原始来源]({e["url"]})', ""]
    lines += ["### 3.11 无重大变化公司", "- TSMC：本期未筛选到经核实的重要更新。有限检查包括投资者官方入口、MediaTek 2nm产品公告及独立报道；MediaTek原文未明确具名TSMC供货，不能据此新增确认供应关系。", "", "## 4. 跨公司与产业链判断"]
    for i, (sentence, _) in enumerate(ANALYSES, 1):
        lines.append(f"{i}. {sentence}")
    lines += ["", "## 5. 下周催化与验证条件"]
    for i, (sentence, _) in enumerate(CATALYSTS, 1):
        lines.append(f"{i}. 触发条件：{sentence} 可能影响：相应产品采用、经营约束或资本兑现；不预设结果。")
    lines += ["", "## 6. 研究附录：产业链与图谱", "### 6.1 图谱更新状态与可视化", "- 产品图：本期没有已核实的实质产品供应关系变化，沿用上周已核版本；沿用不表示重新认证所有旧边。", "![主营产品上下游关系图](../assets/2026-09-14_product_relationships.svg)", "[Obsidian Canvas 源文件](../assets/2026-09-14_product_relationships.canvas)", "- 供应图：本期更新E37，表示Generac与Amazon的后备发电机供货协议；未来交付不画成已完成。", "![供应关系图](../assets/2026-09-21_supply_relationships.svg)", "[Obsidian Canvas 源文件](../assets/2026-09-21_supply_relationships.canvas)", "", "### 6.2 本周供应关系变化表", "| Edge ID | 变化类型 | 供应方 -> 客户 | 产品/服务 | 投资影响 | 本周证据与限制 | 来源 |", "| --- | --- | --- | --- | --- | --- | --- |", "| E37 | 新增 | Generac -> Amazon / AWS | 数据中心后备发电机供货协议 | 潜在供应链资本承诺，非本期收入确认 | 初始约24亿美元交付预计2027—2028年；Amazon附条件认股权证不代表已全部归属。 | [SEC文件](https://www.sec.gov/Archives/edgar/data/1474735/000143774926030550/gnrc20260915_8k.htm) |", "", "### 6.3 与上周的区别", "- E37是本期新增合同阶段关系；未把未来交付或潜在权益当作现有付款。", "- 上周E20和E32—E36的本周变化标记归为历史基线，保留原证据日期与限定语。MediaTek产品公告未明确TSMC为供应方，不据此新增边。", "", "## 7. 本期自检", f'- 本期{len(EVENTS)}项独立入选事项，12家公司各0—5项，头条12项均来自入选事项。', "- 官方有限筛选和独立重要性校准后冻结名单；未入选候选及活跃事项留在coverage账中，不宣称全量清零。", "- 9月14日仅有日期而时区/公开时刻不足的候选不入本期新闻；Google Windows应用9月10日已公布，属于旧闻。", "- 24亿美元是预计未来交付、10亿美元是Anthropic与Accenture双方各自五年预期；股息按美元/股及未来支付日期记载。", "- 监管问询、法院救济、厂商基准与公司自报治理数据均保留性质和限制。机器闸门不能替代来源正文语义复核。", ""]
    (ROOT / "reports" / f"{DAY}_weekly_morning_brief.md").write_text("\n".join(lines), encoding="utf-8")
    (ROOT / "logs" / f"{DAY}_verified_events.json").write_text(json.dumps({"report_date": DAY, "events": EVENTS, "headlines": HEADLINES, "analyses": ANALYSES, "catalysts": CATALYSTS}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()

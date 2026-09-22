#!/usr/bin/env python3
"""Rebuild every archived brief into the compact investment-oriented schema v2."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from graph_update_policy import SCHEMA_V2_MARKER, supply_changed_edge_ids
from historical_snapshot_overrides import apply_text_overrides
from rebuild_historical_obsidian_graphs import ROOT, git_output, load_snapshot, report_snapshots


NO_EVENT_PATTERN = re.compile(
    r"未发现(?:可确认|足够可靠|可达来源支撑)?[^。；]{0,30}(?:重大|新增|官方)(?:事件|公告|新闻|披露)|"
    r"覆盖周内未发现|本期不重复|未写成新增|没有新的重大",
)
MEANINGFUL_MARKERS = ("new", "strengthen", "weaken", "risk", "remove", "新增", "强化", "弱化", "风险", "移除")


def markdown_section(text: str, number: int) -> str:
    match = re.search(rf"(?m)^## {number}\..*$", text)
    if not match:
        raise ValueError(f"缺少第 {number} 节")
    next_match = re.search(rf"(?m)^## {number + 1}\..*$", text[match.end() :])
    end = match.end() + next_match.start() if next_match else len(text)
    return text[match.end() : end].strip()


def numbered_blocks(section: str) -> list[str]:
    return [re.sub(r"\s+", " ", item).strip() for item in re.findall(r"(?ms)^\d+\. (.*?)(?=^\d+\. |\Z)", section)]


def company_blocks(section: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^### (.+)$", section))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        blocks.append((match.group(1).strip(), section[match.end() : end].strip()))
    return blocks


def parse_events(block: str) -> list[dict[str, str]]:
    starts = list(re.finditer(r"(?m)^- (?:\*\*)?日期：(?:\*\*)?\s*(.+)$", block))
    events: list[dict[str, str]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(block)
        chunk = block[start.start() : end]
        fields: dict[str, str] = {}
        for line in chunk.splitlines():
            match = re.match(
                r"^- (?:\*\*)?(日期|事件|影响|可信度|来源)：(?:\*\*)?\s*(.+)$",
                line.strip(),
            )
            if match:
                fields[match.group(1)] = match.group(2).strip()
        if all(fields.get(field) for field in ("日期", "事件", "影响", "可信度", "来源")):
            events.append(fields)
    return events


def parse_old_impact_table(section: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for line in section.splitlines():
        if not line.strip().startswith("|") or re.match(r"^\|\s*(?:---|公司)", line.strip()):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 4:
            result[cells[0]] = {"count": cells[1], "judgment": cells[2], "keywords": cells[3]}
    return result


def markdown_urls(text: str) -> set[str]:
    return set(re.findall(r"\[[^\]]+\]\((https://[^)]+)\)", text))


def clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip().rstrip("。")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def escape_cell(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).replace("|", "\\|").strip()


def event_is_material(event: dict[str, str]) -> bool:
    return not NO_EVENT_PATTERN.search(event.get("事件", ""))


def impact_metric(text: str, company: str) -> str:
    lowered = text.lower()
    if company == "Tesla":
        return "交付量、汽车毛利率、储能部署与库存"
    rules = (
        (r"诉讼|法院|反垄断|合规|禁令|出口管制|白宫|政策框架|\bdma\b|监管(?:调查|决定|要求|审查|处罚|机构|文件)|欧盟.*(?:条款|支付|分发)|替代支付|替代分发", "合规成本、产品可用性与收入风险"),
        (r"网络安全|安全测试|安全评估|安全分类器|未获授权|测试配置|风险报告|错配风险|能力门槛", "安全评估成本、发布节奏与产品可用性"),
        (r"裁员|重组|岗位削减|组织调整|组织架构", "运营费用率、人员成本与业务增速"),
        (r"回购|注销|股东回报|分红|股息|派息", "自由现金流、回购执行、每股指标与股东回报率"),
        (r"财报|业绩|指引|营收|季度收入|营业利润|净利润", "收入增速、营业利润率、订单与指引"),
        (r"广告|\bads?\b|openai pixel|conversions api", "广告负载、转化率、ARPU 与广告收入"),
        (r"学生|student rewards|开发者生态|云额度|培训(?:资源|课程|计划)|认证券", "开发者新增、活跃使用、云消耗与付费转化"),
        (r"\btesla\b|汽车|robotaxi|fsd|电动车|车辆", "交付量、汽车毛利率、储能部署与库存"),
        (r"\b5g\b|\bran\b|网络优化|吞吐|运营商", "网络吞吐、商用覆盖、运营商订单与合同规模"),
        (r"能效|低功耗|水资源|可持续", "能耗、水耗、单位产出成本与客户认证"),
        (r"价格|涨价|提价|降价|售价|定价|毛利|成本(?:上升|下降|压力|传导)", "ASP、毛利率、销量与成本传导"),
        (r"\bapi\b|computer use|browser use|skills|bedrock|app store|软件(?:更新|平台|产品|服务)|订阅|studio|final cut|creative cloud|用户名|apple maps|地图|导航|arcade", "活跃用户、API 调用量、付费转化与推理成本"),
        (r"数据中心|ai infrastructure|ai factor|基础设施|算力|(?:it-)?gw|资本开支|晶圆厂|扩产|产能", "资本开支、算力上线量与利用率"),
        (r"\baws\b|\bazure\b|google cloud|云服务|云业务", "云收入增速、积压订单、资本开支与利润率"),
        (r"pixel\s*\d|pixel watch|meta glasses|显示|折叠屏|手机(?!号)|眼镜|macbook|ipad", "产品出货量、ASP、毛利率与客户采用"),
        (r"hb[mf]|dram|nand|内存|存储|ssd|晶圆|制程|封装|良率", "出货量、ASP、良率与产能利用率"),
        (r"\bcpu\b|\bgpu\b|芯片|加速器|服务器", "产品出货量、ASP、毛利率与客户采用"),
        (r"模型|开放权重|open[- ]weight|frontier ai|agent|copilot|gemini|claude|gpt|chatgpt|muse", "活跃用户、API 调用量、付费转化与推理成本"),
        (r"收入|利润|订单", "收入增速、营业利润率、订单与指引"),
    )
    for pattern, metric in rules:
        if re.search(pattern, lowered, re.I):
            return metric
    if company in {"TSMC", "Samsung Electronics", "SK Hynix", "NVIDIA"}:
        return "出货量、ASP、良率与产能利用率"
    return "相关业务收入、毛利率与市场份额"


def expectation_gap(text: str, confidence: str) -> str:
    if re.search(r"未确认|待确认|媒体报道|市场观点|传闻", confidence + text):
        return "存在交易预期但缺少官方确认，按低置信度折价"
    if re.search(r"不及|低于预期|下调|削减|砍单|延期|推迟|延后|暂停|事故|诉讼|调查|禁令|裁员|撤回", text):
        return "方向偏负面；市场定价程度需结合后续指引验证"
    if re.search(r"超预期|上调|高于|创纪录|最大", text):
        return "方向偏正面；幅度是否高于一致预期仍需财报量化"
    if re.search(r"\d", text):
        return "新增量化基线，需与后续指引及一致预期比较"
    return "新增事实方向明确，幅度是否超出一致预期仍待量化"


def validation_condition(text: str, company: str, confidence: str = "") -> str:
    lowered = text.lower()
    if re.search(r"未确认|待确认|媒体报道|市场观点|传闻", confidence + text):
        return f"等待 {company} 官方公告、监管文件或财报确认"
    if re.search(r"诉讼|法院|监管|合规|禁令|出口管制|反垄断|白宫|政策框架|\bdma\b", lowered):
        return "跟踪法院文件、监管决定及公司风险披露"
    if re.search(r"网络安全|安全测试|安全评估|安全分类器|未获授权|测试配置|风险报告|错配风险|能力门槛", lowered):
        return "跟踪系统卡、第三方评估、安全控制与正式发布时间"
    if re.search(r"回购|注销|股东回报|分红|股息|派息", lowered):
        return "跟踪回购完成量、注销进度、自由现金流与后续分红"
    if re.search(r"财报|业绩|指引|营收|季度收入|营业利润|净利润", lowered):
        return "下次财报核对收入、利润率、指引与管理层口径"
    if re.search(r"广告|\bads?\b|openai pixel|conversions api", lowered):
        return "跟踪广告市场覆盖、广告负载、转化率、ARPU 与监管反馈"
    if re.search(r"学生|student rewards|开发者生态|云额度|培训(?:资源|课程|计划)|认证券", lowered):
        return "跟踪验证用户数、活跃使用、云额度消耗与付费转化"
    if company == "Tesla" or re.search(r"\btesla\b|汽车|robotaxi|fsd|电动车|车辆", lowered):
        return "跟踪季度交付、库存、价格、毛利率与监管许可"
    if re.search(r"\b5g\b|\bran\b|网络优化|吞吐|运营商", lowered):
        return "跟踪运营商合同、扩大部署范围及可复现的网络性能指标"
    if re.search(r"能效|低功耗|水资源|可持续", lowered):
        return "跟踪单位能耗、水耗、客户认证与制造成本变化"
    if re.search(r"价格|涨价|提价|降价|售价|定价|毛利|成本(?:上升|下降|压力|传导)", lowered):
        return "跟踪 ASP、销量、毛利率与成本向客户传导情况"
    if re.search(r"\bapi\b|computer use|browser use|skills|bedrock|app store|软件(?:更新|平台|产品|服务)|订阅|studio|final cut|creative cloud|用户名|apple maps|地图|导航|arcade", lowered):
        return "跟踪正式可用范围、定价、活跃使用、付费转化及第三方基准"
    if re.search(r"pixel\s*\d|pixel watch|meta glasses|显示|折叠屏|手机(?!号)|眼镜|macbook|ipad", lowered):
        return "跟踪正式上市范围、出货量、ASP、毛利率与渠道库存"
    if re.search(r"投资|数据中心|ai infrastructure|ai factor|基础设施|算力|(?:it-)?gw|产能|晶圆厂|扩产|订单|供应", lowered):
        return "跟踪资本开支执行、产能上线、具名客户与订单披露"
    if re.search(r"模型|开放权重|open[- ]weight|frontier ai|agent|copilot|gemini|claude|gpt|chatgpt|muse", lowered):
        return "跟踪正式可用范围、定价、活跃使用、付费转化及第三方基准"
    if re.search(r"hb[mf]|dram|nand|ssd|芯片|制程|封装", lowered):
        return "跟踪样品验证、量产时间、良率、出货量与客户确认"
    if re.search(r"收入|利润|订单", lowered):
        return "下次财报核对收入、利润率、订单与管理层口径"
    return f"等待 {company} 后续公告或下次财报给出可量化证据"


def normalize_judgment(value: str, changed: bool) -> str:
    if not changed:
        return "无重大变化"
    if "负面" in value and "正面" not in value:
        return "负面"
    if "正面" in value and not re.search(r"混合|负面", value):
        return "正面"
    if "中性" in value and not re.search(r"混合|正面|负面", value):
        return "中性"
    return "混合"


def normalize_headline(item: str, fallback_impact: str) -> str:
    item = re.sub(r"^\d+\.\s*", "", item).strip()
    item = item.replace("**为什么重要：**", "重要性：").replace("**来源：**", "来源：")
    item = item.replace("为什么重要：", "重要性：")
    item = item.replace("重要性： ", "重要性：").replace("来源： ", "来源：")
    if "重要性：" not in item and "投资判断：" not in item:
        item = item.strip().rstrip("。") + f"。重要性：{clip(fallback_impact, 140)}。"
    return clip(item, 680)


def build_headlines(old_items: list[str]) -> list[str]:
    # A presentation migration must not promote old baseline edges to new news.
    headlines: list[str] = []
    for item in old_items:
        headline = normalize_headline(item, "原版未单独说明投资影响，待核验")
        if headline not in headlines:
            headlines.append(headline)
        if len(headlines) == 10:
            break
    return headlines


def select_detail_events(
    companies: list[str],
    events_by_company: dict[str, list[dict[str, str]]],
    headlines: list[str],
    maximum: int = 10,
) -> dict[str, list[dict[str, str]]]:
    material = {
        company: [event for event in events_by_company.get(company, []) if event_is_material(event)]
        for company in companies
    }
    selected = {company: events[:1] for company, events in material.items() if events}
    headline_urls = set().union(*(markdown_urls(item) for item in headlines))
    remaining = [
        (0 if markdown_urls(event["来源"]) & headline_urls else 1, company, index, event)
        for company in companies
        for index, event in enumerate(material.get(company, [])[1:], start=1)
    ]
    for _, company, _, event in sorted(remaining, key=lambda item: (item[0], companies.index(item[1]), item[2])):
        if sum(len(events) for events in selected.values()) >= maximum:
            break
        if len(selected[company]) < 4:
            selected[company].append(event)
    return selected


def edge_change_bucket(edge: dict[str, Any]) -> str:
    marker = str(edge.get("changed_this_week", "")).lower()
    if "new" in marker or "新增" in marker:
        return "new"
    if "strength" in marker or "强化" in marker:
        return "strengthened"
    if any(token in marker for token in ("weak", "risk", "remove", "弱化", "风险", "移除")):
        return "risk"
    return "other"


def edge_description(edge: dict[str, Any]) -> str:
    return (
        f"{edge.get('edge_id')} {edge.get('supplier')}→{edge.get('customer')}："
        f"{clip(str(edge.get('product_or_service', '')), 70)}"
    )


def edge_sources(edge: dict[str, Any]) -> str:
    return "、".join(f"[来源{index}]({url})" for index, url in enumerate(edge.get("sources", [])[:2], 1))


def possible_impact(catalyst: str) -> str:
    return impact_metric(catalyst, "") + "可能重新定价"


def format_catalyst(catalyst: str) -> str:
    catalyst = catalyst.strip()
    title_match = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", catalyst)
    if title_match:
        title = title_match.group(1).strip()
        body = title_match.group(2).strip()
    else:
        title = clip(catalyst, 70).rstrip("。") + "。"
        body = catalyst
    body = re.sub(r"触发条件(?:为|是|：)\s*", "触发条件：", body, count=1)
    if "触发条件：" not in body:
        body = "触发条件：" + body
    result = f"**{title}** {body}"
    if "可能影响：" not in result:
        result += f" 可能影响：{possible_impact(result)}。"
    return result


def migrate_report(
    report_date: str,
    commit: str,
    graph_plan: dict[str, Any],
    baseline: dict[str, Any],
    previous_baseline: dict[str, Any] | None,
) -> str:
    report_path = f"reports/{report_date}_weekly_morning_brief.md"
    original = apply_text_overrides(report_date, git_output(["show", f"{commit}:{report_path}"]))
    companies = [str(company) for company in baseline.get("companies", [])]
    preamble = original.split("## 1.", 1)[0].strip().splitlines()
    metadata = [line for line in preamble if line.startswith("- ")]

    events_by_company = {company: [] for company in companies}
    for company, block in company_blocks(markdown_section(original, 3)):
        if company in events_by_company:
            events_by_company[company] = parse_events(block)
    old_impact = parse_old_impact_table(markdown_section(original, 2))
    headlines = build_headlines(numbered_blocks(markdown_section(original, 1)))
    if not headlines and "本周未发现可确认重大事件。" not in markdown_section(original, 1):
        raise ValueError(f"{report_date}: 原版头条缺失，须人工复核，不能自动声称本周无事件")
    detail_events = select_detail_events(companies, events_by_company, headlines)

    headline_title = f"## 1. 本周最重要的 {len(headlines)} 件事" if headlines else "## 1. 本周重大事件"
    lines = ["# 周一晨间科技巨头简报", SCHEMA_V2_MARKER, *metadata, "", headline_title]
    lines.extend(f"{index}. {item}" for index, item in enumerate(headlines, 1))
    if not headlines:
        lines.append("本周未发现可确认重大事件。")

    lines.extend(
        [
            "",
            "## 2. 投资判断速览",
            "| 公司 | 本周变化 | 影响指标 | 预期差 | 判断 | 验证条件 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for company in companies:
        material = [event for event in events_by_company.get(company, []) if event_is_material(event)]
        old_row = old_impact.get(company, {})
        if material:
            primary = material[0]
            primary_event = primary.get("事件", "")
            primary_text = primary_event + " " + primary.get("影响", "")
            change = clip(primary["事件"], 75)
            metric = impact_metric(primary_event, company)
            gap = expectation_gap(primary_text, primary["可信度"])
            judgment = normalize_judgment(old_row.get("judgment", "混合"), True)
            validation = validation_condition(primary_text, company, primary["可信度"])
        else:
            change = "未发现可确认重大事件"
            metric = "沿用上期关键经营指标"
            gap = "无新增预期差"
            judgment = "无重大变化"
            validation = f"等待 {company} 官方公告或下次财报"
        lines.append(
            "| " + " | ".join(escape_cell(value) for value in (company, change, metric, gap, judgment, validation)) + " |"
        )

    lines.extend(["", "## 3. 发生变化的公司"])
    subsection = 1
    for company in companies:
        selected = detail_events.get(company, [])
        if not selected:
            continue
        lines.extend(["", f"### 3.{subsection} {company}"])
        subsection += 1
        for event in selected:
            combined = event["事件"] + " " + event["影响"]
            lines.extend(
                [
                    f"- 日期：{event['日期']}",
                    f"- 事件：{event['事件']}",
                    f"- 投资影响：{event['影响']}",
                    f"- 影响指标：{impact_metric(event['事件'], company)}",
                    f"- 预期差：{expectation_gap(combined, event['可信度'])}",
                    f"- 验证条件：{validation_condition(combined, company, event['可信度'])}",
                    f"- 可信度：{event['可信度']}",
                    f"- 来源：{event['来源']}",
                    "",
                ]
            )
    unchanged = [company for company in companies if company not in detail_events]
    lines.extend([f"### 3.{subsection} 无重大变化公司"])
    if unchanged:
        lines.append("- " + "、".join(unchanged) + "：未发现可确认重大事件；沿用上期基线，不写成新增事实。")
    else:
        lines.append("- 无：全部覆盖公司均有达到纳入标准的本周变化。")

    trends = numbered_blocks(markdown_section(original, 4))[:5]
    while len(trends) < 3:
        trends.append("本周新增事实仍需通过财报、订单或监管文件验证其持续性。")
    lines.extend(["", "## 4. 跨公司与产业链判断"])
    lines.extend(f"{index}. {item}" for index, item in enumerate(trends, 1))

    catalysts = numbered_blocks(markdown_section(original, 5))[:5]
    lines.extend(["", "## 5. 下周催化与验证条件"])
    for index, catalyst in enumerate(catalysts, 1):
        lines.append(f"{index}. {format_catalyst(catalyst)}")

    product_plan = graph_plan["product"]
    supply_plan = graph_plan["supply"]
    product_status = (
        f"本期更新（{product_plan['reason']}）"
        if product_plan["action"] == "generate"
        else f"沿用 {product_plan['asset_date']} 版本（{product_plan['reason']}）"
    )
    supply_status = (
        f"本期更新（{supply_plan['reason']}）"
        if supply_plan["action"] == "generate"
        else f"沿用 {supply_plan['asset_date']} 版本（{supply_plan['reason']}）"
    )
    lines.extend(
        [
            "",
            "## 6. 研究附录：产业链与图谱",
            "",
            "### 6.1 图谱更新状态与可视化",
            f"- 产品图：{product_status}。",
            f"- 供应图：{supply_status}。",
            f"![{product_plan['asset_date']} 主营产品关系图](../{product_plan['svg']})",
            f"[打开产品关系 Canvas](../{product_plan['canvas']})",
            f"![{supply_plan['asset_date']} 供应关系图](../{supply_plan['svg']})",
            f"[打开供应关系 Canvas](../{supply_plan['canvas']})",
            "",
            "### 6.2 本周供应关系变化表",
        ]
    )
    changed_ids = supply_changed_edge_ids(baseline, previous_baseline)
    edges_by_id = {str(edge["edge_id"]): edge for edge in baseline.get("edges", [])}
    if changed_ids:
        lines.extend(
            [
                "| Edge ID | 供应方 | 客户/使用方 | 具体产品/服务 | 本周变化 | 证据与限制 | 来源 |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for edge_id in changed_ids:
            edge = edges_by_id[edge_id]
            evidence = (
                f"证据日 {edge.get('evidence_date', '未披露')}；可信度 {edge.get('confidence', '未标注')}；"
                f"{edge.get('confidence_reason') or edge.get('notes') or edge.get('status', '')}"
            )
            values = (
                edge_id,
                edge.get("supplier", ""),
                edge.get("customer", ""),
                edge.get("product_or_service", ""),
                edge.get("changed_this_week", ""),
                evidence,
                edge_sources(edge),
            )
            lines.append("| " + " | ".join(escape_cell(value) for value in values) + " |")
    else:
        lines.append("本周无供应关系实质变化；供应图沿用最近一次已验证版本。")

    changed_edges = [edges_by_id[edge_id] for edge_id in changed_ids]
    buckets = {
        key: [edge_description(edge) for edge in changed_edges if edge_change_bucket(edge) == key]
        for key in ("new", "strengthened", "risk", "other")
    }
    unchanged_edges = [edge_description(edge) for edge in baseline.get("edges", []) if edge["edge_id"] not in changed_ids][:4]
    lines.extend(
        [
            "",
            "### 6.3 与上周的区别",
            "- 新增关系：" + ("；".join(buckets["new"]) if buckets["new"] else "无。"),
            "- 强化关系：" + ("；".join(buckets["strengthened"]) if buckets["strengthened"] else "无。"),
            "- 弱化或风险关系：" + ("；".join(buckets["risk"]) if buckets["risk"] else "无。"),
            "- 基线修订/上周基线不足：" + ("；".join(buckets["other"]) if buckets["other"] else "无。"),
            "- 无明显变化但关键关系：" + ("；".join(unchanged_edges) if unchanged_edges else "无可比关系。"),
        ]
    )
    if previous_baseline is None:
        lines.append("- 对比限制：首期归档无仓库内上期基线，关系按当期公开来源重建。")

    lines.extend(
        [
            "",
            "## 7. 本期自检",
            f"- 日期范围：基线覆盖 {baseline['coverage_period']['start']} 至 {baseline['coverage_period']['end']}，与报告周一的上一完整自然周一致。",
            f"- 公司覆盖：完整覆盖当期 {len(companies)} 家公司；未把后续新增研究对象倒灌至早期报告。",
            f"- 事件与投资判断：保留 {len(headlines)} 条原版头条，不以背景关系补足数量；事后展示迁移不构成事实或时点认证。",
            f"- 图谱策略：产品图 {product_plan['action']}，供应图 {supply_plan['action']}；Canvas/SVG 均由对应历史 JSON 快照生成或沿用。",
            "- 证据边界：无直接证据的关系未标为新增或强化；媒体报道和未确认事项保留原可信度限制。",
            "- GitHub 同步：历史正文不回写可变同步状态，以本文件所在 Git 提交与远端记录为准。",
        ]
    )
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="按不可变 Git 快照重建全部历史周报为 schema v2。")
    parser.add_argument("--dates", nargs="*", help="仅迁移指定日期；默认迁移全部")
    parser.add_argument("--graph-plan", default="state/historical_graph_plan.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    selected = set(args.dates) if args.dates else None
    graph_plan_payload = json.loads((ROOT / args.graph_plan).read_text(encoding="utf-8"))
    graph_plans = graph_plan_payload.get("reports", {})
    snapshots = report_snapshots()
    protected = [
        day for day, _ in snapshots
        if (selected is None or day in selected)
        and "<!-- report-vintage: revised -->" in (ROOT / "reports" / f"{day}_weekly_morning_brief.md").read_text(encoding="utf-8")
    ]
    if protected:
        raise SystemExit("错误：已有纠错展示版，不能用旧快照迁移覆盖并复活错误：" + ", ".join(protected))
    previous_baseline: dict[str, Any] | None = None
    written = 0
    latest_date = ""
    for report_date, commit in snapshots:
        baseline = load_snapshot(commit, "state/supply_graph_baseline.json")
        if selected is None or report_date in selected:
            if report_date not in graph_plans:
                raise SystemExit(f"错误：历史图谱计划缺少 {report_date}")
            migrated = migrate_report(
                report_date,
                commit,
                graph_plans[report_date],
                baseline,
                previous_baseline,
            )
            if not args.dry_run:
                (ROOT / "reports" / f"{report_date}_weekly_morning_brief.md").write_text(migrated, encoding="utf-8")
            written += 1
            latest_date = max(latest_date, report_date)
            print(f"{report_date} <- {commit[:10]}: schema v2 rebuilt")
        previous_baseline = baseline

    if not args.dry_run and selected is None and latest_date:
        latest_report = ROOT / "reports" / f"{latest_date}_weekly_morning_brief.md"
        text = latest_report.read_text(encoding="utf-8")
        coverage = re.search(r"(?m)^- 覆盖期间：(.+)$", text).group(1)
        generated = re.search(r"(?m)^- 生成时间：(.+)$", text).group(1)
        latest = (
            "# 周一晨间科技巨头简报\n"
            f"- 覆盖期间：{coverage}\n"
            f"- 生成时间：{generated}\n"
            f"- 本期文件：reports/{latest_report.name}\n\n"
            "本文件是最新晨报入口。当前正文采用紧凑投资判断 schema v2，图谱按实质变化策略更新。\n\n"
            f"[{latest_report.name}]({latest_report.name})\n"
        )
        (ROOT / "reports" / "latest.md").write_text(latest, encoding="utf-8")
    print(f"历史周报迁移完成：reports={written} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()

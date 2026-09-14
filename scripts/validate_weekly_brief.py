#!/usr/bin/env python3
"""提交或推送前校验每周简报产物。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from graph_update_policy import is_schema_v2, supply_changed_edge_ids
from json_canvas_graphs import validate_canvas_file
from validate_point_in_time import check_report as check_point_in_time
from validate_report_vintage import check_vintage


REQUIRED_COMPANIES = [
    "Apple",
    "Microsoft",
    "Alphabet / Google",
    "Amazon / AWS",
    "Meta",
    "NVIDIA",
    "Tesla",
    "OpenAI",
    "Anthropic",
    "Samsung Electronics",
    "SK Hynix",
    "TSMC",
]
LEGACY_REQUIRED_COMPANIES = [
    company for company in REQUIRED_COMPANIES if company not in {"OpenAI", "Anthropic"}
]
ALLOWED_COMPANY_SCOPES = (LEGACY_REQUIRED_COMPANIES, REQUIRED_COMPANIES)

REQUIRED_EDGE_FIELDS = [
    "edge_id",
    "supplier",
    "customer",
    "product_or_service",
    "relationship_type",
    "evidence_date",
    "source_type",
    "last_seen",
    "changed_this_week",
    "status",
    "confidence",
    "confidence_reason",
    "markdown_section_ref",
    "sources",
]

REQUIRED_PRODUCT_RELATIONSHIP_FIELDS = [
    "edge_id",
    "source",
    "target",
    "product_or_service",
    "evidence_level",
    "official_sources",
]

REQUIRED_PRODUCT_NODE_FIELDS = [
    "node_id",
    "company",
    "product",
    "category",
    "official_sources",
]

REQUIRED_PRODUCT_EDGE_FIELDS = [
    "edge_id",
    "source_node",
    "target_node",
    "source_company",
    "target_company",
    "product_or_service",
    "relationship_type",
    "evidence_level",
    "official_sources",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"错误：{message}", file=sys.stderr)
    raise SystemExit(1)


def extract_section(text: str, start: str, end: str | None = None) -> str:
    if start not in text:
        fail(f"缺少章节标记：{start}")
    section = text.split(start, 1)[1]
    if end and end in section:
        section = section.split(end, 1)[0]
    return section


def extract_mermaid(text: str) -> str:
    match = re.search(r"```mermaid\n(.*?)\n```", text, flags=re.S)
    if not match:
        fail("缺少完整闭合的 mermaid 代码块")
    return match.group(1)


def edge_ids_from_text(text: str) -> set[str]:
    return set(re.findall(r"\bE\d{2}\b", text))


def extract_markdown_urls(markdown: str) -> set[str]:
    urls = set(re.findall(r"\[[^\]]+\]\((https?://[^)]+)\)", markdown))
    urls.update(re.findall(r"(?<!\()https?://[^\s)>\"]+", markdown))
    return {url.rstrip(".,;") for url in urls}


def collect_urls(report_path: Path, baseline_path: Path | None, product_graph_path: Path | None = None) -> list[str]:
    urls = extract_markdown_urls(report_path.read_text(encoding="utf-8"))
    if baseline_path and baseline_path.exists():
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        for source in data.get("sources", []):
            if isinstance(source, str) and source.startswith(("http://", "https://")):
                urls.add(source)
        for edge in data.get("edges", []):
            for source in edge.get("sources", []):
                if isinstance(source, str) and source.startswith(("http://", "https://")):
                    urls.add(source)
    if product_graph_path and product_graph_path.exists():
        data = json.loads(product_graph_path.read_text(encoding="utf-8"))
        for section in ("companies", "relationships", "product_nodes", "product_edges"):
            for item in data.get(section, []):
                for source in item.get("official_sources", []):
                    if isinstance(source, str) and source.startswith(("http://", "https://")):
                        urls.add(source)
    return sorted(urls)


def validate_latest(latest_path: Path) -> None:
    latest = latest_path.read_text(encoding="utf-8")
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", latest)
    if not links:
        fail("reports/latest.md 没有 Markdown 链接")
    for link in links:
        if link.startswith(("http://", "https://", "/")):
            continue
        target = latest_path.parent / link
        if not target.exists():
            fail(f"reports/latest.md 链接目标不存在：{link}")


def validate_source_audit(
    audit_path: Path | None,
    report_path: Path,
    baseline_path: Path,
    product_graph_path: Path | None = None,
) -> None:
    if audit_path is None:
        return
    if not audit_path.exists():
        fail(f"来源审查文件不存在：{audit_path}")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("report_sha256") != sha256_file(report_path):
        fail("来源审查日志不是由当前周报生成")
    if audit.get("baseline_sha256") != sha256_file(baseline_path):
        fail("来源审查日志不是由当前供应关系基线生成")
    if product_graph_path is not None:
        if audit.get("product_graph_sha256") != sha256_file(product_graph_path):
            fail("来源审查日志不是由当前年度产品关系图生成")
    current_urls = collect_urls(report_path, baseline_path, product_graph_path)
    if audit.get("audited_urls") != current_urls:
        fail("来源审查 URL 清单与当前周报/基线/年度产品关系图不一致")
    summary = audit.get("summary", {})
    if summary.get("total", 0) <= 0:
        fail("来源审查没有审查任何 URL")
    if summary.get("unclassified", 0) != 0:
        fail("来源审查包含未分类来源")
    if summary.get("errors", 0) != 0:
        fail("来源审查包含可达性错误")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_claims = sum(1 for edge in baseline.get("edges", []) if edge.get("claim_keywords"))
    if summary.get("claim_total", 0) != expected_claims:
        fail(
            "来源审查 claim 数量与基线不一致："
            f"expected={expected_claims} actual={summary.get('claim_total', 0)}"
        )
    if summary.get("claim_failed", 0) != 0:
        fail("来源审查包含未通过关键词匹配的核心事实 claim")
    for source in audit.get("sources", []):
        if not source.get("url", "").startswith("https://"):
            fail(f"来源审查包含非 HTTPS URL：{source}")
        if not source.get("reachable"):
            fail(f"来源审查包含不可达 URL：{source}")


def validate_product_graph(
    report: str,
    product_graph_path: Path | None,
    product_image_path: Path | None,
    product_canvas_path: Path | None,
    required_companies: list[str],
) -> None:
    if product_graph_path is None and product_image_path is None and product_canvas_path is None:
        return
    if product_graph_path is None or product_image_path is None or product_canvas_path is None:
        fail("产品关系 JSON、Canvas 和 SVG 图片必须同时提供")
    if not product_graph_path.exists():
        fail(f"产品关系 JSON 不存在：{product_graph_path}")
    if not product_image_path.exists():
        fail(f"产品关系图片不存在：{product_image_path}")
    if not product_canvas_path.exists():
        fail(f"产品关系 Canvas 不存在：{product_canvas_path}")
    if product_canvas_path.suffix.lower() != ".canvas":
        fail(f"产品关系 Canvas 扩展名无效：{product_canvas_path}")
    try:
        validate_canvas_file(product_canvas_path)
    except (ValueError, json.JSONDecodeError) as exc:
        fail(f"产品关系 Canvas 校验失败：{exc}")
    if product_image_path.suffix.lower() not in {".svg", ".png", ".jpg", ".jpeg", ".webp"}:
        fail(f"不支持的产品关系图片类型：{product_image_path}")
    expected_image_ref = str(product_image_path).replace("\\", "/")
    alternate_image_ref = "../" + expected_image_ref
    if expected_image_ref not in report and alternate_image_ref not in report:
        fail(f"周报没有引用产品关系图片：{expected_image_ref}")
    if is_schema_v2(report):
        expected_canvas_ref = str(product_canvas_path).replace("\\", "/")
        alternate_canvas_ref = "../" + expected_canvas_ref
        if expected_canvas_ref not in report and alternate_canvas_ref not in report:
            fail(f"schema v2 周报没有引用产品关系 Canvas：{expected_canvas_ref}")

    product_graph = json.loads(product_graph_path.read_text(encoding="utf-8"))
    companies = product_graph.get("companies")
    if not isinstance(companies, list):
        fail("产品关系图 companies 必须是列表")
    names = [item.get("name") for item in companies]
    if names != required_companies:
        fail("产品关系图公司列表缺失，或未按标准顺序排列")
    for company in companies:
        if not company.get("main_products"):
            fail(f"产品关系图公司缺少 main_products：{company}")
        if not company.get("official_sources"):
            fail(f"产品关系图公司缺少 official_sources：{company}")

    relationships = product_graph.get("relationships")
    if not isinstance(relationships, list) or not relationships:
        fail("产品关系图 relationships 必须是非空列表")
    seen: set[str] = set()
    for relation in relationships:
        for field in REQUIRED_PRODUCT_RELATIONSHIP_FIELDS:
            if field not in relation:
                fail(f"产品关系缺少字段 {field}：{relation}")
        edge_id = relation["edge_id"]
        if not re.fullmatch(r"P\d{2}", edge_id):
            fail(f"产品关系 edge_id 无效：{edge_id}")
        if edge_id in seen:
            fail(f"产品关系 edge_id 重复：{edge_id}")
        seen.add(edge_id)
        if relation["source"] not in names:
            fail(f"产品关系 source 不是覆盖公司：{relation}")
        if relation["target"] not in names and not str(relation["target"]).startswith("外部:"):
            fail(f"产品关系 target 不是覆盖公司或外部节点：{relation}")
        if not relation.get("official_sources"):
            fail(f"产品关系缺少 official_sources：{relation}")

    product_nodes = product_graph.get("product_nodes")
    product_edges = product_graph.get("product_edges")
    legacy_company_graph = not product_nodes and not product_edges
    if legacy_company_graph:
        canvas = json.loads(product_canvas_path.read_text(encoding="utf-8"))
        canvas_labels = {str(edge.get("label")) for edge in canvas.get("edges", []) if edge.get("label")}
        expected_labels = {
            str(relation["edge_id"])
            for relation in relationships
            if relation.get("source") != relation.get("target")
        }
        missing_labels = expected_labels - canvas_labels
        if missing_labels:
            fail(f"旧版产品关系 Canvas 缺少公司级 Edge ID：{sorted(missing_labels)}")
        return
    if not isinstance(product_nodes, list) or not product_nodes:
        fail("产品关系图 product_nodes 必须是非空列表，或与 product_edges 同时省略")
    if not isinstance(product_edges, list) or not product_edges:
        fail("产品关系图 product_edges 必须是非空列表，或与 product_nodes 同时省略")

    nodes_by_id: dict[str, dict[str, object]] = {}
    products_by_company = {company["name"]: set(company["main_products"]) for company in companies}
    covered_products: set[tuple[str, str]] = set()
    for node in product_nodes:
        for field in REQUIRED_PRODUCT_NODE_FIELDS:
            if field not in node:
                fail(f"产品节点缺少字段 {field}：{node}")
        node_id = str(node["node_id"])
        if node_id in nodes_by_id:
            fail(f"产品节点 node_id 重复：{node_id}")
        company = str(node["company"])
        product = str(node["product"])
        if company not in products_by_company:
            fail(f"产品节点 company 不是覆盖公司：{node}")
        if product not in products_by_company[company]:
            fail(f"产品节点 product 不在该公司的 main_products 中：{node}")
        if not node.get("official_sources"):
            fail(f"产品节点缺少 official_sources：{node}")
        nodes_by_id[node_id] = node
        covered_products.add((company, product))

    expected_products = {
        (company["name"], product)
        for company in companies
        for product in company["main_products"]
    }
    if covered_products != expected_products:
        fail(f"产品节点未完整覆盖 main_products：missing={sorted(expected_products - covered_products)}")

    attached_nodes: set[str] = set()
    product_edge_ids: set[str] = set()
    for edge in product_edges:
        for field in REQUIRED_PRODUCT_EDGE_FIELDS:
            if field not in edge:
                fail(f"产品级关系缺少字段 {field}：{edge}")
        edge_id = str(edge["edge_id"])
        if not re.fullmatch(r"PX\d{2,3}", edge_id):
            fail(f"产品级关系 edge_id 无效：{edge_id}")
        if edge_id in product_edge_ids:
            fail(f"产品级关系 edge_id 重复：{edge_id}")
        product_edge_ids.add(edge_id)
        if edge["source_node"] not in nodes_by_id or edge["target_node"] not in nodes_by_id:
            fail(f"产品级关系引用了不存在的产品节点：{edge}")
        if not edge.get("official_sources"):
            fail(f"产品级关系缺少 official_sources：{edge}")
        attached_nodes.add(str(edge["source_node"]))
        attached_nodes.add(str(edge["target_node"]))

    unattached = set(nodes_by_id) - attached_nodes
    if unattached:
        fail(f"产品节点未进入任何产品级关系：{sorted(unattached)[:8]}")

    canvas = json.loads(product_canvas_path.read_text(encoding="utf-8"))
    canvas_labels = {str(edge.get("label")) for edge in canvas.get("edges", []) if edge.get("label")}
    expected_labels = {
        str(edge["edge_id"])
        for edge in product_edges
        if edge.get("source_company") != edge.get("target_company")
    }
    missing_labels = expected_labels - canvas_labels
    if missing_labels:
        fail(f"产品关系 Canvas 缺少跨公司 Edge ID：{sorted(missing_labels)}")


def validate_supply_artifacts(
    report: str,
    supply_image_path: Path | None,
    supply_canvas_path: Path | None,
    expected_edge_ids: set[str],
) -> None:
    if supply_image_path is None and supply_canvas_path is None:
        return
    if supply_image_path is None or supply_canvas_path is None:
        fail("供应关系 Canvas 和 SVG 图片必须同时提供")
    if not supply_image_path.exists():
        fail(f"供应关系图片不存在：{supply_image_path}")
    if not supply_canvas_path.exists():
        fail(f"供应关系 Canvas 不存在：{supply_canvas_path}")
    if supply_canvas_path.suffix.lower() != ".canvas":
        fail(f"供应关系 Canvas 扩展名无效：{supply_canvas_path}")
    try:
        validate_canvas_file(supply_canvas_path)
    except (ValueError, json.JSONDecodeError) as exc:
        fail(f"供应关系 Canvas 校验失败：{exc}")
    if supply_image_path.suffix.lower() not in {".svg", ".png", ".jpg", ".jpeg", ".webp"}:
        fail(f"不支持的供应关系图片类型：{supply_image_path}")
    expected_image_ref = str(supply_image_path).replace("\\", "/")
    alternate_image_ref = "../" + expected_image_ref
    if expected_image_ref not in report and alternate_image_ref not in report:
        fail(f"周报没有引用供应关系图片：{expected_image_ref}")
    if is_schema_v2(report):
        expected_canvas_ref = str(supply_canvas_path).replace("\\", "/")
        alternate_canvas_ref = "../" + expected_canvas_ref
        if expected_canvas_ref not in report and alternate_canvas_ref not in report:
            fail(f"schema v2 周报没有引用供应关系 Canvas：{expected_canvas_ref}")
    canvas = json.loads(supply_canvas_path.read_text(encoding="utf-8"))
    canvas_labels = {str(edge.get("label")) for edge in canvas.get("edges", []) if edge.get("label")}
    if canvas_labels != expected_edge_ids:
        fail(f"供应关系 Canvas Edge ID 不一致：canvas={sorted(canvas_labels)} json={sorted(expected_edge_ids)}")


DEFAULT_FORMAT_LIMITS = {"headlines": 12, "core_lines": None, "total_lines": None, "core_chars": None}


def validate_headlines(report: str, schema_v2: bool = False, limits: dict | None = None) -> None:
    maximum = (limits or DEFAULT_FORMAT_LIMITS)["headlines"]
    heading = re.search(r"^## 1\. ([^\n]+)", report, flags=re.M)
    if not heading:
        fail("缺少第 1 节重大事件标题")
    section = extract_section(report, heading.group(0), "## 2.")
    numbers = [int(value) for value in re.findall(r"^(\d+)\. ", section, flags=re.M)]
    if len(numbers) > maximum or numbers != list(range(1, len(numbers) + 1)):
        fail(f"第 1 节最多 {maximum} 件事，按实际数量从 1 连续编号，不得凑数：actual={numbers}")
    if not schema_v2:
        return
    if not numbers:
        if heading.group(1) != "本周重大事件" or "本周未发现可确认重大事件。" not in section:
            fail("零事件必须使用“本周重大事件”标题并明确写“本周未发现可确认重大事件。”")
        return
    if heading.group(1) != f"本周最重要的 {len(numbers)} 件事":
        fail(f"第 1 节标题数量必须等于实际事件数：{len(numbers)}")
    items = re.findall(r"(?ms)^\d+\. (.*?)(?=^\d+\. |\Z)", section)
    seen: set[str] = set()
    for index, item in enumerate(items, start=1):
        if "https://" not in item:
            fail(f"第 1 节第 {index} 件事缺少 HTTPS 来源")
        if "重要性：" not in item and "投资判断：" not in item:
            fail(f"第 1 节第 {index} 件事缺少“重要性”或“投资判断”")
        prose = re.sub(r"https://[^\s)]+", "", item)
        normalized = re.sub(r"\s+", "", prose)
        if normalized in seen:
            fail(f"第 1 节第 {index} 件事与前项重复，不得凑数")
        seen.add(normalized)
        if len(prose) > 700:
            fail(f"第 1 节第 {index} 件事过长，应压缩为事件、重要性和来源")


def _numbered_blocks(section: str) -> list[str]:
    return re.findall(r"(?ms)^\d+\. (.*?)(?=^\d+\. |\Z)", section)


def _heading_blocks(section: str, prefix: str) -> list[tuple[str, str]]:
    pattern = re.compile(rf"(?m)^### {re.escape(prefix)}\d+ (.+)$")
    matches = list(pattern.finditer(section))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        blocks.append((match.group(1).strip(), section[match.end() : end]))
    return blocks


def validate_v2_investment_table(report: str, required_companies: list[str]) -> None:
    section = extract_section(report, "## 2. 投资判断速览", "## 3.")
    header = next((line for line in section.splitlines() if line.strip().startswith("|")), "")
    for column in ("公司", "本周变化", "影响指标", "预期差", "判断", "验证条件"):
        if column not in header:
            fail(f"第 2 节投资判断表缺少列：{column}")
    for company in required_companies:
        if not re.search(rf"(?m)^\|\s*{re.escape(company)}\s*\|", section):
            fail(f"第 2 节投资判断表缺少公司：{company}")


def validate_v2_company_details(report: str, required_companies: list[str]) -> None:
    section = extract_section(report, "## 3. 发生变化的公司", "## 4.")
    blocks = _heading_blocks(section, "3.")
    if not blocks:
        fail("第 3 节缺少公司小节和“无重大变化公司”汇总")
    unchanged_blocks = [block for title, block in blocks if title == "无重大变化公司"]
    if len(unchanged_blocks) != 1:
        fail("第 3 节必须且只能有一个“无重大变化公司”汇总小节")

    changed_companies: set[str] = set()
    required_fields = ("日期", "事件", "投资影响", "影响指标", "预期差", "验证条件", "可信度", "来源")
    for title, block in blocks:
        if title == "无重大变化公司":
            continue
        if title not in required_companies:
            fail(f"第 3 节公司标题不在覆盖范围内：{title}")
        if title in changed_companies:
            fail(f"第 3 节公司标题重复：{title}")
        changed_companies.add(title)
        event_count = len(re.findall(r"(?m)^- 事件：\s*\S", block))
        if event_count < 1:
            fail(f"{title} 应至少包含 1 条重大事件，actual={event_count}")
        if "<!-- company-selection: top5 -->" in report and event_count > 5:
            fail(f"{title} 最多5条独立重要事项，actual={event_count}")
        for field in required_fields:
            count = len(re.findall(rf"(?m)^- {field}：\s*\S", block))
            if count != event_count:
                fail(f"{title} 的“{field}”数量必须与事件数量一致：events={event_count} actual={count}")
        source_lines = re.findall(r"(?m)^- 来源：\s*(.+)$", block)
        if any("https://" not in line for line in source_lines):
            fail(f"{title} 的每条事件来源必须包含 HTTPS 链接")

    unchanged_block = unchanged_blocks[0]
    unchanged_companies = {company for company in required_companies if company in unchanged_block}
    overlap = changed_companies & unchanged_companies
    if overlap:
        fail(f"公司不能同时列为发生变化和无重大变化：{sorted(overlap)}")
    covered = changed_companies | unchanged_companies
    if covered != set(required_companies):
        fail(f"第 3 节公司覆盖不完整：missing={sorted(set(required_companies) - covered)}")


def validate_v2_trends_and_catalysts(report: str) -> None:
    trends = extract_section(report, "## 4. 跨公司与产业链判断", "## 5.")
    trend_items = _numbered_blocks(trends)
    if not (3 <= len(trend_items) <= 5):
        fail(f"第 4 节必须包含 3-5 条跨公司判断：actual={len(trend_items)}")
    catalysts = extract_section(report, "## 5. 下周催化与验证条件", "## 6.")
    catalyst_items = _numbered_blocks(catalysts)
    if not (1 <= len(catalyst_items) <= 5):
        fail(f"第 5 节必须包含 1-5 条催化事项：actual={len(catalyst_items)}")
    for index, item in enumerate(catalyst_items, start=1):
        if "触发条件：" not in item or "可能影响：" not in item:
            fail(f"第 5 节第 {index} 项必须同时包含“触发条件”和“可能影响”")


def validate_v2_appendix(
    report: str,
    baseline: dict[str, object],
    expected_changed_edge_ids: set[str] | None = None,
) -> None:
    if "```mermaid" in report:
        fail("schema v2 不再保留 Mermaid；JSON 是关系事实源，Canvas/SVG 是唯一可视化层")
    status = extract_section(report, "### 6.1 图谱更新状态与可视化", "### 6.2")
    for graph_name in ("产品图：", "供应图："):
        match = re.search(rf"(?m)^- {graph_name}(.+)$", status)
        if not match:
            fail(f"第 6.1 节缺少更新状态：{graph_name}")
        if "本期更新" not in match.group(1) and "沿用" not in match.group(1):
            fail(f"第 6.1 节必须逐图说明是本期更新还是沿用历史版本：{graph_name}")

    table = extract_section(report, "### 6.2 本周供应关系变化表", "### 6.3")
    table_ids = set(re.findall(r"\|\s*(E\d{2})\s*\|", table))
    changed_ids = (
        expected_changed_edge_ids
        if expected_changed_edge_ids is not None
        else set(supply_changed_edge_ids(baseline))
    )
    if table_ids != changed_ids:
        fail(f"第 6.2 节只能列本周实质变化关系：table={sorted(table_ids)} expected={sorted(changed_ids)}")
    if not changed_ids and "本周无供应关系实质变化" not in table:
        fail("本周无变化时，第 6.2 节必须明确写“本周无供应关系实质变化”")


def validate_v2_compactness(report: str, limits: dict | None = None) -> None:
    limits = limits or DEFAULT_FORMAT_LIMITS
    nonempty_lines = [line for line in report.splitlines() if line.strip()]
    if limits["total_lines"] is not None and len(nonempty_lines) > limits["total_lines"]:
        fail(f"schema v2 周报非空行数不得超过 {limits['total_lines']}：actual={len(nonempty_lines)}")
    core = report.split("## 6. 研究附录：产业链与图谱", 1)[0]
    core_lines = [line for line in core.splitlines() if line.strip()]
    if limits["core_lines"] is not None and len(core_lines) > limits["core_lines"]:
        fail(f"第 1-5 节非空行数不得超过 {limits['core_lines']}：actual={len(core_lines)}")
    if limits["core_chars"] is not None and len(core) > limits["core_chars"]:
        fail(f"第 1-5 节正文过长，应压缩事件描述：characters={len(core)}")


def validate_v2_structure(
    report: str,
    baseline: dict[str, object],
    required_companies: list[str],
    expected_changed_edge_ids: set[str] | None = None,
    limits: dict | None = None,
) -> None:
    for heading in (
        "## 2. 投资判断速览",
        "## 3. 发生变化的公司",
        "## 4. 跨公司与产业链判断",
        "## 5. 下周催化与验证条件",
        "## 6. 研究附录：产业链与图谱",
        "### 6.1 图谱更新状态与可视化",
        "### 6.2 本周供应关系变化表",
        "### 6.3 与上周的区别",
    ):
        if heading not in report:
            fail(f"schema v2 缺少章节：{heading}")
    validate_v2_investment_table(report, required_companies)
    validate_v2_company_details(report, required_companies)
    validate_v2_trends_and_catalysts(report)
    validate_v2_appendix(report, baseline, expected_changed_edge_ids)
    validate_v2_compactness(report, limits)


def preflight_report(report_path: Path, baseline_path: Path) -> None:
    """Check local prose before evidence binding, graph generation or network IO."""
    report = report_path.read_text(encoding="utf-8")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    companies = baseline.get("companies")
    if companies not in ALLOWED_COMPANY_SCOPES:
        fail("基线公司列表缺失，或未按要求的标准顺序排列")
    schema_v2 = is_schema_v2(report)
    limits = DEFAULT_FORMAT_LIMITS
    validate_headlines(report, schema_v2, limits)
    if schema_v2:
        validate_v2_structure(report, baseline, list(companies), limits=limits)
    else:
        print("旧结构仅预检头条；完整历史校验仍须执行")


def validate_report(
    report_path: Path,
    baseline_path: Path,
    latest_path: Path,
    source_audit_path: Path | None = None,
    product_graph_path: Path | None = None,
    product_image_path: Path | None = None,
    product_canvas_path: Path | None = None,
    supply_image_path: Path | None = None,
    supply_canvas_path: Path | None = None,
    expected_changed_edge_ids: set[str] | None = None,
) -> None:
    report = report_path.read_text(encoding="utf-8")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    schema_v2 = is_schema_v2(report)

    try:
        vintage_status = check_vintage(report_path)
        if vintage_status:
            print(vintage_status)
        print(check_point_in_time(report_path, baseline_path, product_graph_path))
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        fail(f"时点证据校验失败：{exc}")

    limits = DEFAULT_FORMAT_LIMITS
    validate_headlines(report, schema_v2, limits)

    period = baseline.get("coverage_period", {})
    start = period.get("start")
    end = period.get("end")
    if not start or not end:
        fail("基线缺少 coverage_period.start/end")
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        fail(f"覆盖日期无效：{exc}")
    report_date_match = re.search(r"(\d{4}-\d{2}-\d{2})", report_path.name)
    if not report_date_match:
        fail(f"无法从周报文件名识别报告日期：{report_path.name}")
    report_date = date.fromisoformat(report_date_match.group(1))
    if report_date.weekday() != 0:
        fail(f"周报文件日期必须是周一：{report_date}")
    expected_start = report_date - timedelta(days=7)
    expected_end = report_date - timedelta(days=1)
    if start_date != expected_start or end_date != expected_end:
        fail(f"覆盖周期必须是报告周一的上一周：expected={expected_start} 至 {expected_end}")
    expected_period = f"{start} 至 {end}"
    if expected_period not in report:
        fail(f"周报没有包含覆盖周期：{expected_period}")

    companies = baseline.get("companies")
    if companies not in ALLOWED_COMPANY_SCOPES:
        fail("基线公司列表缺失，或未按要求的标准顺序排列")
    required_companies = list(companies)
    for company in required_companies:
        if company not in report:
            fail(f"周报未提及必需公司：{company}")

    edges = baseline.get("edges")
    if not isinstance(edges, list) or not edges:
        fail("基线 edges 必须是非空列表")
    # Schema v2 keeps the cumulative baseline; only weekly changes enter the table.
    if len(edges) < 8 or (not schema_v2 and len(edges) > 25):
        fail(f"基线关系数量超出预期范围：{len(edges)}")

    json_ids: set[str] = set()
    for edge in edges:
        for field in REQUIRED_EDGE_FIELDS:
            if field not in edge:
                fail(f"供应关系缺少必需字段 {field}：{edge}")
        edge_id = edge["edge_id"]
        if not re.fullmatch(r"E\d{2}", edge_id):
            fail(f"edge_id 无效：{edge_id}")
        if edge_id in json_ids:
            fail(f"edge_id 重复：{edge_id}")
        json_ids.add(edge_id)
        if not edge["sources"]:
            fail(f"供应关系缺少来源：{edge_id}")
        if any(not str(source).startswith(("http://", "https://")) for source in edge["sources"]):
            fail(f"供应关系包含非 URL 来源：{edge_id}")
        joined = " ".join(str(edge.get(key, "")) for key in ("status", "source_type", "confidence_reason", "notes"))
        low_confidence = edge.get("confidence") in {"low", "low_medium", "medium"}
        limitation_pattern = (
            r"media|baseline|insufficient|risk|no_new|not a new|not new|"
            r"媒体|基线|不足|风险|无订单|不是新|不能|未确认|无官方|未披露|尚无"
        )
        if low_confidence and not re.search(limitation_pattern, joined, re.I):
            fail(f"低/中可信度供应关系缺少限制说明：{edge_id}")

    if schema_v2:
        validate_v2_structure(report, baseline, required_companies, expected_changed_edge_ids, limits)
    else:
        mermaid = extract_mermaid(report)
        if "flowchart LR" not in mermaid:
            fail("Mermaid 图必须使用 flowchart LR")
        for company in required_companies:
            if company not in mermaid:
                fail(f"Mermaid 图缺少公司节点：{company}")
        mermaid_ids = edge_ids_from_text(mermaid)

        table = extract_section(report, "### 6.2 供应关系明细表", "### 6.3")
        table_ids = set(re.findall(r"\| (E\d{2}) \|", table))
        if json_ids != mermaid_ids or json_ids != table_ids:
            fail(
                "Edge ID 不一致："
                f"json={sorted(json_ids)} mermaid={sorted(mermaid_ids)} table={sorted(table_ids)}"
            )

    disallowed_phrases = [
        "提交与推送在本次文件校验后执行",
        "将在校验通过后追加提交",
        "图中重要边均能",
        "已提交并推送",
        "origin/main",
    ]
    for phrase in disallowed_phrases:
        if phrase in report:
            fail(f"周报包含过期或不精确的自检表述：{phrase}")

    validate_latest(latest_path)
    validate_source_audit(source_audit_path, report_path, baseline_path, product_graph_path)
    validate_product_graph(
        report,
        product_graph_path,
        product_image_path,
        product_canvas_path,
        required_companies,
    )
    validate_supply_artifacts(report, supply_image_path, supply_canvas_path, json_ids)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="reports/2026-06-29_weekly_morning_brief.md")
    parser.add_argument("--baseline", default="state/supply_graph_baseline.json")
    parser.add_argument("--latest", default="reports/latest.md")
    parser.add_argument("--source-audit")
    parser.add_argument("--product-graph")
    parser.add_argument("--product-image")
    parser.add_argument("--product-canvas")
    parser.add_argument("--supply-image")
    parser.add_argument("--supply-canvas")
    parser.add_argument("--expected-changed-edge-ids", nargs="*")
    parser.add_argument("--preflight-only", action="store_true", help="只读正文结构预检，不认证来源、时点、图谱或发布状态")
    args = parser.parse_args()

    if args.preflight_only:
        preflight_report(Path(args.report), Path(args.baseline))
        print("正文格式预检通过；不是完整质量闸门或事实认证")
        return

    validate_report(
        Path(args.report),
        Path(args.baseline),
        Path(args.latest),
        Path(args.source_audit) if args.source_audit else None,
        Path(args.product_graph) if args.product_graph else None,
        Path(args.product_image) if args.product_image else None,
        Path(args.product_canvas) if args.product_canvas else None,
        Path(args.supply_image) if args.supply_image else None,
        Path(args.supply_canvas) if args.supply_canvas else None,
        set(args.expected_changed_edge_ids) if args.expected_changed_edge_ids is not None else None,
    )
    print("周报主校验通过")


if __name__ == "__main__":
    main()

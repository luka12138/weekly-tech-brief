#!/usr/bin/env python3
"""提交或推送前校验每周简报产物。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path


REQUIRED_COMPANIES = [
    "Apple",
    "Microsoft",
    "Alphabet / Google",
    "Amazon / AWS",
    "Meta",
    "NVIDIA",
    "Tesla",
    "Samsung Electronics",
    "SK Hynix",
    "TSMC",
]

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


def collect_urls(report_path: Path, baseline_path: Path | None) -> list[str]:
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


def validate_source_audit(audit_path: Path | None, report_path: Path, baseline_path: Path) -> None:
    if audit_path is None:
        return
    if not audit_path.exists():
        fail(f"来源审查文件不存在：{audit_path}")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("report_sha256") != sha256_file(report_path):
        fail("来源审查日志不是由当前周报生成")
    if audit.get("baseline_sha256") != sha256_file(baseline_path):
        fail("来源审查日志不是由当前供应关系基线生成")
    current_urls = collect_urls(report_path, baseline_path)
    if audit.get("audited_urls") != current_urls:
        fail("来源审查 URL 清单与当前周报/基线不一致")
    summary = audit.get("summary", {})
    if summary.get("total", 0) <= 0:
        fail("来源审查没有审查任何 URL")
    if summary.get("unclassified", 0) != 0:
        fail("来源审查包含未分类来源")
    if summary.get("errors", 0) != 0:
        fail("来源审查包含可达性错误")
    for source in audit.get("sources", []):
        if not source.get("url", "").startswith("https://"):
            fail(f"来源审查包含非 HTTPS URL：{source}")
        if not source.get("reachable"):
            fail(f"来源审查包含不可达 URL：{source}")


def validate_product_graph(report: str, product_graph_path: Path | None, product_image_path: Path | None) -> None:
    if product_graph_path is None and product_image_path is None:
        return
    if product_graph_path is None or product_image_path is None:
        fail("产品关系 JSON 和产品关系图片必须同时提供")
    if not product_graph_path.exists():
        fail(f"产品关系 JSON 不存在：{product_graph_path}")
    if not product_image_path.exists():
        fail(f"产品关系图片不存在：{product_image_path}")
    if product_image_path.suffix.lower() not in {".svg", ".png", ".jpg", ".jpeg", ".webp"}:
        fail(f"不支持的产品关系图片类型：{product_image_path}")
    expected_image_ref = str(product_image_path).replace("\\", "/")
    alternate_image_ref = "../" + expected_image_ref
    if expected_image_ref not in report and alternate_image_ref not in report:
        fail(f"周报没有引用产品关系图片：{expected_image_ref}")

    product_graph = json.loads(product_graph_path.read_text(encoding="utf-8"))
    companies = product_graph.get("companies")
    if not isinstance(companies, list):
        fail("产品关系图 companies 必须是列表")
    names = [item.get("name") for item in companies]
    if names != REQUIRED_COMPANIES:
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


def validate_supply_image(report: str, supply_image_path: Path | None) -> None:
    if supply_image_path is None:
        return
    if not supply_image_path.exists():
        fail(f"供应关系图片不存在：{supply_image_path}")
    if supply_image_path.suffix.lower() not in {".svg", ".png", ".jpg", ".jpeg", ".webp"}:
        fail(f"不支持的供应关系图片类型：{supply_image_path}")
    expected_image_ref = str(supply_image_path).replace("\\", "/")
    alternate_image_ref = "../" + expected_image_ref
    if expected_image_ref not in report and alternate_image_ref not in report:
        fail(f"周报没有引用供应关系图片：{expected_image_ref}")


def validate_report(
    report_path: Path,
    baseline_path: Path,
    latest_path: Path,
    source_audit_path: Path | None = None,
    product_graph_path: Path | None = None,
    product_image_path: Path | None = None,
    supply_image_path: Path | None = None,
) -> None:
    report = report_path.read_text(encoding="utf-8")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    period = baseline.get("coverage_period", {})
    start = period.get("start")
    end = period.get("end")
    if not start or not end:
        fail("基线缺少 coverage_period.start/end")
    try:
        date.fromisoformat(start)
        date.fromisoformat(end)
    except ValueError as exc:
        fail(f"覆盖日期无效：{exc}")
    expected_period = f"{start} 至 {end}"
    if expected_period not in report:
        fail(f"周报没有包含覆盖周期：{expected_period}")

    companies = baseline.get("companies")
    if companies != REQUIRED_COMPANIES:
        fail("基线公司列表缺失，或未按要求的标准顺序排列")
    for company in REQUIRED_COMPANIES:
        if company not in report:
            fail(f"周报未提及必需公司：{company}")

    edges = baseline.get("edges")
    if not isinstance(edges, list) or not edges:
        fail("基线 edges 必须是非空列表")
    if not (8 <= len(edges) <= 25):
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

    mermaid = extract_mermaid(report)
    if "flowchart LR" not in mermaid:
        fail("Mermaid 图必须使用 flowchart LR")
    for company in REQUIRED_COMPANIES:
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
    validate_source_audit(source_audit_path, report_path, baseline_path)
    validate_product_graph(report, product_graph_path, product_image_path)
    validate_supply_image(report, supply_image_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="reports/2026-06-29_weekly_morning_brief.md")
    parser.add_argument("--baseline", default="state/supply_graph_baseline.json")
    parser.add_argument("--latest", default="reports/latest.md")
    parser.add_argument("--source-audit")
    parser.add_argument("--product-graph")
    parser.add_argument("--product-image")
    parser.add_argument("--supply-image")
    args = parser.parse_args()

    validate_report(
        Path(args.report),
        Path(args.baseline),
        Path(args.latest),
        Path(args.source_audit) if args.source_audit else None,
        Path(args.product_graph) if args.product_graph else None,
        Path(args.product_image) if args.product_image else None,
        Path(args.supply_image) if args.supply_image else None,
    )
    print("周报主校验通过")


if __name__ == "__main__":
    main()

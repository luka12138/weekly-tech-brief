#!/usr/bin/env python3
"""Bind reviewed source passages to the fixed September 21 report inventory."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-09-21"
REPORT = ROOT / "reports" / f"{DAY}_weekly_morning_brief.md"
BASELINE = ROOT / "state/supply_graph_baseline.json"
PRODUCT = ROOT / "state/product_relationships_2026.json"
SKILL = ROOT / ".agents/skills/weekly-tech-brief/SKILL.md"

DEFERRED = {
 "APL-SIRI": "9月14日Apple公告仅有日期，未知时区的完整可能区间跨越本周起点；缺少可认证的首次公开时刻，不能据此列为本期新事项。来源：Apple Siri公告datePublished=2026-09-14Z及raw_v03。",
 "APL-X": "诉讼撤回/和解报道称9月14日，但来源公开时区与具体版本时点不足以证明落在本期窗口；保留未决程序和条款问题。来源：Reuters转录raw_v03。",
 "MS-CODE": "9月14日AI准则草案报道缺乏可认证的本期首次公开时刻；且仍是草案，未发布为生效规则。来源：Reuters转录raw_d04。",
 "GOO-WIN": "Google官方Windows应用公告日期为9月10日，已属上期旧闻，不作为9月21日新事项。来源：Google 9/10公告及raw_d11。",
 "AWS-SAFETY": "Reuters采访为公司治理立场；在本期有限筛选中优先可核的发电机合同，对安全成效的关键事实和具体版本未完成入选核验，不作反面断言。来源：raw_d08。",
 "META-SAFETY": "Reuters所述安全立场与Meta One产品发布不同；未获能改变本期结论的实施证据，暂留资料池，不宣称治理风险解除。来源：raw_d08。",
 "NV-IP": "IP限制报道仍需核对具体合同、对象与因果；本期不将匿名/间接争议写成已确认供应约束，保留未决。来源：raw_d13。",
 "KR-POWER": "电力预付款提案报道缺乏可用的双方原始协议或拒绝文书；金额、义务与生效状态未能确认，不推成已确定资本约束。来源：raw_d07。",
 "SK-NAND": "美国NAND厂选址讨论尚无正式投资、厂址或协议；本期优先公司对Intel报道的明确回应，未核完该匿名线索。来源：raw_d09。",
 "SK-WAGE": "工资协议报道所涉批准日期为9月10日，属于上一窗口；不重复作为本周新事项。来源：raw_d09。",
 "TSM-MTK": "MediaTek 9月15日官方2nm芯片公告未具名TSMC制造关系；独立报道不足以建立可核供应边，不推断新订单。来源：MediaTek公告与raw_d09。",
}

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def interval(day_text: str, locator: str) -> dict:
    day = date.fromisoformat(day_text)
    midnight = datetime.combine(day, datetime.min.time(), timezone.utc)
    return {"published_date": day_text,
            "earliest": (midnight - timedelta(hours=14)).isoformat(),
            "latest_exclusive": (midnight + timedelta(days=1, hours=12)).isoformat(),
            "timezone_basis": "global_utc_minus12_to_plus14",
            "version_locator": locator,
            "note": "原文只证明日期，未证明时区或钟点；保留完整全球50小时可能区间，端点不是实际发布时间。"}

def main() -> None:
    data = json.loads((ROOT / "logs" / f"{DAY}_verified_events.json").read_text())
    coverage_path = ROOT / "logs" / f"{DAY}_research_coverage.json"
    coverage = json.loads(coverage_path.read_text())
    inventory = json.loads((ROOT / "logs" / f"{DAY}_point_in_time_inventory_v2.json").read_text())
    events = data["events"]
    event_ids = {e["id"] for e in events}
    headlines = {cid: i for i, cid in enumerate(data["headlines"], 1)}
    event_num = {e["id"]: i for i, e in enumerate(events, 1)}
    raw_files = sorted((ROOT / "logs").glob(f"{DAY}_raw_*.json"))
    raw_payloads = [(path, json.loads(path.read_text())) for path in raw_files]
    direct = {item["id"]: item for item in json.loads((ROOT / "logs" / f"{DAY}_direct_source_receipts.json").read_text())["records"]}
    claims = []
    linked = {}
    for e in events:
        hits = [(path, raw) for path, raw in raw_payloads if e["url"] in str(raw.get("result", ""))]
        if e["id"] in direct and direct[e["id"]].get("http_status") == 200:
            receipt_path = ROOT / "logs" / f"{DAY}_direct_source_receipts.json"
            retrieved = direct[e["id"]]["retrieved_at"]
        elif hits:
            receipt_path, raw = hits[-1]
            stamp = raw["at"]
            if isinstance(stamp, dict):
                stamp = stamp["current_time"]
            retrieved = str(stamp).replace(" UTC", "+00:00").replace(" ", "T", 1)
        else:
            raise ValueError(f"{e['id']}: no captured source retrieval")
        refs = [f"event:{event_num[e['id']]}", f"company:{e['company']}"]
        if e["id"] in headlines:
            refs.append(f"headline:{headlines[e['id']]}")
        for i, (_, ids) in enumerate(data["analyses"], 1):
            if e["id"] in ids:
                refs.append(f"analysis:{i}")
        for i, (_, ids) in enumerate(data["catalysts"], 1):
            if e["id"] in ids:
                refs.append(f"catalyst:{i}")
        if e["id"] == "AWS-GEN":
            refs.append("supply:E37")
        assert set(refs) <= set(inventory), (e["id"], set(refs) - set(inventory))
        parts = [s.strip() for s in re.split(r"[；。]", e["fact"]) if s.strip()]
        if not parts:
            raise ValueError(f"{e['id']}: empty factual statement")
        linked[e["id"]] = []
        for n, statement in enumerate(parts, 1):
            claim_id = f"{e['id']}-{n}"
            linked[e["id"]].append(claim_id)
            source = {"url": e["url"], "retrieved_at": retrieved,
                      "basis": e.get("basis", "filing" if e["id"] == "AWS-GEN" else "dated_release"),
                      "locator": f"{e['locator']}；本地回执 {receipt_path.relative_to(ROOT)}#{e['id']}",
                      "claim_first_public_interval": interval(e["date"], e["locator"]),
                      "support": statement}
            claims.append({"id": claim_id, "candidate_id": e["id"], "kind": "news",
                           "statement": statement, "targets": refs, "evidence": [source]})
    # A no-selected-update company row is still a conclusion requiring an
    # explicit bounded evidence trail, even though it has no selected event.
    mediatek = direct["TSM-MTK"]
    claims.append({"id": "TSMC-NO-SELECTED-1", "kind": "analysis",
                   "statement": "本期有限检查未取得MediaTek 2nm产品与TSMC具名制造关系的官方确认，因此不新增TSMC供应边或公司特定入选事项。",
                   "targets": ["company:TSMC"], "evidence": [{
                       "url": mediatek["url"], "retrieved_at": mediatek["retrieved_at"],
                       "basis": "dated_release", "locator": "MediaTek 9月15日2nm Dimensity 9600 Pro公告全文及TSMC官方投资者入口有限检查；本地回执logs/2026-09-21_direct_source_receipts.json#TSM-MTK",
                       "claim_first_public_interval": interval("2026-09-15", "MediaTek 9月15日公告具体正文"),
                       "support": "该公告称2nm产品，但未具名TSMC为制造方；有限范围内不推断确定关系。"}]})
    missing = set(inventory) - {target for claim in claims for target in claim["targets"]}
    if missing:
        raise ValueError(f"uncovered targets: {sorted(missing)}")
    now = utc_now()
    created = datetime.fromtimestamp(REPORT.stat().st_mtime, timezone.utc).isoformat()
    evidence = {"schema_version": 1, "report_date": DAY, "cutoff_exclusive": "2026-09-21T00:00:00+08:00",
                "status": "ready", "report_created_at": created, "reviewed_at": now,
                "report_sha256": digest(REPORT), "baseline_sha256": digest(BASELINE),
                "product_graph_sha256": digest(PRODUCT),
                "manual_reviews": {
                    "financial_periods_and_units": {"status": "reviewed", "note": "SEC 8-K的24亿美元是2027—2028年预计初始交付、80亿美元为认股权证后续归属付款阶梯；Microsoft 0.98美元是每股季度股息，11月登记、12月支付；Anthropic/Accenture是双方各自五年预计至少10亿美元。三者不合并为本期收入。"},
                    "source_versions": {"status": "reviewed", "note": "逐项核对16项官方或Reuters具体正文及日期；Meta页面显示9月15日及16日更新，Google Live页面显示9月15日及17日更新，均在截止前。9月14日边界不明候选与9月10日Windows旧闻未作为news。研究原文回执在raw及direct_source_receipts。"},
                    "product_graph": {"status": "reviewed", "note": "按年度产品图索引及本期变化核对；9月21日没有已证实的主营产品关系实质变化，沿用9月14日图。MediaTek原文未具名TSMC，故不增产品或供应边；供应图仅新合同E37。"},
                    "report_vintage": {"status": "reviewed", "note": "9月21日报告在截止后生成并以当前文件哈希绑定；9月14日已发布报告和图保持原哈希，只读用于上周对照。归档的9月21日生产前快照不冒充原周一发布版本。"}},
                "claims": claims,
                "excluded_candidates": [{"id": key, "disposition": "deferred", "reason": reason} for key, reason in DEFERRED.items()]}
    evidence_path = ROOT / "logs" / f"{DAY}_temporal_evidence.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")

    for c in coverage["candidates"]:
        cid = c["id"]
        if cid in event_ids:
            c["disposition"] = "included"
            c["reason"] = "经本期有限筛选及具体来源核验，列入独立事项；事实限制见正文和时点证据。"
            c["claim_ids"] = linked[cid]
            c["targets"] = [f"company:{next(e['company'] for e in events if e['id']==cid)}", f"event:{event_num[cid]}"]
            c["research"]["open_questions"] = []
            c["research"]["next_action"] = {"kind": "closed", "target": cid, "question": "本期入选事实已按原文和窗口核验"}
            e = next(e for e in events if e["id"] == cid)
            hits = [(path, raw) for path, raw in raw_payloads if e["url"] in str(raw.get("result", ""))]
            source_path = (ROOT / "logs" / f"{DAY}_direct_source_receipts.json") if cid in direct else hits[-1][0]
            material = {"role": "source_review", "path": str(source_path.relative_to(ROOT)), "locator": e["locator"]}
            if material not in c["research"]["materials"]:
                c["research"]["materials"].append(material)
        else:
            c["disposition"] = "deferred"
            c["reason"] = DEFERRED[cid]
            c["decision_evidence"] = DEFERRED[cid]
            c.pop("claim_ids", None)
            c.pop("targets", None)
    conclusions = {}
    for company in ["Apple", "Microsoft", "Alphabet / Google", "Amazon / AWS", "Meta", "NVIDIA", "Tesla", "OpenAI", "Anthropic", "Samsung Electronics", "SK Hynix", "TSMC"]:
        selected = [e["id"] for e in events if e["company"] == company]
        checks = [c for c in coverage["checks"] if c["company"] == company]
        official = [c for c in checks if c["source_family"] == "company" and c["stage"] == "discovery" and c["status"] == "reviewed"]
        independent = [c for c in checks if c["source_family"] in {"media", "authority"} and c["status"] == "reviewed"]
        if not official or not independent:
            raise ValueError(f"{company}: missing bounded official/independent check")
        conclusions[company] = {"status": "events" if selected else "no_selected_update",
             "selected_candidate_ids": selected,
             "check_ids": [official[0]["id"], independent[0]["id"]],
             "note": f"完成官方入口及独立重要性校准；本期选入{len(selected)}项，不宣称零遗漏。",
             "selection_reason": "按产品可用阶段、资本/供应承诺、监管经营资格和治理影响排序；仅纳入具体版本及时间可核事项。" if selected else "官方及独立渠道有限筛选后未选入可核的本周公司特定重要事项，未断言公司没有变化。",
             "legal_review": "本期法律/监管线索依公开机关或具日期媒体核对；问询不等于裁决，未入选线索保留未决。"}
    coverage["company_conclusions"] = conclusions
    for item in coverage["watchlist"]:
        item["status"] = "active"
        item["review_scope"] = "not_selected"
        item["defer_reason"] = "本期有限筛选未选为前五独立事项，继续保留原未决状态；不宣称风险解决。"
    coverage["status"] = "ready"
    coverage["gaps"] = []
    coverage["report_sha256"] = digest(REPORT)
    coverage["product_graph_sha256"] = digest(PRODUCT)
    coverage["skill_sha256"] = digest(SKILL)
    coverage["reviewed_at"] = utc_now()
    coverage["selection_note"] = "16项具日期具体版本核验后发布，11项未入选线索保留来源与未决理由；每家公司最多5项。"
    coverage_path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"claims": len(claims), "targets": len(inventory), "included": len(event_ids), "deferred": len(DEFERRED)}, ensure_ascii=False))

if __name__ == "__main__":
    main()

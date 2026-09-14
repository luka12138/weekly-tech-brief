#!/usr/bin/env python3
"""Check research closure records, not search recall or source truth."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, time, timedelta
from pathlib import Path

from validate_point_in_time import SHANGHAI, collect_targets, digest, report_day, timestamp
from validate_weekly_brief import REQUIRED_COMPANIES, validate_v2_company_details


ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {"financial", "product", "capital", "operations", "legal", "governance"}
STAGES = {"discovery", "regulatory", "countercheck"}
ACTIONS = {"recover_existing", "fetch_gap", "bind_evidence", "split_candidate", "follow_canonical", "closed"}
MATERIAL_ROLES = {"source_review", "draft", "receipt", "legacy_record"}
SELECTION_POLICY = "company_top5"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def indexed(items: object, label: str) -> dict:
    require(isinstance(items, list), f"{label}: require list")
    result = {}
    for item in items:
        require(isinstance(item, dict), f"{label}: require objects")
        key = item.get("id")
        require(nonempty(key) and key not in result, f"{label}: missing/duplicate id")
        result[key] = item
    return result


def refs(value: object, available: object, label: str, allow_empty: bool = False) -> set:
    require(isinstance(value, list) and (bool(value) or allow_empty), f"{label}: require references")
    require(all(nonempty(v) for v in value), f"{label}: invalid reference")
    require(len(set(value)) == len(value) and set(value) <= set(available), f"{label}: unknown/duplicate reference")
    return set(value)


def validate_event_workflow(data: dict, ready: bool = False) -> dict:
    """Validate work-card links; never infer factual verification from a card."""
    require(type(data.get("workflow_version")) is int and data["workflow_version"] == 2,
            "event workflow_version:2 required")
    candidates = indexed(data.get("candidates"), "workflow candidates")
    roots = {}
    for identity, candidate in candidates.items():
        card = candidate.get("research")
        require(isinstance(card, dict), f"{identity}: missing research work card")
        require(nonempty(card.get("event_key")), f"{identity}: missing event identity")
        canonical = card.get("canonical_id")
        require(nonempty(canonical) and canonical in candidates, f"{identity}: unknown canonical candidate")
        require(card.get("identity_status") in {"identified", "needs_split"}, f"{identity}: identity status invalid")
        materials = card.get("materials")
        require(isinstance(materials, list) and bool(materials), f"{identity}: missing recovery materials")
        for material in materials:
            require(isinstance(material, dict) and material.get("role") in MATERIAL_ROLES and
                    nonempty(material.get("path")) and nonempty(material.get("locator")),
                    f"{identity}: invalid material locator")
        questions = card.get("open_questions")
        require(isinstance(questions, list) and all(nonempty(q) for q in questions),
                f"{identity}: invalid open questions")
        action = card.get("next_action")
        require(isinstance(action, dict) and action.get("kind") in ACTIONS and
                nonempty(action.get("target")) and nonempty(action.get("question")),
                f"{identity}: next action needs a concrete target and question")
        if canonical == identity:
            require(card["event_key"] not in roots, f"{identity}: duplicate root event identity")
            roots[card["event_key"]] = identity
            require(action["kind"] != "follow_canonical", f"{identity}: root cannot follow itself")
            require(not questions or action["kind"] != "closed", f"{identity}: open questions marked closed")
            require(candidate.get("disposition") != "pending" or bool(questions),
                    f"{identity}: pending candidate needs an actionable question")
            if card["identity_status"] == "needs_split":
                require(action["kind"] == "split_candidate", f"{identity}: mixed events need a split action")
            if candidate.get("disposition") == "excluded" and candidate.get("exclusion_basis") == "duplicate":
                require(False, f"{identity}: duplicate exclusion needs a different canonical candidate")
        else:
            require(not questions and action["kind"] == "follow_canonical" and action["target"] == canonical,
                    f"{identity}: alias questions must transfer to canonical, not be discarded")
        if ready:
            if data.get("selection_policy") == SELECTION_POLICY and candidate.get("disposition") == "deferred":
                continue
            elif candidate.get("disposition") == "quarantined":
                require(canonical == identity and card["identity_status"] == "identified" and
                        bool(questions) and action["kind"] == "fetch_gap",
                        f"{identity}: quarantined lead must retain an explicit verification gap")
            else:
                require(not questions and card["identity_status"] == "identified",
                        f"{identity}: unresolved work-card questions or mixed events")
                if canonical == identity:
                    require(action["kind"] == "closed", f"{identity}: work-card action not closed")

    for identity, candidate in candidates.items():
        card = candidate["research"]
        canonical = candidates[card["canonical_id"]]
        parent = canonical["research"]
        require(parent["canonical_id"] == canonical["id"], f"{identity}: alias chain/cycle is not allowed")
        require(card["event_key"] == parent["event_key"], f"{identity}: distinct events/stages cannot share canonical")
        require(set(candidate.get("companies", [])) <= set(canonical.get("companies", [])),
                f"{identity}: canonical lost an affected company")
        expected = {key for key, value in candidates.items() if value["research"]["canonical_id"] == canonical["id"]}
        require(refs(parent.get("member_ids"), candidates, f"{canonical['id']}.member_ids") == expected,
                f"{identity}: canonical must retain all member IDs and their materials")
        if ready and identity != canonical["id"]:
            require(candidate.get("disposition") == "excluded" and candidate.get("exclusion_basis") == "duplicate",
                    f"{identity}: alias must have a traceable duplicate disposition")
    return candidates


def validate_material_references(candidates: dict, root: Path) -> None:
    """Check recoverable local receipts, not the truth of their contents."""
    receipts = {}
    for identity, candidate in candidates.items():
        for material in candidate["research"]["materials"]:
            path = (root / material["path"]).resolve()
            require(path.is_relative_to(root.resolve()) and path.is_file(),
                    f"{identity}: material file missing or outside repository")
            if material["role"] != "receipt":
                continue
            if path not in receipts:
                payload = json.loads(path.read_text(encoding="utf-8"))
                require(isinstance(payload, dict), f"{identity}: invalid receipt file type")
                receipts[path] = indexed(payload.get("records"), str(path))
            selected = refs(material.get("record_ids"), receipts[path], f"{identity}.receipt record_ids")
            for key in selected:
                result = receipts[path][key].get("result")
                require(isinstance(result, (str, dict, list)) and bool(result) and
                        (not isinstance(result, str) or bool(result.strip())),
                        f"{identity}: receipt {key} has no actual tool result; cannot recover from an ID/summary")


def build_worklist(data: dict, company: str | None = None, candidate_id: str | None = None,
                   root: Path | None = None) -> dict:
    candidates = validate_event_workflow(data)
    if root is not None:
        validate_material_references(candidates, root)

    def check_gaps(name: str) -> dict:
        rows = [c for c in data.get("checks", []) if c.get("company") == name]
        if data.get("selection_policy") == SELECTION_POLICY:
            conclusion = data.get("company_conclusions", {}).get(name, {})
            return {"selected_candidate_ids": conclusion.get("selected_candidate_ids", []),
                    "recorded_conclusion": conclusion.get("status", "not_recorded"),
                    "scope": "company_top5; deferred work does not block publication"}
        return {"blocked_checks": [c["id"] for c in rows if c.get("status") != "reviewed"],
                "missing_stage_records": sorted(STAGES - {c.get("stage") for c in rows}),
                "official_discovery_recorded_reviewed": any(
                    c.get("stage") == "discovery" and c.get("source_family") == "company" and
                    c.get("status") == "reviewed" for c in rows),
                "recorded_conclusion": data.get("company_conclusions", {}).get(name, {}).get("status", "not_recorded")}

    if candidate_id:
        require(candidate_id in candidates, "unknown candidate filter")
        candidate = candidates[candidate_id]
        canonical = candidates[candidate["research"]["canonical_id"]]
        return {"publication_certified": False, "candidate": candidate,
                "canonical": canonical if canonical is not candidate else None}
    roots = [c for c in candidates.values() if c["research"]["canonical_id"] == c["id"]]
    if data.get("selection_policy") == SELECTION_POLICY:
        roots = [c for c in roots if c.get("disposition") != "deferred"]
    if company:
        require(company in REQUIRED_COMPANIES, "unknown company filter")
        return {"publication_certified": False, "company": company,
                "work": [{"id": c["id"], "summary": c["summary"], "research": c["research"]}
                         for c in roots if company in c["companies"]],
                **check_gaps(company)}
    return {"publication_certified": False, "status": data.get("status"),
            "candidate_records": len(candidates), "canonical_candidates": len(roots),
            "aliases": len(candidates) - len(roots),
            "companies": {name: {"events": len(rows),
                                 "open": [c["id"] for c in rows if c["research"]["open_questions"] or
                                          c["research"]["identity_status"] != "identified"],
                                 **check_gaps(name)}
                          for name in REQUIRED_COMPANIES
                          for rows in [[c for c in roots if name in c["companies"]]]}}


def validate_coverage(data: dict, report: Path, product: Path, skill: Path,
                      evidence: dict, root: Path) -> None:
    day = report_day(report)
    cutoff = datetime.combine(day, time.min, SHANGHAI)
    require(isinstance(data, dict) and data.get("schema_version") == 1, "coverage schema mismatch")
    require(data.get("report_date") == day.isoformat(), "coverage report date mismatch")
    require(timestamp(data.get("cutoff_exclusive"), "cutoff") == cutoff, "coverage cutoff mismatch")
    require(data.get("status") == "ready", "coverage is draft/unresolved; publication blocked")
    selected_scope = data.get("selection_policy") == SELECTION_POLICY
    require(data.get("selection_policy") in {None, SELECTION_POLICY}, "unknown selection policy")
    event_workflow = data.get("workflow_version") is not None or day.isoformat() >= "2026-09-14"
    if event_workflow:
        validate_material_references(validate_event_workflow(data, ready=True), root)
    if day.isoformat() >= "2026-09-14":
        require(selected_scope, "company_top5 selection policy required for new reports")
    for key, path in (("report_sha256", report), ("product_graph_sha256", product), ("skill_sha256", skill)):
        require(data.get(key) == digest(path), f"{key}: stale coverage; review changed inputs")
    if "<!-- company-selection: top5 -->" in report.read_text(encoding="utf-8"):
        require(selected_scope, "top5 report cannot use legacy coverage policy")
    reviewed = timestamp(data.get("reviewed_at"), "coverage reviewed_at")
    require(cutoff <= reviewed <= datetime.now(SHANGHAI) + timedelta(minutes=5), "invalid coverage review time")
    require(evidence.get("report_sha256") == digest(report), "coverage requires current temporal evidence")
    products = json.loads(product.read_text(encoding="utf-8"))
    companies = {c["name"]: set(c["main_products"]) for c in products["companies"]}
    require(set(companies) == set(REQUIRED_COMPANIES), "product company scope mismatch")
    prior = data.get("prior_report", {})
    previous_day = (day - timedelta(days=7)).isoformat()
    prior_path = root / "reports" / f"{previous_day}_weekly_morning_brief.md"
    reviewed_prior = prior_path
    if "frozen_path" in prior:
        require(nonempty(prior["frozen_path"]), "prior frozen path is empty")
        reviewed_prior = (root / prior["frozen_path"]).resolve()
        require(reviewed_prior.is_relative_to((root / "archives").resolve()) and
                reviewed_prior.name == prior_path.name and reviewed_prior.is_file(),
                "prior frozen snapshot must be the dated report inside archives")
    require(prior.get("path") == str(prior_path.relative_to(root)) and
            prior.get("sha256") == digest(reviewed_prior) and nonempty(prior.get("note")),
            "prior report review missing/stale; recover ongoing matters")

    checks = indexed(data.get("checks"), "checks")
    candidates = indexed(data.get("candidates"), "candidates")
    if selected_scope:
        validate_company_selection(data, candidates, checks, report)
    for key, check in checks.items():
        company, stage = check.get("company"), check.get("stage")
        require(company in companies and stage in STAGES, f"{key}: company/stage invalid")
        require(check.get("status") in ({"reviewed", "blocked"} if selected_scope else {"reviewed"}),
                f"{key}: blocked/unreviewed check")
        for field in ("query_or_url", "result_ref", "note", "entrypoint"):
            require(nonempty(check.get(field)), f"{key}: missing {field}")
        require(check.get("source_family") in {"company", "authority", "media", "search"}, f"{key}: invalid source family")
        at = timestamp(check.get("checked_at"), f"{key}.checked_at")
        require(cutoff <= at <= reviewed, f"{key}: invalid check time")
        refs(check.get("businesses"), companies[company], f"{key}.businesses", allow_empty=stage != "discovery")
        refs(check.get("categories"), CATEGORIES, f"{key}.categories")
        found = refs(check.get("candidate_ids"), candidates, f"{key}.candidate_ids", allow_empty=True)
        for identity in found:
            require(company in candidates[identity].get("companies", []), f"{key}: candidate company mismatch")
        if stage == "regulatory":
            require(check["source_family"] != "company" and "legal" in check["categories"],
                    f"{key}: regulatory check cannot rely only on company publicity")

    conclusions = data.get("company_conclusions", {})
    require(isinstance(conclusions, dict) and set(conclusions) == set(companies), "12 company conclusions required")
    for company, businesses in companies.items():
        rows = [c for c in checks.values() if c["company"] == company]
        if selected_scope:
            continue
        require({c["stage"] for c in rows} == STAGES, f"{company}: missing discovery/regulatory/countercheck")
        discovery = [c for c in rows if c["stage"] == "discovery"]
        if event_workflow:
            require(any(c["source_family"] == "company" for c in discovery),
                    f"{company}: official company channel check cannot be replaced by media")
        require(set().union(*(set(c["businesses"]) for c in discovery)) >= businesses,
                f"{company}: missing main business coverage")
        require(set().union(*(set(c["categories"]) for c in rows if c["stage"] != "countercheck")) == CATEGORIES,
                f"{company}: missing event category coverage")
        earlier = [c for c in rows if c["stage"] != "countercheck"]
        require(any(c["entrypoint"] not in {d["entrypoint"] for d in earlier} and
                    c["source_family"] in {"authority", "media"} and
                    timestamp(c["checked_at"], "countercheck") >= max(timestamp(d["checked_at"], "check") for d in earlier)
                    for c in rows if c["stage"] == "countercheck"),
                f"{company}: reverse check needs a later, different authority/media entrypoint")
        conclusion = conclusions[company]
        require(isinstance(conclusion, dict) and nonempty(conclusion.get("note")), f"{company}: missing conclusion rationale")
        require(conclusion.get("status") in {"events", "no_company_specific_change"}, f"{company}: unresolved conclusion")
        if conclusion["status"] == "no_company_specific_change":
            require(not any(company in c.get("companies", []) and c.get("materiality") in {"material", "unresolved"}
                            and c.get("disposition") in {"included", "pending"} for c in candidates.values()),
                    f"{company}: no-change conclusion conflicts with candidate")

    claims = indexed(evidence.get("claims"), "temporal claims")
    report_text = report.read_text(encoding="utf-8")
    targets = collect_targets(report_text, {"edges": []})
    quarantine_ids = set()
    for identity, candidate in candidates.items():
        affected = refs(candidate.get("companies"), companies, f"{identity}.companies")
        discovered = refs(candidate.get("discovered_by"), checks, f"{identity}.discovered_by")
        for key in discovered:
            require(identity in checks[key]["candidate_ids"] and checks[key]["company"] in affected,
                    f"{identity}: discovery link mismatch")
        for field in ("summary", "materiality_reason", "reason"):
            require(nonempty(candidate.get(field)), f"{identity}: missing {field}")
        disposition = candidate.get("disposition")
        if selected_scope and disposition == "deferred":
            require(nonempty(candidate.get("decision_evidence")), f"{identity}: deferred item needs traceable selection rationale")
            require(not candidate.get("claim_ids") and not candidate.get("targets") and
                    not any(c.get("candidate_id") == identity for c in claims.values()),
                    f"{identity}: deferred item leaked into published evidence")
            continue
        if disposition == "quarantined":
            validate_quarantined_lead(data, candidate, claims, report_text, reviewed)
            quarantine_ids.add(identity)
            continue
        require(candidate.get("materiality") in {"material", "routine"}, f"{identity}: unresolved materiality")
        require(disposition in {"included", "background", "future_plan", "excluded"}, f"{identity}: pending candidate")
        if disposition == "excluded":
            require(candidate.get("exclusion_basis") in {"outside_window", "duplicate", "not_material", "unsupported"},
                    f"{identity}: invalid exclusion basis (headline/space limits are not reasons)")
            require(not (candidate["materiality"] == "material" and candidate["exclusion_basis"] in {"not_material", "unsupported"}),
                    f"{identity}: unresolved material item cannot be silently excluded")
            require(nonempty(candidate.get("decision_evidence")), f"{identity}: exclusion needs traceable evidence")
            continue
        linked = refs(candidate.get("claim_ids"), claims, f"{identity}.claim_ids")
        locations = refs(candidate.get("targets"), targets, f"{identity}.targets")
        require(locations <= set().union(*(set(claims[c]["targets"]) for c in linked)), f"{identity}: target not supported by linked claim")
        for company in affected:
            require(f"company:{company}" in locations, f"{identity}: affected company conclusion missing")
        if candidate["materiality"] == "material" and disposition == "included":
            require(any(t.startswith("event:") for t in locations), f"{identity}: material event missing from company details")

    require(set(re.findall(r"<!-- quarantined-lead:([^\s<>]+) -->", report_text)) == quarantine_ids,
            "quarantined appendix and candidate records disagree")

    watchlist = indexed(data.get("watchlist"), "watchlist")
    for key, item in watchlist.items():
        affected = refs(item.get("companies"), companies, f"{key}.companies")
        if selected_scope and item.get("review_scope") == "not_selected":
            require(item.get("status") == "active" and nonempty(item.get("topic")) and
                    nonempty(item.get("note")) and nonempty(item.get("defer_reason")),
                    f"{key}: deferred watch must retain its unresolved state and rationale")
            continue
        checked = refs(item.get("check_ids"), checks, f"{key}.check_ids")
        require(all(checks[c].get("status") == "reviewed" for c in checked),
                f"{key}: ongoing matter relies on blocked check")
        require({checks[c]["company"] for c in checked} >= affected, f"{key}: ongoing matter missing company checks")
        require(item.get("status") in {"active", "closed"} and nonempty(item.get("topic")) and nonempty(item.get("note")),
                f"{key}: ongoing matter not resolved for this week")
    previous_coverage = root / "logs" / f"{previous_day}_research_coverage.json"
    if previous_coverage.exists():
        old = json.loads(previous_coverage.read_text(encoding="utf-8"))
        active = {c["id"] for c in old.get("watchlist", []) if c.get("status") == "active"}
        require(active <= set(watchlist), "ongoing matters disappeared from prior watchlist")


def validate_company_selection(data: dict, candidates: dict, checks: dict, report: Path) -> None:
    """Validate a bounded selection without certifying ranking or search recall."""
    report_text = report.read_text(encoding="utf-8")
    require("<!-- company-selection: top5 -->" in report_text, "company_top5 report marker required")
    validate_v2_company_details(report_text, REQUIRED_COMPANIES)
    conclusions = data.get("company_conclusions", {})
    require(isinstance(conclusions, dict) and set(conclusions) == set(REQUIRED_COMPANIES),
            "12 company selections required")
    published = {key for key, c in candidates.items()
                 if c.get("disposition") in {"included", "background", "future_plan"}}
    selected_all = set()
    for company, conclusion in conclusions.items():
        require(isinstance(conclusion, dict) and conclusion.get("status") in
                {"events", "no_selected_update", "limited"}, f"{company}: unresolved selection")
        for field in ("note", "selection_reason", "legal_review"):
            require(nonempty(conclusion.get(field)), f"{company}: missing {field}")
        selected = refs(conclusion.get("selected_candidate_ids"), candidates,
                        f"{company}.selected_candidate_ids", allow_empty=True)
        require(len(selected) <= 5, f"{company}: at most 5 selected events")
        require(selected == {key for key in published if company in candidates[key].get("companies", [])},
                f"{company}: selection and published candidates disagree")
        require(conclusion["status"] == "limited" or
                bool(selected) == (conclusion["status"] == "events"), f"{company}: selection status mismatch")
        selected_all.update(selected)
        check_ids = refs(conclusion.get("check_ids"), checks, f"{company}.check_ids")
        rows = [checks[key] for key in check_ids]
        require(all(c.get("company") == company for c in rows), f"{company}: wrong company check")
        official = [c for c in rows if c.get("source_family") == "company" and c.get("stage") == "discovery"]
        require(bool(official), f"{company}: official company channel attempt required")
        independent = [c for c in rows if c.get("source_family") in {"authority", "media"} and
                       c.get("status") == "reviewed" and
                       c.get("entrypoint") not in {o.get("entrypoint") for o in official}]
        require(bool(independent), f"{company}: independent importance check required")
        if not any(c.get("status") == "reviewed" for c in official):
            require(conclusion["status"] == "limited", f"{company}: official access limitation must be disclosed")
        if conclusion["status"] == "limited":
            limitation = conclusion.get("limitation")
            company_row = next((line for line in report_text.splitlines()
                                if re.match(rf"^\|\s*{re.escape(company)}\s*\|", line)), "")
            require(nonempty(limitation) and limitation in company_row, f"{company}: missing visible limitation")

    event_owners = {}
    for key in selected_all:
        events = [t for t in candidates[key].get("targets", []) if t.startswith("event:")]
        require(bool(events), f"{key}: selected event missing company detail")
        for event in events:
            require(event not in event_owners, f"{event}: distinct candidates cannot be packed into one event")
            event_owners[event] = key
    actual_events = {t for t in collect_targets(report_text, {"edges": []}) if t.startswith("event:")}
    require(set(event_owners) == actual_events, "report events and selected candidates disagree")


def validate_quarantined_lead(data: dict, candidate: dict, claims: dict,
                              report_text: str, reviewed: datetime) -> None:
    identity = candidate["id"]
    require(type(data.get("unconfirmed_lead_policy")) is int and data["unconfirmed_lead_policy"] == 1,
            f"{identity}: explicit unconfirmed lead policy required")
    require(candidate.get("materiality") == "unresolved", f"{identity}: known material/routine event cannot use lead quarantine")
    require(not candidate.get("claim_ids") and not candidate.get("targets"),
            f"{identity}: quarantined lead cannot support confirmed targets")
    require(not any(c.get("candidate_id") == identity for c in claims.values()),
            f"{identity}: quarantined lead leaked into temporal claims")
    q = candidate.get("quarantine", {})
    require(isinstance(q, dict) and q.get("known_material_event") is False,
            f"{identity}: confirmed material event still blocks publication")
    for key in ("confirmed_scope", "unconfirmed_scope", "materiality_assessment", "timing_limit", "next_verification"):
        require(nonempty(q.get(key)), f"{identity}: quarantine missing {key}")
    at = timestamp(q.get("reviewed_at"), f"{identity}.quarantine.reviewed_at")
    require(timestamp(data["cutoff_exclusive"], "cutoff") <= at <= reviewed,
            f"{identity}: invalid quarantine review time")
    urls = q.get("source_urls")
    require(isinstance(urls, list) and bool(urls) and all(nonempty(u) and u.startswith("https://") for u in urls),
            f"{identity}: quarantine requires traceable source links")
    opening, closing = f"<!-- quarantined-lead:{identity} -->", f"<!-- /quarantined-lead:{identity} -->"
    appendix = re.search(r"^## 7\.[^\n]*\n(.*?)(?=^## |\Z)", report_text, re.M | re.S)
    require(appendix is not None and report_text.count(opening) == 1 and report_text.count(closing) == 1,
            f"{identity}: one visible quarantine appendix block required")
    match = re.search(re.escape(opening) + r"(.*?)" + re.escape(closing), appendix[1], re.S)
    require(match is not None, f"{identity}: lead must stay in section 7 appendix")
    block = match[1]
    require("未确认" in block and "不计入当周事实、投资判断或图谱" in block and
            "不作为当时已知或回测输入" in block,
            f"{identity}: appendix must disclose the non-evidence boundary")
    require(all(q[key] in block for key in ("confirmed_scope", "unconfirmed_scope", "materiality_assessment", "timing_limit", "next_verification"))
            and all(url in block for url in urls), f"{identity}: appendix hides a verification gap or source")


def check_coverage(report: Path, product: Path, root: Path = ROOT) -> str:
    day = report_day(report).isoformat()
    path = root / "logs" / f"{day}_research_coverage.json"
    require(path.exists(), f"missing research closure: {path}; do not fabricate completion")
    data = json.loads(path.read_text(encoding="utf-8"))
    evidence = json.loads((root / "logs" / f"{day}_temporal_evidence.json").read_text(encoding="utf-8"))
    validate_coverage(data, report, product, root / ".agents/skills/weekly-tech-brief/SKILL.md", evidence, root)
    return "研究覆盖记录结构与候选处置通过；隔离线索仍未确认，不认证零遗漏或人工记录真实性"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--product-graph", type=Path)
    parser.add_argument("--worklist", action="store_true", help="Read draft work cards; no publication certification")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--company")
    selection.add_argument("--candidate")
    args = parser.parse_args()
    if not args.worklist and (args.company or args.candidate):
        parser.error("--company/--candidate require --worklist")
    if not args.worklist and args.product_graph is None:
        parser.error("--product-graph is required for publication validation")
    try:
        if args.worklist:
            path = ROOT / "logs" / f"{report_day(args.report).isoformat()}_research_coverage.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            print(json.dumps(build_worklist(data, args.company, args.candidate, ROOT), ensure_ascii=False, indent=2))
            return
        print(check_coverage(args.report.resolve(), args.product_graph.resolve()))
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
        raise SystemExit(f"研究覆盖闸门失败：{exc}") from exc


if __name__ == "__main__":
    main()

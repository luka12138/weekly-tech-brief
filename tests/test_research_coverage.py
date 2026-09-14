from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_quality_gate
from test_weekly_brief_schema import valid_report
from validate_research_coverage import (
    CATEGORIES, REQUIRED_COMPANIES, build_worklist, digest,
    validate_coverage, validate_event_workflow,
)


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "reports").mkdir()
        (self.root / "logs").mkdir()
        self.report = self.root / "reports/2026-09-07_weekly_morning_brief.md"
        self.report.write_text(valid_report(), encoding="utf-8")
        self.product = self.root / "products.json"
        self.product.write_text(json.dumps({"companies": [
            {"name": c, "main_products": ["Core", "Other"]} for c in REQUIRED_COMPANIES]}))
        self.skill = self.root / "SKILL.md"
        self.skill.write_text("test skill")
        prior = self.root / "reports/2026-08-31_weekly_morning_brief.md"
        prior.write_text("Prior report, ongoing matters reviewed")
        self.evidence = {"report_sha256": digest(self.report), "claims": [
            {"id": "R1", "targets": ["company:Apple", "event:1"]}]}
        self.data = {"schema_version": 1, "report_date": "2026-09-07", "status": "ready",
            "cutoff_exclusive": "2026-09-07T00:00:00+08:00",
            "reviewed_at": "2026-09-08T01:00:00Z", "report_sha256": digest(self.report),
            "product_graph_sha256": digest(self.product), "skill_sha256": digest(self.skill),
            "prior_report": {"path": str(prior.relative_to(self.root)), "sha256": digest(prior), "note": "Reviewed prior matters"},
            "checks": [], "candidates": [], "watchlist": [], "company_conclusions": {}}
        for i, company in enumerate(REQUIRED_COMPANIES):
            for stage, hour, family in (("discovery", "01", "company"), ("regulatory", "02", "authority"), ("countercheck", "03", "media")):
                self.data["checks"].append({"id": f"{i}-{stage}", "company": company, "stage": stage,
                    "businesses": ["Core", "Other"], "categories": sorted(CATEGORIES),
                    "query_or_url": f"{company} dated news index", "entrypoint": f"{family}-index",
                    "source_family": family, "result_ref": f"tool-result-{i}-{stage}",
                    "checked_at": f"2026-09-07T{hour}:00:00Z", "status": "reviewed",
                    "note": f"Inspected {company} window entries; no candidates in fixture", "candidate_ids": []})
            self.data["company_conclusions"][company] = {"status": "no_company_specific_change", "note": "Window entries inspected"}

    def validate(self):
        validate_coverage(self.data, self.report, self.product, self.skill, self.evidence, self.root)

    def freeze_prior(self):
        prior = self.root / self.data["prior_report"]["path"]
        frozen = self.root / "archives/comparison/reports" / prior.name
        frozen.parent.mkdir(parents=True)
        frozen.write_bytes(prior.read_bytes())
        self.data["prior_report"]["frozen_path"] = str(frozen.relative_to(self.root))
        return prior, frozen

    def test_frozen_prior_preserves_review_when_display_changes(self):
        prior, _ = self.freeze_prior()
        prior.write_text("Other display version; not the reviewed version")
        self.validate()

    def test_frozen_prior_hash_cannot_be_rebound_silently(self):
        _, frozen = self.freeze_prior()
        frozen.write_text("Changed snapshot")
        with self.assertRaisesRegex(ValueError, "prior report review missing/stale"):
            self.validate()

    def test_frozen_prior_must_stay_in_archive(self):
        self.data["prior_report"]["frozen_path"] = self.data["prior_report"]["path"]
        with self.assertRaisesRegex(ValueError, "inside archives"):
            self.validate()

    def add_candidate(self):
        check = next(c for c in self.data["checks"] if c["company"] == "Apple" and c["stage"] == "regulatory")
        check["candidate_ids"] = ["C1"]
        candidate = {"id": "C1", "companies": ["Apple"], "discovered_by": [check["id"]],
            "summary": "New litigation stage", "materiality": "material", "materiality_reason": "Affects deployment conditions",
            "disposition": "included", "reason": "Dated filing verified", "claim_ids": ["R1"],
            "targets": ["company:Apple", "event:1"]}
        self.data["candidates"].append(candidate)
        self.data["company_conclusions"]["Apple"]["status"] = "events"
        return candidate

    def enable_workflow(self):
        self.data["workflow_version"] = 2
        (self.root / "logs/evidence.json").write_text(json.dumps(self.evidence))
        for candidate in self.data["candidates"]:
            candidate["research"] = {
                "event_key": f"case-stage-{candidate['id']}",
                "canonical_id": candidate["id"], "member_ids": [candidate["id"]],
                "identity_status": "identified",
                "materials": [{"path": "logs/evidence.json", "locator": "R1", "role": "source_review"}],
                "open_questions": [],
                "next_action": {"kind": "closed", "target": "R1", "question": "Dated claim bound in fixture"},
            }

    def add_alias(self):
        root = self.data["candidates"][0]
        alias = copy.deepcopy(root)
        alias.update(id="C2", disposition="excluded", exclusion_basis="duplicate",
                     decision_evidence="C1 includes C2's additional evidence in fixture")
        alias["research"].update(member_ids=["C2"], canonical_id="C1",
                                next_action={"kind": "follow_canonical", "target": "C1", "question": "Use C1 and preserve C2 evidence"})
        self.data["candidates"].append(alias)
        root["research"]["member_ids"].append("C2")
        next(c for c in self.data["checks"] if c["id"] == alias["discovered_by"][0])["candidate_ids"].append("C2")
        return alias

    def enable_selection(self):
        self.data["selection_policy"] = "company_top5"
        self.report.write_text(self.report.read_text() + "\n<!-- company-selection: top5 -->\n")
        self.data["report_sha256"] = self.evidence["report_sha256"] = digest(self.report)
        for company, conclusion in self.data["company_conclusions"].items():
            selected = [c["id"] for c in self.data["candidates"]
                        if company in c["companies"] and c["disposition"] == "included"]
            conclusion.update(status="events" if selected else "no_selected_update",
                              selected_candidate_ids=selected, selection_reason="Ranked by business impact",
                              legal_review="Independent dated coverage inspected; scope limited to fixture",
                              check_ids=[c["id"] for c in self.data["checks"]
                                         if c["company"] == company and c["stage"] != "regulatory"])

    def test_selection_does_not_require_all_businesses_or_three_rounds(self):
        self.add_candidate()
        self.enable_selection()
        for check in self.data["checks"]:
            check.update(businesses=["Core"], categories=["legal"])
            if check["stage"] == "regulatory":
                check["status"] = "blocked"
        self.validate()

    def test_selection_requires_official_and_independent_entries(self):
        self.add_candidate()
        self.enable_selection()
        conclusion = self.data["company_conclusions"]["Apple"]
        conclusion["check_ids"] = ["0-countercheck"]
        with self.assertRaisesRegex(ValueError, "official company channel"):
            self.validate()
        conclusion["check_ids"] = ["0-discovery"]
        with self.assertRaisesRegex(ValueError, "independent importance"):
            self.validate()

    def test_top5_report_cannot_fall_back_to_legacy_coverage(self):
        self.add_candidate()
        self.enable_selection()
        del self.data["selection_policy"]
        with self.assertRaisesRegex(ValueError, "cannot use legacy"):
            self.validate()

    def test_zero_selected_updates_does_not_require_filler_events(self):
        self.enable_selection()
        report = self.report.read_text()
        start, end = report.index("### 3.1 Apple"), report.index("### 3.2 无重大变化公司")
        report = report[:start] + report[end:]
        report = report.replace("- Microsoft、", "- Apple、Microsoft、")
        self.report.write_text(report)
        self.data["report_sha256"] = self.evidence["report_sha256"] = digest(self.report)
        self.evidence["claims"] = []
        self.validate()

    def test_selection_official_failure_needs_visible_limitation(self):
        self.add_candidate()
        self.enable_selection()
        self.data["checks"][0]["status"] = "blocked"
        with self.assertRaisesRegex(ValueError, "official access limitation"):
            self.validate()
        conclusion = self.data["company_conclusions"]["Apple"]
        conclusion.update(status="limited", limitation="Official index unavailable")
        with self.assertRaisesRegex(ValueError, "missing visible limitation"):
            self.validate()
        self.report.write_text(self.report.read_text().replace("| Apple | 重大变化", "| Apple | Official index unavailable"))
        self.data["report_sha256"] = self.evidence["report_sha256"] = digest(self.report)
        self.validate()

    def test_selection_does_not_require_unselected_work_or_watch_to_close(self):
        original = self.add_candidate()
        extra = copy.deepcopy(original)
        extra.update(id="C2", disposition="deferred", claim_ids=[], targets=[],
                     materiality="unresolved", reason="Outside the selected focus; not disproved",
                     decision_evidence="Recovered metadata only; lower priority than C1")
        self.data["candidates"].append(extra)
        self.data["checks"][1]["candidate_ids"].append("C2")
        self.enable_workflow()
        extra["research"].update(open_questions=["Scope remains unknown"],
                                 next_action={"kind": "fetch_gap", "target": "Future public filing",
                                              "question": "Resume only when new material appears"})
        self.data["watchlist"] = [{"id": "W1", "companies": ["Apple"], "status": "active",
                                  "topic": "Old matter", "note": "Not checked this week",
                                  "review_scope": "not_selected", "defer_reason": "No selected conclusion relies on it"}]
        self.enable_selection()
        self.validate()
        self.assertNotIn("C2", build_worklist(self.data)["companies"]["Apple"]["open"])
        extra["claim_ids"] = ["R1"]
        with self.assertRaisesRegex(ValueError, "deferred item leaked"):
            self.validate()

    def test_selection_does_not_certify_missing_claims_or_extra_events(self):
        candidate = self.add_candidate()
        self.enable_selection()
        candidate["claim_ids"] = []
        with self.assertRaisesRegex(ValueError, "claim_ids"):
            self.validate()
        candidate["claim_ids"] = ["R1"]
        candidate["targets"] = ["company:Apple"]
        with self.assertRaisesRegex(ValueError, "selected event missing"):
            self.validate()

    def test_selection_rejects_six_candidates_and_packed_events(self):
        candidate = self.add_candidate()
        for number in range(2, 7):
            extra = copy.deepcopy(candidate)
            extra["id"] = f"C{number}"
            self.data["candidates"].append(extra)
        self.enable_selection()
        with self.assertRaisesRegex(ValueError, "at most 5"):
            self.validate()
        self.data["candidates"] = self.data["candidates"][:2]
        self.data["company_conclusions"]["Apple"]["selected_candidate_ids"] = ["C1", "C2"]
        with self.assertRaisesRegex(ValueError, "cannot be packed"):
            self.validate()

    def test_future_production_requires_selection_as_well_as_work_cards(self):
        self.enable_workflow()
        future = self.root / "reports/2026-09-14_weekly_morning_brief.md"
        self.data.update(report_date="2026-09-14", cutoff_exclusive="2026-09-14T00:00:00+08:00")
        with self.assertRaisesRegex(ValueError, "company_top5 selection policy required"):
            validate_coverage(self.data, future, self.product, self.skill, self.evidence, self.root)

    def test_plan2_official_channel_cannot_be_replaced_by_media(self):
        self.enable_workflow()
        self.validate()
        self.data["checks"][0]["source_family"] = "media"
        with self.assertRaisesRegex(ValueError, "official company channel"):
            self.validate()

    def quarantine_candidate(self):
        candidate = self.add_candidate()
        self.enable_workflow()
        candidate.update(materiality="unresolved", disposition="quarantined", claim_ids=[], targets=[])
        candidate["research"].update(open_questions=["Public filing scope is unverified"],
                                    next_action={"kind": "fetch_gap", "target": "Public filing", "question": "Await a new accessible copy"})
        candidate["quarantine"] = {
            "known_material_event": False, "confirmed_scope": "Only a docket entry was recovered",
            "unconfirmed_scope": "Product scope remains unverified",
            "materiality_assessment": "Available metadata does not establish a material business event",
            "timing_limit": "Publication time of the alleged change remains unverified",
            "next_verification": "Read the filing when a lawful public copy becomes available",
            "reviewed_at": "2026-09-08T00:30:00Z", "source_urls": ["https://example.com/docket"]}
        self.data["unconfirmed_lead_policy"] = 1
        q = candidate["quarantine"]
        block = "\n<!-- quarantined-lead:C1 -->\n未确认；不计入当周事实、投资判断或图谱；不作为当时已知或回测输入\n"
        block += "\n".join(q[k] for k in ("confirmed_scope", "unconfirmed_scope", "materiality_assessment", "timing_limit", "next_verification"))
        block += "\nhttps://example.com/docket\n<!-- /quarantined-lead:C1 -->\n"
        self.report.write_text(self.report.read_text() + block)
        self.data["report_sha256"] = self.evidence["report_sha256"] = digest(self.report)
        return candidate

    def test_quarantined_lead_keeps_gap_visible_without_becoming_fact(self):
        self.quarantine_candidate()
        self.validate()

    def test_quarantine_requires_explicit_policy(self):
        self.quarantine_candidate()
        del self.data["unconfirmed_lead_policy"]
        with self.assertRaisesRegex(ValueError, "explicit unconfirmed lead policy"):
            self.validate()

    def test_known_material_event_cannot_be_quarantined(self):
        candidate = self.quarantine_candidate()
        candidate["materiality"] = "material"
        with self.assertRaisesRegex(ValueError, "known material"):
            self.validate()
        candidate["materiality"] = "unresolved"
        candidate["quarantine"]["known_material_event"] = True
        with self.assertRaisesRegex(ValueError, "confirmed material event"):
            self.validate()

    def test_quarantined_lead_cannot_bind_confirmed_targets(self):
        candidate = self.quarantine_candidate()
        candidate["claim_ids"] = ["R1"]
        with self.assertRaisesRegex(ValueError, "cannot support confirmed targets"):
            self.validate()
        candidate["claim_ids"] = []
        self.evidence["claims"][0]["candidate_id"] = "C1"
        with self.assertRaisesRegex(ValueError, "leaked into temporal claims"):
            self.validate()

    def test_quarantine_cannot_hide_the_gap_from_readers(self):
        self.quarantine_candidate()
        self.report.write_text(self.report.read_text().replace("Product scope remains unverified", ""))
        self.data["report_sha256"] = self.evidence["report_sha256"] = digest(self.report)
        with self.assertRaisesRegex(ValueError, "hides a verification gap"):
            self.validate()

    def test_quarantine_does_not_waive_company_coverage(self):
        self.quarantine_candidate()
        self.data["checks"] = [c for c in self.data["checks"] if c["stage"] != "countercheck"]
        with self.assertRaisesRegex(ValueError, "missing discovery/regulatory/countercheck"):
            self.validate()

    def test_quarantine_cannot_be_moved_outside_section_seven(self):
        self.quarantine_candidate()
        text = self.report.read_text()
        start = text.index("<!-- quarantined-lead:C1 -->")
        block = text[start:]
        text = text[:start].replace("## 3.", block + "\n## 3.", 1)
        self.report.write_text(text)
        self.data["report_sha256"] = self.evidence["report_sha256"] = digest(self.report)
        with self.assertRaisesRegex(ValueError, "section 7 appendix"):
            self.validate()

    def test_quarantine_requires_exactly_one_appendix_block(self):
        self.quarantine_candidate()
        text = self.report.read_text()
        block = text[text.index("<!-- quarantined-lead:C1 -->"):]
        self.report.write_text(text + block)
        self.data["report_sha256"] = self.evidence["report_sha256"] = digest(self.report)
        with self.assertRaisesRegex(ValueError, "one visible quarantine"):
            self.validate()

    def test_plan2_future_production_requires_work_cards(self):
        future = self.root / "reports/2026-09-14_weekly_morning_brief.md"
        self.data.update(report_date="2026-09-14", cutoff_exclusive="2026-09-14T00:00:00+08:00")
        with self.assertRaisesRegex(ValueError, "workflow_version:2"):
            validate_coverage(self.data, future, self.product, self.skill, self.evidence, self.root)

    def test_plan2_closed_cards_pass_without_copying_claims(self):
        self.add_candidate()
        self.enable_workflow()
        self.validate()

    def test_plan2_draft_questions_do_not_certify_publication(self):
        candidate = self.add_candidate()
        self.enable_workflow()
        candidate["disposition"] = "pending"
        candidate["research"]["open_questions"] = ["Which dated update introduced this scope?"]
        candidate["research"]["next_action"].update(kind="fetch_gap", target="Official dated update", question="Resolve publication time only")
        before = copy.deepcopy(self.data)
        result = build_worklist(self.data)
        self.assertFalse(result["publication_certified"])
        self.assertEqual(before, self.data)
        with self.assertRaisesRegex(ValueError, "unresolved work-card"):
            self.validate()

    def test_plan2_cannot_hide_pending_or_missing_recovery_pointer(self):
        candidate = self.add_candidate()
        self.enable_workflow()
        candidate["disposition"] = "pending"
        with self.assertRaisesRegex(ValueError, "actionable question"):
            build_worklist(self.data)
        candidate["disposition"] = "included"
        candidate["research"]["materials"][0]["locator"] = ""
        with self.assertRaisesRegex(ValueError, "material locator"):
            build_worklist(self.data)

    def test_plan2_alias_preserves_records_and_follows_one_root(self):
        self.add_candidate()
        self.enable_workflow()
        self.add_alias()
        self.validate()
        result = build_worklist(self.data, candidate_id="C2")
        self.assertEqual(result["canonical"]["id"], "C1")
        self.assertEqual(result["canonical"]["research"]["member_ids"], ["C1", "C2"])
        self.assertEqual(build_worklist(self.data)["aliases"], 1)

    def test_plan2_losing_alias_members_or_companies_fails(self):
        self.add_candidate()
        self.enable_workflow()
        alias = self.add_alias()
        self.data["candidates"][0]["research"]["member_ids"] = ["C1"]
        with self.assertRaisesRegex(ValueError, "all member IDs"):
            build_worklist(self.data)
        self.data["candidates"][0]["research"]["member_ids"].append("C2")
        alias["companies"].append("Microsoft")
        with self.assertRaisesRegex(ValueError, "affected company"):
            build_worklist(self.data)

    def test_plan2_distinct_stages_and_alias_cycles_rejected(self):
        self.add_candidate()
        self.enable_workflow()
        alias = self.add_alias()
        alias["research"]["event_key"] = "case-new-judgment-not-party-motion"
        with self.assertRaisesRegex(ValueError, "distinct events/stages"):
            build_worklist(self.data)
        alias["research"]["event_key"] = "case-stage-C1"
        root = self.data["candidates"][0]["research"]
        root.update(canonical_id="C2", next_action={"kind": "follow_canonical", "target": "C2", "question": "Invalid cycle"})
        with self.assertRaisesRegex(ValueError, "chain/cycle"):
            build_worklist(self.data)

    def test_plan2_split_required_until_distinct_events_are_separated(self):
        candidate = self.add_candidate()
        self.enable_workflow()
        candidate["research"].update(identity_status="needs_split", open_questions=["Separate government opinion and party motion"])
        candidate["research"]["next_action"].update(kind="split_candidate", target="C1 existing filings", question="Preserve distinct stages")
        validate_event_workflow(self.data)
        with self.assertRaisesRegex(ValueError, "mixed events"):
            self.validate()

    def test_plan2_alias_questions_must_be_transferred(self):
        self.add_candidate()
        self.enable_workflow()
        alias = self.add_alias()
        alias["research"]["open_questions"] = ["Unresolved new retention amount"]
        with self.assertRaisesRegex(ValueError, "transfer to canonical"):
            build_worklist(self.data)

    def test_plan2_same_root_key_or_untraceable_duplicate_rejected(self):
        candidate = self.add_candidate()
        self.enable_workflow()
        candidate.update(disposition="excluded", exclusion_basis="duplicate")
        with self.assertRaisesRegex(ValueError, "different canonical"):
            build_worklist(self.data)
        candidate["exclusion_basis"] = "outside_window"
        second = copy.deepcopy(candidate)
        second["id"] = "C2"
        second["research"].update(canonical_id="C2", member_ids=["C2"])
        self.data["candidates"].append(second)
        with self.assertRaisesRegex(ValueError, "duplicate root"):
            build_worklist(self.data)

    def test_plan2_worklist_rejects_unknown_filters(self):
        self.enable_workflow()
        for kwargs in ({"company": "Unknown"}, {"candidate_id": "missing"}):
            with self.assertRaisesRegex(ValueError, "unknown"):
                build_worklist(self.data, **kwargs)

    def test_plan2_worklist_distinguishes_absent_checks_from_passed_checks(self):
        self.enable_workflow()
        self.data["checks"] = [c for c in self.data["checks"] if c["company"] != "Apple"]
        del self.data["company_conclusions"]["Apple"]
        result = build_worklist(self.data, company="Apple")
        self.assertEqual(result["blocked_checks"], [])
        self.assertEqual(result["missing_stage_records"], ["countercheck", "discovery", "regulatory"])
        self.assertFalse(result["official_discovery_recorded_reviewed"])
        self.assertEqual(result["recorded_conclusion"], "not_recorded")

    def test_plan2_worklist_blocked_official_not_reported_reviewed(self):
        self.enable_workflow()
        self.data["checks"][0]["status"] = "blocked"
        company = build_worklist(self.data)["companies"]["Apple"]
        self.assertFalse(company["official_discovery_recorded_reviewed"])
        self.assertEqual(company["blocked_checks"], ["0-discovery"])
        self.assertEqual(company["missing_stage_records"], [])

    def test_plan2_receipt_ids_require_actual_payload_not_placeholders(self):
        candidate = self.add_candidate()
        self.enable_workflow()
        candidate["research"]["materials"] = [{"path": "logs/raw.json", "locator": "CL01",
                                               "role": "receipt", "record_ids": ["CL01"]}]
        path = self.root / "logs/raw.json"
        path.write_text(json.dumps({"records": [{"id": "CL1"}]}))
        with self.assertRaisesRegex(ValueError, "unknown/duplicate"):
            build_worklist(self.data, root=self.root)
        for result in (None, "", "  ", {}, [], 123):
            path.write_text(json.dumps({"records": [{"id": "CL01", "result": result}]}))
            with self.assertRaisesRegex(ValueError, "no actual tool result"):
                build_worklist(self.data, root=self.root)
        path.write_text(json.dumps({"records": [{"id": "CL01", "result": "Original body with date and restrictions"}]}))
        self.assertFalse(build_worklist(self.data, root=self.root)["publication_certified"])

    def test_plan2_worklist_missing_material_file_blocks_recovery(self):
        self.add_candidate()
        self.enable_workflow()
        (self.root / "logs/evidence.json").unlink()
        with self.assertRaisesRegex(ValueError, "material file missing"):
            build_worklist(self.data, root=self.root)

    def test_complete_zero_candidate_record_valid_without_news_quota(self):
        self.validate()

    def test_business_gap_not_covered_by_query_mention(self):
        self.data["checks"][0]["businesses"] = ["Core"]
        with self.assertRaisesRegex(ValueError, "main business"):
            self.validate()

    def test_category_gap(self):
        for c in self.data["checks"]:
            c["categories"].remove("governance")
        with self.assertRaisesRegex(ValueError, "event category"):
            self.validate()

    def test_missing_independent_regulatory_or_reverse_pass(self):
        original = copy.deepcopy(self.data)
        for stage in ("regulatory", "countercheck"):
            self.data = copy.deepcopy(original)
            self.data["checks"] = [c for c in self.data["checks"] if c["stage"] != stage]
            with self.assertRaisesRegex(ValueError, "missing discovery"):
                self.validate()

    def test_same_entrypoint_is_not_reverse_check(self):
        self.data["checks"][2]["entrypoint"] = "company-index"
        with self.assertRaisesRegex(ValueError, "different authority/media"):
            self.validate()

    def test_company_release_is_not_independent_regulatory_check(self):
        self.data["checks"][1]["source_family"] = "company"
        with self.assertRaisesRegex(ValueError, "regulatory check"):
            self.validate()

    def test_blocked_output_and_missing_receipt_fail(self):
        for field, value in (("status", "blocked"), ("result_ref", "")):
            original = self.data["checks"][0][field]
            self.data["checks"][0][field] = value
            with self.assertRaises(ValueError):
                self.validate()
            self.data["checks"][0][field] = original

    def test_material_candidate_must_be_closed_and_in_details(self):
        candidate = self.add_candidate()
        self.validate()
        candidate["disposition"] = "pending"
        with self.assertRaisesRegex(ValueError, "pending candidate"):
            self.validate()
        candidate["disposition"] = "included"
        candidate["targets"] = ["company:Apple"]
        with self.assertRaisesRegex(ValueError, "company details"):
            self.validate()

    def test_headline_limit_or_unsupported_not_material_exclusion(self):
        candidate = self.add_candidate()
        candidate["disposition"] = "excluded"
        candidate["decision_evidence"] = "source reference"
        for basis in ("headline_full", "unsupported", "not_material"):
            candidate["exclusion_basis"] = basis
            with self.assertRaises(ValueError):
                self.validate()

    def test_false_no_change_and_dangling_claim_fail(self):
        candidate = self.add_candidate()
        self.data["company_conclusions"]["Apple"]["status"] = "no_company_specific_change"
        with self.assertRaisesRegex(ValueError, "no-change"):
            self.validate()
        self.data["company_conclusions"]["Apple"]["status"] = "events"
        candidate["claim_ids"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "unknown/duplicate"):
            self.validate()

    def test_active_watchlist_cannot_disappear(self):
        (self.root / "logs/2026-08-31_research_coverage.json").write_text(json.dumps({"watchlist": [{"id": "case-A", "status": "active"}]}))
        with self.assertRaisesRegex(ValueError, "ongoing matters disappeared"):
            self.validate()

    def test_changed_inputs_and_draft_block(self):
        for key in ("report_sha256", "product_graph_sha256", "skill_sha256"):
            old = self.data[key]
            self.data[key] = "stale"
            with self.assertRaisesRegex(ValueError, "stale"):
                self.validate()
            self.data[key] = old
        self.data["status"] = "draft"
        with self.assertRaisesRegex(ValueError, "draft/unresolved"):
            self.validate()

    def test_real_gate_blocks_before_point_in_time_and_side_effects(self):
        argv = ["gate", "--report", str(self.report)]
        with patch.object(sys, "argv", argv), patch.object(run_quality_gate, "ROOT", self.root), \
             patch.object(run_quality_gate, "preflight_report"), patch.object(run_quality_gate, "check_point_in_time") as temporal, \
             patch.object(run_quality_gate, "run") as run, redirect_stdout(StringIO()), \
             self.assertRaisesRegex(SystemExit, "missing research closure"):
            run_quality_gate.main()
        temporal.assert_not_called()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

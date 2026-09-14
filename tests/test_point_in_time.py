from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from validate_point_in_time import (  # noqa: E402
    REVIEW_SCOPES, check_report, collect_targets, digest, validate_evidence,
)


class PointInTimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "reports").mkdir()
        (self.root / "logs").mkdir()
        self.report = self.root / "reports/2026-09-07_weekly_morning_brief.md"
        self.baseline = self.root / "baseline.json"
        self.product = self.root / "product.json"
        self.report.write_text("""# Test
<!-- point-in-time-policy: 1 -->
## 1. 本周最重要的 10 件事
1. New release [source](https://example.com/release)
Continued text
## 2. 投资判断速览
| 公司 | 本周变化 |
| --- | --- |
| Apple | Release |
## 3. 发生变化的公司
### 3.1 Apple
- 日期：2026-09-02
- 事件：New release
- 来源：[source](https://example.com/release)
### 3.2 无重大变化公司
- Other companies: none found
## 4. 跨公司与产业链判断
1. Analysis
## 5. 下周催化与验证条件
1. Forecast
## 6. 研究附录：产业链与图谱
""", encoding="utf-8")
        self.baseline.write_text(json.dumps({"edges": [{"edge_id": "E01", "changed_this_week": "new", "evidence_date": "2026-09-02"}]}))
        self.product.write_text("{}")
        self.data = {
            "schema_version": 1, "report_date": "2026-09-07",
            "cutoff_exclusive": "2026-09-07T00:00:00+08:00",
            "report_sha256": digest(self.report), "baseline_sha256": digest(self.baseline),
            "product_graph_sha256": digest(self.product),
            "report_created_at": "2026-09-07T08:00:00+08:00",
            "reviewed_at": "2026-09-07T09:00:00+08:00",
            "manual_reviews": {key: {"status": "reviewed", "note": "Specific fixture review"} for key in REVIEW_SCOPES},
            "claims": [{
                "id": "F01", "statement": "Release announced", "kind": "news",
                "targets": list(collect_targets(self.report.read_text(), json.loads(self.baseline.read_text()))),
                "evidence": [{
                    "url": "https://example.com/release",
                    "claim_first_public_at": "2026-09-02T12:00:00+08:00",
                    "retrieved_at": "2026-09-07T08:30:00+08:00",
                    "basis": "dated_release", "locator": "Dateline and paragraph 1",
                    "support": "The dated release announces this event.",
                }],
            }],
        }

    def validate(self, data=None):
        validate_evidence(data or self.data, self.report, self.baseline, self.product)

    def test_declared_day_end_bound_is_not_an_instant(self):
        source = self.data["claims"][0]["evidence"][0]
        source["claim_first_public_at"] = "2026-09-02T23:59:59-07:00"
        source["support"] = "以当地当日最晚时刻保守判断，不宣称实际23:59提交。"
        with self.assertRaisesRegex(ValueError, "day-end bound"):
            self.validate()

    def test_draft_evidence_is_not_certified_even_with_complete_fields(self):
        self.data["status"] = "draft"
        with self.assertRaisesRegex(ValueError, "draft/unresolved"):
            self.validate()

    def test_genuine_second_precision_is_not_rejected_by_clock_value_alone(self):
        self.data["claims"][0]["evidence"][0]["claim_first_public_at"] = "2026-09-02T23:59:59-07:00"
        self.validate()

    def test_inventory_can_be_saved_without_exporting_full_context(self):
        import subprocess
        output = self.root / "inventory.json"
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/validate_point_in_time.py"),
                   "--report", str(self.report), "--baseline", str(self.baseline), "--inventory",
                   "--inventory-output", str(output)]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        inventory = json.loads(output.read_text())
        self.assertEqual(json.loads(result.stdout)["targets"], len(inventory))
        self.assertIn("event:1", inventory)
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_next_event_metadata_does_not_attach_to_previous_target(self):
        text = """## 3. Events
### 3.1 Apple
- 日期：2026-09-01
- 事件：First
<!-- candidates: C2; claims: C2-1 -->
- 日期：2026-09-02
- 事件：Second
<!-- multiline
claims: C3-1
-->
"""
        targets = collect_targets(text, {})
        self.assertEqual(targets["event:1"], "- 日期：2026-09-01\n- 事件：First")
        self.assertEqual(targets["event:2"], "- 日期：2026-09-02\n- 事件：Second")

    def use_interval(self, day="2026-09-03"):
        from datetime import date, datetime, time, timedelta, timezone
        source = self.data["claims"][0]["evidence"][0]
        source.pop("claim_first_public_at", None)
        midnight = datetime.combine(date.fromisoformat(day), time.min, timezone.utc)
        source["claim_first_public_interval"] = {
            "published_date": day,
            "earliest": (midnight - timedelta(hours=14)).isoformat(),
            "latest_exclusive": (midnight + timedelta(days=1, hours=12)).isoformat(),
            "timezone_basis": "global_utc_minus12_to_plus14",
            "version_locator": "Dated release paragraph; no later inserted claim",
            "note": "Date only; timezone unknown; endpoints are bounds, not publication instants.",
        }
        return source

    def test_midweek_date_only_interval_passes(self):
        self.use_interval()
        self.validate()

    def test_interval_at_week_boundary_is_not_current_week(self):
        for day in ("2026-08-30", "2026-08-31", "2026-09-06", "2026-09-07"):
            with self.subTest(day=day):
                self.use_interval(day)
                with self.assertRaises(ValueError):
                    self.validate()

    def test_interval_cannot_be_narrowed_or_shifted(self):
        for field, value in (("earliest", "2026-09-03T00:00:00Z"),
                             ("latest_exclusive", "2026-09-04T00:00:00Z")):
            source = self.use_interval()
            source["claim_first_public_interval"][field] = value
            with self.assertRaisesRegex(ValueError, "full global timezone bounds"):
                self.validate()

    def test_interval_requires_version_and_uncertainty_details(self):
        for field in ("version_locator", "note", "published_date", "timezone_basis"):
            source = self.use_interval()
            del source["claim_first_public_interval"][field]
            with self.assertRaises(ValueError):
                self.validate()

    def test_interval_cannot_be_combined_with_invented_instant(self):
        source = self.use_interval()
        source["claim_first_public_at"] = "2026-09-03T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.validate()

    def test_interval_retains_late_page_update_barrier(self):
        source = self.use_interval()
        source["page_modified_at"] = "2026-09-07T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "later page update"):
            self.validate()

    def test_interval_must_finish_before_retrieval(self):
        source = self.use_interval()
        source["retrieved_at"] = "2026-09-03T12:00:00Z"
        with self.assertRaisesRegex(ValueError, "chronology"):
            self.validate()

    def test_undated_or_malformed_interval_fails(self):
        for value in (None, [], "2026-09-03", {}, {"timezone_basis": "UTC"}):
            source = self.use_interval()
            source["claim_first_public_interval"] = value
            with self.assertRaises(ValueError):
                self.validate()

    def test_valid_evidence_and_complete_inventory(self):
        self.validate()
        targets = collect_targets(self.report.read_text(), json.loads(self.baseline.read_text()))
        self.assertEqual(set(targets), {"headline:1", "company:Apple", "event:1", "analysis:1", "catalyst:1", "supply:E01"})
        self.assertIn("Continued text", targets["headline:1"])
        self.assertNotIn("Other companies", targets["event:1"])

    def test_legacy_dates_are_context_not_new_disclosure(self):
        data = json.loads(self.baseline.read_text())
        data["edges"].extend([
            {"edge_id": "E02", "changed_this_week": "no_new_weekly_evidence", "evidence_date": "long_term_baseline"},
            {"edge_id": "E03", "changed_this_week": "no_new_weekly_evidence", "evidence_date": "2026-07-24/2026-07-29"},
        ])
        self.baseline.write_text(json.dumps(data))
        self.data["baseline_sha256"] = digest(self.baseline)
        self.validate()
        data["edges"][2]["evidence_date"] = "2026-07-24/2026-09-07"
        self.baseline.write_text(json.dumps(data))
        self.data["baseline_sha256"] = digest(self.baseline)
        with self.assertRaisesRegex(ValueError, "evidence_date exceeds"):
            self.validate()

    def test_new_edges_cannot_use_missing_legacy_or_old_dates(self):
        for value in (None, "long_term_baseline", "2026-07-29", "2026-09-01/2026-09-02", "unknown"):
            with self.subTest(value=value):
                self.baseline.write_text(json.dumps({"edges": [{
                    "edge_id": "E01", "changed_this_week": "new", "evidence_date": value,
                }]}))
                self.data["baseline_sha256"] = digest(self.baseline)
                with self.assertRaisesRegex(ValueError, "evidence_date"):
                    self.validate()

    def test_unrecognized_legacy_date_does_not_silently_pass(self):
        data = json.loads(self.baseline.read_text())
        data["edges"].append({"edge_id": "E02", "changed_this_week": "no_new_weekly_evidence", "evidence_date": "unknown"})
        self.baseline.write_text(json.dumps(data))
        self.data["baseline_sha256"] = digest(self.baseline)
        with self.assertRaisesRegex(ValueError, "invalid evidence_date"):
            self.validate()

    def test_zero_headline_statement_still_needs_review(self):
        targets = collect_targets("## 1. 本周重大事件\n本周未发现可确认重大事件。\n## 2. 投资判断速览", {"edges": []})
        self.assertEqual(set(targets), {"headline:none"})

    def test_main_validator_cannot_skip_temporal_gate(self):
        from validate_weekly_brief import validate_report
        from contextlib import redirect_stderr
        from io import StringIO
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            validate_report(self.report, self.baseline, self.root / "latest.md", product_graph_path=self.product)

    def test_quality_gate_rejects_missing_evidence_before_side_effects(self):
        import run_quality_gate
        args = ["run_quality_gate.py", "--report", str(self.report), "--baseline", str(self.baseline)]
        with patch.object(sys, "argv", args), patch.object(run_quality_gate, "build_graph_plan") as plan, \
             patch.object(run_quality_gate, "check_coverage", return_value="coverage fixture"), \
             patch.object(run_quality_gate, "run") as run, patch.object(run_quality_gate, "preflight_report") as preflight:
            with self.assertRaisesRegex(SystemExit, "missing temporal evidence"):
                run_quality_gate.main()
        preflight.assert_called_once_with(self.report.resolve(), self.baseline)
        plan.assert_not_called()
        run.assert_not_called()

    def test_monday_shanghai_cutoff_is_exclusive(self):
        for instant in ("2026-09-06T20:00:00-04:00", "2026-09-06T16:00:00Z", "2026-09-07T08:00:00+08:00"):
            with self.subTest(instant=instant):
                data = copy.deepcopy(self.data)
                data["claims"][0]["evidence"][0]["claim_first_public_at"] = instant
                with self.assertRaisesRegex(ValueError, "at/after cutoff"):
                    self.validate(data)

    def test_last_instant_before_cutoff_is_allowed(self):
        self.data["claims"][0]["evidence"][0]["claim_first_public_at"] = "2026-09-06T23:59:59.999999+08:00"
        self.validate()

    def test_old_aws_announcement_cannot_be_new_news(self):
        self.data["claims"][0]["evidence"][0]["claim_first_public_at"] = "2025-11-03T13:58:02Z"
        with self.assertRaisesRegex(ValueError, "old announcement"):
            self.validate()

    def test_old_background_is_allowed_but_not_changed_supply(self):
        claim = self.data["claims"][0]
        claim["kind"] = "background"
        claim["evidence"][0]["claim_first_public_at"] = "2025-11-03T13:58:02Z"
        with self.assertRaisesRegex(ValueError, "changed supply"):
            self.validate()
        self.baseline.write_text('{"edges": []}')
        self.data["baseline_sha256"] = digest(self.baseline)
        claim["targets"].remove("supply:E01")
        self.validate()

    def test_future_schedule_is_not_realized_fact(self):
        forecast = copy.deepcopy(self.data["claims"][0])
        forecast.update(id="F02", targets=["catalyst:1"], event_at="2028-01-01T12:00:00+08:00")
        self.data["claims"].append(forecast)
        with self.assertRaisesRegex(ValueError, "future occurrence"):
            self.validate()
        forecast["kind"] = "forecast"
        self.validate()

    def test_later_page_update_requires_dated_section(self):
        evidence = self.data["claims"][0]["evidence"][0]
        evidence["page_modified_at"] = "2026-09-07T08:00:00+08:00"
        with self.assertRaisesRegex(ValueError, "later page update"):
            self.validate()
        evidence["basis"] = "dated_section"
        evidence["locator"] = "September 2 update, excluding September 7 addition"
        self.validate()

    def test_missing_or_naive_publication_time_fails(self):
        for value in (None, "", "2026-09-02", "2026-09-02T12:00:00"):
            with self.subTest(value=value):
                self.data["claims"][0]["evidence"][0]["claim_first_public_at"] = value
                with self.assertRaises(ValueError):
                    self.validate()

    def test_http_status_is_not_a_publication_basis(self):
        self.data["claims"][0]["evidence"][0]["basis"] = "http_200"
        with self.assertRaisesRegex(ValueError, "basis"):
            self.validate()

    def test_empty_evidence_or_omitted_target_fails(self):
        data = copy.deepcopy(self.data)
        data["claims"][0]["evidence"] = []
        with self.assertRaisesRegex(ValueError, "no dated evidence"):
            self.validate(data)
        self.data["claims"][0]["targets"].remove("headline:1")
        with self.assertRaisesRegex(ValueError, "unreviewed report targets"):
            self.validate()

    def test_unknown_and_duplicate_claims_fail(self):
        data = copy.deepcopy(self.data)
        data["claims"][0]["targets"] = ["headline:999"]
        with self.assertRaisesRegex(ValueError, "target"):
            self.validate(data)
        self.data["claims"].append(copy.deepcopy(self.data["claims"][0]))
        with self.assertRaisesRegex(ValueError, "duplicated"):
            self.validate()

    def test_all_three_input_hashes_are_bound(self):
        for field in ("report_sha256", "baseline_sha256", "product_graph_sha256"):
            with self.subTest(field=field):
                data = copy.deepcopy(self.data)
                data[field] = "0" * 64
                with self.assertRaisesRegex(ValueError, "stale evidence"):
                    self.validate(data)

    def test_unresolved_financial_review_fails(self):
        self.data["manual_reviews"]["financial_periods_and_units"]["status"] = "unknown"
        with self.assertRaisesRegex(ValueError, "financial_periods_and_units"):
            self.validate()

    def test_required_review_text_cannot_be_null_or_blank(self):
        for field in ("note", "statement", "locator", "support"):
            for value in (None, " ", {}, False):
                with self.subTest(field=field, value=value):
                    data = copy.deepcopy(self.data)
                    if field == "note":
                        data["manual_reviews"]["source_versions"][field] = value
                    elif field == "statement":
                        data["claims"][0][field] = value
                    else:
                        data["claims"][0]["evidence"][0][field] = value
                    with self.assertRaises(ValueError):
                        self.validate(data)

    def test_retrieval_cannot_be_after_review(self):
        self.data["claims"][0]["evidence"][0]["retrieved_at"] = "2026-09-08T10:00:00+08:00"
        with self.assertRaisesRegex(ValueError, "chronology"):
            self.validate()

    def test_explicit_event_and_supply_dates_cannot_exceed_cutoff(self):
        self.report.write_text(self.report.read_text().replace("日期：2026-09-02", "日期：2026-09-07"))
        self.data["report_sha256"] = digest(self.report)
        with self.assertRaisesRegex(ValueError, "declared disclosure date"):
            self.validate()

    def test_future_supply_evidence_date_fails(self):
        self.baseline.write_text(self.baseline.read_text().replace("2026-09-02", "2026-09-07"))
        self.data["baseline_sha256"] = digest(self.baseline)
        with self.assertRaisesRegex(ValueError, "evidence_date"):
            self.validate()

    def test_legacy_is_unverified_not_passed(self):
        with self.assertRaisesRegex(ValueError, "missing temporal evidence"):
            check_report(self.report, self.baseline, self.product)
        self.report.write_text(self.report.read_text().replace("<!-- point-in-time-policy: 1 -->", ""))
        self.assertIn("legacy_unverified", check_report(self.report, self.baseline, self.product))
        newer = self.report.with_name("2026-09-14_weekly_morning_brief.md")
        newer.write_text(self.report.read_text())
        with self.assertRaisesRegex(ValueError, "missing temporal evidence"):
            check_report(newer, self.baseline, self.product)

    def test_standalone_requires_product_and_checks_manifest(self):
        evidence = self.root / "logs/2026-09-07_temporal_evidence.json"
        evidence.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(ValueError, "product graph"):
            check_report(self.report, self.baseline)
        self.assertIn("校验通过", check_report(self.report, self.baseline, self.product))


if __name__ == "__main__":
    unittest.main()

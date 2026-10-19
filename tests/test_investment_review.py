from __future__ import annotations

import copy
import json
import math
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from investment_review import (  # noqa: E402
    COMPANIES, MARKER, POLICY, POLICY_REGISTERED_AT, calculate_market, check_report,
    digest, html_view, markdown, selection_digest, timestamp, validate_snapshot,
)
from validate_point_in_time import collect_targets  # noqa: E402


class InvestmentReviewTests(unittest.TestCase):
    def setUp(self):
        clock = patch("investment_review.utc_now", return_value=timestamp("2026-10-12T12:00:00Z"))
        clock.start()
        self.addCleanup(clock.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "logs").mkdir()
        (self.root / "reports").mkdir()
        self.coverage = {
            "report_date": "2026-10-12", "selection_policy": "company_top5",
            "company_conclusions": {c: {"selected_candidate_ids": ["C1"] if c == "Apple" else []} for c in COMPANIES},
            "candidates": [{"id": "C1", "companies": ["Apple"], "claim_ids": ["CL1"], "targets": ["event:1", "company:Apple"]}],
            "report_sha256": "final report not yet bound",
        }
        self.coverage_path = self.root / "logs/2026-10-12_research_coverage.json"
        self.save(self.coverage_path, self.coverage)
        self.data = {
            "schema_version": 1, "kind": "production", "report_date": "2026-10-12",
            "cutoff": "2026-10-12T00:00:00+08:00", "generated_at": "2026-10-12T09:00:00+08:00",
            "policy_registered_at": POLICY_REGISTERED_AT, "policy": copy.deepcopy(POLICY),
            "coverage": {"path": "logs/2026-10-12_research_coverage.json", "selection_sha256": selection_digest(self.coverage)},
            "sources": {}, "companies": [
                {"company": c, "selected_candidate_ids": ["C1"] if c == "Apple" else [],
                 "market_status": "unavailable", "market_source": None, "limitation": "No verified market series; not zero.",
                 "associations": [], "hypothesis": None} for c in COMPANIES
            ],
        }

    def save(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def source(self, name, raw):
        path = self.root / "logs" / f"{name}.json"
        self.save(path, raw)
        self.data["sources"][name] = {
            "path": str(path.relative_to(self.root)), "sha256": digest(path), "url": "https://example.com/frozen-test-fixture",
            "availability": {"claim_first_public_at": "2026-10-10T01:00:00Z"}, "retrieved_at": "2026-10-12T00:00:00Z",
            "version": "TEST ONLY", "locator": "synthetic fixture, not market evidence", "availability_basis": "synthetic test",
        }
        return path

    def market(self):
        days = []
        day = datetime(2026, 8, 31, 20, tzinfo=timezone.utc)
        while day < timestamp(self.data["cutoff"]):
            if day.weekday() < 5:
                days.append({"close_at": day.isoformat(), "stock_return": .01, "benchmark_return": .005})
            day += timedelta(days=1)
        raw = {"instrument": {"symbol": "TEST", "venue": "TEST", "currency": "USD", "benchmark": "TEST_BENCH", "calendar": "synthetic_weekdays", "price_basis": "total_return_asof_cutoff"}, "sessions": days}
        self.source("M1", raw)
        self.data["companies"][0].update(market_status="verified", market_source="M1")
        return raw

    def check(self):
        return validate_snapshot(self.data, self.root)

    def test_source_url_does_not_absorb_adjacent_chinese_metadata(self):
        from validate_weekly_brief import extract_markdown_urls
        self.source("N1", {"body": "test fixture"})
        text = markdown(self.data, self.check(), "test-hash")
        self.assertEqual(extract_markdown_urls(text), {self.data["sources"]["N1"]["url"]})

    def test_missing_is_not_zero_and_all_companies_retained(self):
        result = self.check()
        self.assertEqual(list(result), list(COMPANIES))
        self.assertTrue(all(x is None for x in result.values()))
        rendered = markdown(self.data, result, "hash")
        self.assertIn("待接入 / 样本不足", rendered)
        self.assertNotIn("+0.00%", rendered)

    def test_formula_compounding_and_excess(self):
        self.market()
        m = self.check()["Apple"]
        self.assertEqual(m["sessions"], 5)
        self.assertAlmostEqual(m["week_return"], 1.01 ** 5 - 1)
        self.assertAlmostEqual(m["excess_return"], 1.01 ** 5 - 1.005 ** 5)
        self.assertAlmostEqual(m["rv20"], 0)
        self.assertAlmostEqual(m["week_shock"], math.log1p(.01) * math.sqrt(252))

    def test_old_shock_exit_is_not_new_news_effect(self):
        raw = self.market()
        raw["sessions"][-24]["stock_return"] = .5
        self.source("M1", raw)
        self.assertLess(self.check()["Apple"]["rv20_change"], 0)

    def test_short_window_stays_missing(self):
        raw = self.market()
        raw["sessions"] = raw["sessions"][-4:]
        self.source("M1", raw)
        self.assertIsNone(self.check()["Apple"]["rv20"])

    def test_future_source_rejected(self):
        self.market()
        self.data["sources"]["M1"]["availability"]["claim_first_public_at"] = self.data["cutoff"]
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.check()

    def test_future_market_observation_rejected(self):
        raw = self.market()
        raw["sessions"][-1]["close_at"] = self.data["cutoff"]
        self.source("M1", raw)
        with self.assertRaisesRegex(ValueError, "observation"):
            self.check()

    def test_hash_change_rejected(self):
        raw = self.market()
        self.save(self.root / "logs/M1.json", {**raw, "future": True})
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.check()

    def test_future_adjusted_and_invalid_returns_rejected(self):
        raw = self.market()
        for value in (True, float("nan"), float("inf"), -1):
            bad = copy.deepcopy(raw)
            bad["sessions"][0]["stock_return"] = value
            self.source("M1", bad)
            with self.assertRaises(ValueError):
                self.check()
        raw["instrument"]["price_basis"] = "latest_adjusted"
        self.source("M1", raw)
        with self.assertRaisesRegex(ValueError, "adjusted"):
            self.check()

    def test_interval_cannot_claim_session_reaction(self):
        self.market()
        self.source("N1", {"body": "test news"})
        self.data["sources"]["N1"]["availability"] = {"claim_first_public_interval": {
            "published_date": "2026-10-07", "timezone_basis": "global_utc_minus12_to_plus14",
            "earliest": "2026-10-06T10:00:00Z", "latest_exclusive": "2026-10-08T12:00:00Z",
            "version_locator": "test fixture", "note": "unknown timezone, full interval",
        }}
        self.data["companies"][0]["associations"] = [{
            "candidate_id": "C1", "precision": "interval", "publication_start": "2026-10-06T10:00:00Z",
            "publication_end": "2026-10-08T12:00:00Z", "resolution": "session", "source_ids": ["N1"],
            "interpretation": "not causal", "alternatives": "other explanations",
        }]
        with self.assertRaisesRegex(ValueError, "date interval"):
            self.check()
        self.data["companies"][0]["associations"][0]["resolution"] = "weekly"
        self.check()
        self.data["companies"][0]["associations"][0]["publication_end"] = "2026-10-08T11:00:00Z"
        with self.assertRaisesRegex(ValueError, "match cited source"):
            self.check()

    def test_future_generation_rejected(self):
        self.data["generated_at"] = "2026-10-13T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "generation time"):
            self.check()

    def test_policy_backdating_or_tuning_rejected(self):
        self.data["policy"]["return_sessions"] = 10
        with self.assertRaisesRegex(ValueError, "policy differs"):
            self.check()
        self.data["policy"] = copy.deepcopy(POLICY)
        self.data["policy_registered_at"] = "2026-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "backdated"):
            self.check()

    def test_outcomes_and_unknown_fields_rejected(self):
        self.data["realized_next_week_return"] = .2
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.check()

    def test_removed_company_or_extra_event_rejected(self):
        removed = self.data["companies"].pop()
        with self.assertRaisesRegex(ValueError, "12 companies"):
            self.check()
        self.data["companies"].append(removed)
        self.data["companies"][0]["selected_candidate_ids"] = ["C2"]
        with self.assertRaisesRegex(ValueError, "differs from coverage"):
            self.check()

    def test_no_circular_hash_but_selection_changes_rejected(self):
        self.coverage["report_sha256"] = "new final rendered body hash"
        self.save(self.coverage_path, self.coverage)
        self.check()
        self.coverage["company_conclusions"]["Apple"]["selected_candidate_ids"] = []
        self.save(self.coverage_path, self.coverage)
        with self.assertRaisesRegex(ValueError, "selection hash"):
            self.check()

    def test_preview_not_publishable(self):
        self.data.update(kind="design_preview", coverage=None)
        self.data["companies"][0]["selected_candidate_ids"] = []
        validate_snapshot(self.data, self.root, allow_preview=True)
        with self.assertRaisesRegex(ValueError, "cannot be published"):
            self.check()

    def test_report_binding_and_old_report_compatibility(self):
        old = self.root / "reports/2026-10-05_weekly_morning_brief.md"
        old.write_text("historical report", encoding="utf-8")
        self.assertIn("旧期", check_report(old))
        report = self.root / "reports/2026-10-12_weekly_morning_brief.md"
        report.write_text("no module", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "marker"):
            check_report(report)
        snapshot = self.root / "logs/2026-10-12_investment_review.json"
        self.save(snapshot, self.data)
        content = MARKER + "\n" + markdown(self.data, self.check(), digest(snapshot)) + "\n## 1. 本周重大事件\n"
        report.write_text(content, encoding="utf-8")
        check_report(report)
        report.write_text(content.replace("待接入 / 样本不足", "+0.00%", 1), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differs from frozen"):
            check_report(report)

    def test_html_escapes_content_and_contains_same_figures(self):
        self.market()
        self.data["companies"][0]["limitation"] = "<script>alert(1)</script>"
        metrics = self.check()
        page = html_view(self.data, metrics, "hash")
        self.assertIn("+5.10%", page)
        self.assertIn("+5.10%", markdown(self.data, metrics, "hash"))
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("default-src 'none'", page)

    def test_hypothesis_requires_verifiable_expectation_and_falsifier(self):
        h = {
            "id": "H1", "candidate_ids": ["C1"], "direction": "up", "volatility": "uncertain",
            "expectation_kind": "research_assumption", "expectation": "Analyst hypothesis, not consensus",
            "source_ids": [], "transmission": "Test-only mechanism", "financial_scale": "Unknown; missing margin data",
            "realization_horizon": "Next fiscal year", "falsification": "Order cancellation", "alternatives": "Sector demand",
        }
        self.data["companies"][0]["hypothesis"] = h
        self.check()
        h["expectation_kind"] = "consensus"
        with self.assertRaisesRegex(ValueError, "sources"):
            self.check()
        h["expectation_kind"] = "unpriced"
        with self.assertRaisesRegex(ValueError, "not an observable"):
            self.check()
        h["expectation_kind"] = "research_assumption"
        h["falsification"] = ""
        with self.assertRaisesRegex(ValueError, "missing text"):
            self.check()

    def test_extra_independent_event_in_hypothesis_rejected(self):
        self.data["companies"][0]["selected_candidate_ids"] = [f"C{i}" for i in range(6)]
        with self.assertRaisesRegex(ValueError, "exceeds five"):
            self.check()

    def test_new_block_does_not_overwrite_original_temporal_targets(self):
        body = MARKER + "\n" + markdown(self.data, self.check(), "hash")
        body += "\n## 1. 本周重大事件\n本周未发现可确认重大事件。\n"
        body += "## 2. 投资判断速览\n| 公司 | 判断 |\n| Apple | ORIGINAL_EVIDENCE |\n"
        targets = collect_targets(body, {"edges": []})
        self.assertEqual(targets["company:Apple"], "| Apple | ORIGINAL_EVIDENCE |")
        self.assertEqual(set(targets), {"headline:none", "company:Apple"})

    def test_duplicate_or_unsorted_sessions_rejected(self):
        raw = self.market()
        raw["sessions"][-1] = raw["sessions"][-2]
        self.source("M1", raw)
        with self.assertRaisesRegex(ValueError, "unique and ascending"):
            self.check()

    def observed_market(self):
        dates = []
        d = datetime(2026, 8, 31, tzinfo=timezone.utc)
        while d < timestamp(self.data['cutoff']):
            if d.weekday() < 5:
                dates.append(d.date().isoformat())
            d += timedelta(days=1)
        closes = [100*1.01**i for i in range(len(dates))]
        benches = [200*1.005**i for i in range(len(dates))]
        def receipt(name, method, codes, fields, values, args):
            path = self.root/'logs'/f'{name}.json'
            self.save(path, {'request': {'method': method, 'args': args},
                             'result': {'ErrorCode': 0, 'Codes': codes, 'Fields': fields, 'Times': dates, 'Data': values}})
            return {'path': str(path.relative_to(self.root)), 'sha256': digest(path)}
        options = 'PriceAdj=U;TradingCalendar=TEST;Currency=USD'
        args = ['TEST', 'close', dates[0], dates[-1], options]
        stock = receipt('stock', 'wsd', ['TEST'], ['CLOSE'], [closes], args)
        bench = receipt('bench', 'wsd', ['BENCH'], ['CLOSE'], [benches], args)
        cal = receipt('calendar', 'tdays', [None], [None], [dates], [dates[0], dates[-1], 'TradingCalendar=TEST'])
        sid = receipt('stock_identity', 'wss', ['TEST'], ['SEC_NAME'], [['Synthetic Corp']], [])
        bid = receipt('bench_identity', 'wss', ['BENCH'], ['SEC_NAME'], [['Synthetic Index']], [])
        raw = {'instrument': {'symbol': 'TEST', 'venue': 'TEST', 'currency': 'USD', 'benchmark': 'BENCH', 'calendar': 'TEST', 'price_basis': 'unadjusted_close_price_return'},
               'session_dates': dates, 'closes': closes, 'benchmark_closes': benches,
               'provenance': {'stock': stock, 'benchmark': bench, 'calendar': cal, 'stock_identity': sid, 'benchmark_identity': bid}}
        path = self.root/'logs/observed.json';self.save(path, raw)
        self.data.update(schema_version=2, observations={'O1': {'path': 'logs/observed.json', 'sha256': digest(path),
                         'url': 'https://example.com/synthetic-test-only', 'retrieved_at': '2026-10-12T00:00:00Z',
                         'version': 'Synthetic current read, after cutoff', 'locator': 'synthetic fixture', 'limitation': 'not PIT'}})
        self.data['companies'][0].update(market_status='observed', market_source='O1')
        return raw

    def save_observed(self, raw):
        path = self.root/'logs/observed.json';self.save(path, raw)
        self.data['observations']['O1']['sha256'] = digest(path)

    def test_observed_prices_display_metrics_without_pit_promotion(self):
        self.observed_market()
        metrics = self.check();m = metrics['Apple']
        self.assertAlmostEqual(m['week_return'], 1.01**5-1)
        self.assertAlmostEqual(m['excess_return'], 1.01**5-1.005**5)
        self.assertIsNotNone(m['rv20_change'])
        self.assertFalse(m['pit_qualified'])
        page = markdown(self.data, metrics, 'hash')
        self.assertIn('TEST / USD / Synthetic Index（BENCH）', page)
        self.assertIn('历史PIT未认证', page)
        self.assertIn('价格回报', page)
        self.assertIn('+5.10%', page)
        self.assertNotIn('样本不足', page)

    def test_observed_raw_tamper_and_missing_session_rejected(self):
        raw = self.observed_market();raw['closes'][2] *= 2;self.save_observed(raw)
        with self.assertRaisesRegex(ValueError, 'differs from raw'):
            self.check()
        raw = self.observed_market();cal = self.root/raw['provenance']['calendar']['path']
        altered = json.loads(cal.read_text());altered['result']['Times'].pop();self.save(cal, altered)
        raw['provenance']['calendar']['sha256'] = digest(cal);self.save_observed(raw)
        with self.assertRaisesRegex(ValueError, 'calendar'):
            self.check()

    def test_observed_missing_benchmark_preserves_stock_metrics(self):
        raw = self.observed_market();raw['benchmark_closes'] = [None]*len(raw['closes'])
        raw['provenance'].update(benchmark=None, benchmark_identity=None);self.save_observed(raw)
        metrics = self.check();m = metrics['Apple']
        self.assertIsNotNone(m['week_return']);self.assertIsNotNone(m['rv20'])
        self.assertIsNone(m['excess_return'])
        self.assertIn('基准数据缺失', markdown(self.data, metrics, 'hash'))

    def test_observed_cannot_be_used_as_qualified_source(self):
        self.observed_market();self.data['companies'][0]['market_status'] = 'verified'
        with self.assertRaisesRegex(ValueError, 'frozen source'):
            self.check()

    def test_observed_future_and_nonfinite_data_rejected(self):
        raw = self.observed_market();raw['session_dates'][-1] = '2026-10-12';self.save_observed(raw)
        with self.assertRaisesRegex(ValueError, 'future'):
            self.check()
        raw = self.observed_market();raw['closes'][-1] = None;self.save_observed(raw)
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            self.check()

    def test_private_company_is_not_sample_insufficiency(self):
        self.data.update(schema_version=2, observations={})
        self.data['companies'][7]['market_status'] = 'not_mapped'
        page = markdown(self.data, self.check(), 'hash')
        self.assertIn('不适用：未建立直接证券映射', page)

    def test_taiwan_cannot_use_the_other_tse_calendar(self):
        raw = self.observed_market();raw['instrument'].update(venue='TWSE', calendar='TSE');self.save_observed(raw)
        with self.assertRaisesRegex(ValueError, 'different market calendar'):
            self.check()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from historical_snapshot_overrides import apply_data_overrides, apply_text_overrides  # noqa: E402
from audit_sources import check_claims  # noqa: E402
from migrate_historical_briefs_v2 import expectation_gap, impact_metric, validation_condition  # noqa: E402
from rebuild_historical_source_audits import (  # noqa: E402
    can_reuse_claim_cache,
    can_reuse_source_cache,
)


class HistoricalRebuildTests(unittest.TestCase):
    def test_documented_override_corrects_samsung_trial(self) -> None:
        old = (
            "Samsung 与 KDDI 官方宣布商用 5G 网络部署。 "
            "https://news.samsung.com/global/"
            "samsung-and-kddi-successfully-deploy-ai-powered-network-optimization-solution-on-commercial-5g-network"
        )
        corrected = apply_text_overrides("2026-07-06", old)
        self.assertIn("完成商用 5G SA 网络优化试验", corrected)
        self.assertIn("successfully-complete-ai-powered-network-optimization-trial", corrected)
        payload = apply_data_overrides("2026-07-06", {"status": "new_commercial_deployment"})
        self.assertEqual(payload["status"], "new_commercial_network_trial")

    def test_http_404_never_uses_source_cache(self) -> None:
        live = {"status": 404, "reachable": False, "error": None}
        cached = {"status": 200, "reachable": True}
        self.assertFalse(can_reuse_source_cache(live, cached, True))

    def test_transport_error_can_use_exact_source_cache(self) -> None:
        live = {"status": None, "reachable": False, "error": "URLError: DNS"}
        cached = {"status": 200, "reachable": True}
        self.assertTrue(can_reuse_source_cache(live, cached, True))
        self.assertFalse(can_reuse_source_cache(live, cached, False))

    def test_claim_cache_requires_transient_failure_on_its_source(self) -> None:
        claim = {"source_urls": ["https://example.com/source"]}
        cached = {"matched": True}
        unrelated_failure = {
            "https://example.com/other": {"live_probe_error": "timeout"},
            "https://example.com/source": {"status": 200},
        }
        related_failure = {
            "https://example.com/source": {"live_probe_error": "timeout"},
        }
        self.assertFalse(can_reuse_claim_cache(claim, unrelated_failure, cached, True))
        self.assertTrue(can_reuse_claim_cache(claim, related_failure, cached, True))

    def test_claim_check_refreshes_text_before_failing(self) -> None:
        claims = [
            {
                "claim_id": "E1",
                "source_urls": ["https://example.com/source"],
                "keywords": ["alpha", "beta"],
                "min_keyword_matches": 2,
            }
        ]
        audited = [
            {
                "url": "https://example.com/source",
                "status": 200,
                "access_limited": False,
            }
        ]
        with patch("audit_sources.fetch_text", side_effect=["", "alpha beta"]):
            result = check_claims(claims, audited, timeout=1)

        self.assertTrue(result[0]["matched"])
        self.assertTrue(result[0]["url_results"][0]["text_fetch_retried"])
        self.assertFalse(result[0]["url_results"][0]["text_fetch_failed"])

    def test_claim_check_does_not_hide_persistent_keyword_mismatch(self) -> None:
        claims = [
            {
                "claim_id": "E1",
                "source_urls": ["https://example.com/source"],
                "keywords": ["alpha", "beta"],
                "min_keyword_matches": 2,
            }
        ]
        audited = [
            {
                "url": "https://example.com/source",
                "status": 200,
                "access_limited": False,
            }
        ]
        with patch("audit_sources.fetch_text", side_effect=["unrelated", "still unrelated"]):
            result = check_claims(claims, audited, timeout=1)

        self.assertTrue(result[0]["failed"])
        self.assertEqual(result[0]["best_match_count"], 0)

    def test_software_api_event_uses_adoption_metrics(self) -> None:
        text = "Computer Use、Skills API 和 Files API 正式 GA，并新增 browser use 与 1 TB 文件存储。"
        self.assertEqual(
            impact_metric(text, "Anthropic"),
            "活跃用户、API 调用量、付费转化与推理成本",
        )
        self.assertIn("活跃使用", validation_condition(text, "Anthropic"))

    def test_shareholder_return_event_uses_cash_return_metrics(self) -> None:
        text = "董事会批准股份回购并全部注销，同时提高股东回报目标。"
        self.assertEqual(
            impact_metric(text, "SK Hynix"),
            "自由现金流、回购执行、每股指标与股东回报率",
        )
        self.assertIn("回购完成量", validation_condition(text, "SK Hynix"))

    def test_low_latency_is_not_misclassified_as_a_delay(self) -> None:
        text = "企业级 SSD 量产，面向需要低延迟的 AI 服务器。"
        self.assertNotIn("负面", expectation_gap(text, "已确认"))
        self.assertIn("负面", expectation_gap("项目宣布延期并下调指引", "已确认"))

    def test_limitation_language_does_not_override_event_type(self) -> None:
        student_event = "推出 Student Rewards 和云额度，属于长期生态投资，不是本期云收入。"
        self.assertEqual(
            impact_metric(student_event, "Amazon / AWS"),
            "开发者新增、活跃使用、云消耗与付费转化",
        )
        display_event = "发布折叠屏显示技术，不应误写为 HBM 或 DRAM 供应关系。"
        self.assertEqual(
            impact_metric(display_event, "Samsung Electronics"),
            "产品出货量、ASP、毛利率与客户采用",
        )

    def test_regulatory_and_revenue_synonyms_use_matching_validation(self) -> None:
        self.assertIn("监管决定", validation_condition("欧盟 DMA 合规条款调整", "Apple"))
        revenue_event = "7 月合并营收同比增长 44.7%。"
        self.assertEqual(
            impact_metric(revenue_event, "TSMC"),
            "收入增速、营业利润率、订单与指引",
        )

    def test_domain_terms_do_not_cross_match(self) -> None:
        hbm_event = "HBM4 已量产出货，并通过约 10 家客户样品认证。"
        self.assertEqual(
            impact_metric(hbm_event, "SK Hynix"),
            "出货量、ASP、良率与产能利用率",
        )
        username_event = "WhatsApp 用户名正式推出，新联系人无需暴露手机号。"
        self.assertEqual(
            impact_metric(username_event, "Meta"),
            "活跃用户、API 调用量、付费转化与推理成本",
        )
        pixel_event = "发布 Pixel 11 系列与 Pixel Watch 5，并集成 Gemini。"
        self.assertEqual(
            impact_metric(pixel_event, "Alphabet / Google"),
            "产品出货量、ASP、毛利率与客户采用",
        )

    def test_contextual_terms_do_not_override_primary_product(self) -> None:
        guardduty_event = "AWS 发布 GuardDuty AI Protection，检测 Bedrock 成本消耗攻击。"
        self.assertEqual(
            impact_metric(guardduty_event, "Amazon / AWS"),
            "活跃用户、API 调用量、付费转化与推理成本",
        )
        regulated_model_event = "Microsoft 与 Mistral 面向受监管行业提供 frontier AI。"
        self.assertEqual(
            impact_metric(regulated_model_event, "Microsoft"),
            "活跃用户、API 调用量、付费转化与推理成本",
        )
        eu_terms_event = "Apple 调整欧盟 App Store、替代支付和替代分发条款。"
        self.assertEqual(
            impact_metric(eu_terms_event, "Apple"),
            "合规成本、产品可用性与收入风险",
        )


if __name__ == "__main__":
    unittest.main()

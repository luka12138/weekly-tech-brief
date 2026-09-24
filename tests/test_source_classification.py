import sys
import unittest
import ssl
import subprocess
import urllib.error
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_sources import classify_host, probe_url


class SourceClassificationTests(unittest.TestCase):
    def test_regulators_and_stakeholders_stay_distinct(self):
        for host in ("ftc.gov", "www.nhtsa.gov", "www.justice.gov"):
            self.assertEqual(classify_host(host), "official_or_regulatory")
        self.assertEqual(classify_host("www.newsmediaalliance.org"), "industry_association_statement")
        self.assertEqual(classify_host("www.macrumors.com"), "trade_or_press_media")

    def test_lookalike_domains_are_not_trusted(self):
        for host in ("ftc.gov.example.com", "fakenhtsa.gov", "justice.gov.example.com", "newsmediaalliance.org.example.com"):
            self.assertEqual(classify_host(host), "unclassified")

    def test_current_week_official_channels_and_reuters_republisher(self):
        for host in ("leginfo.legislature.ca.gov", "www.gov.ca.gov", "www.d-matrix.ai", "www.fortum.com", "www.googlecloudpresscorner.com"):
            self.assertEqual(classify_host(host), "official_or_regulatory")
            self.assertEqual(classify_host(host + ".example.com"), "unclassified")
        self.assertEqual(classify_host("www.investing.com"), "trade_or_press_media")

    def test_used_regulators_publishers_and_distributors(self):
        for host in ('ec.europa.eu', 'curia.europa.eu', 'english.motir.go.kr', 'mn8.com'):
            self.assertEqual(classify_host(host), 'official_or_regulatory')
        self.assertEqual(classify_host('www.cna.com.tw'), 'tier1_media')
        for host in ('electrek.co', 'globalnews.ca', 'iclg.com', 'news.cision.com', 'tech.yahoo.com', 'www.law360.com', 'www.nasdaq.com'):
            self.assertEqual(classify_host(host), 'trade_or_press_media')
        self.assertEqual(classify_host('ec.europa.eu.example.com'), 'unclassified')

    @patch('audit_sources.time.sleep')
    @patch('audit_sources.urllib.request.urlopen', side_effect=urllib.error.URLError(ssl.SSLError('TLS EOF')))
    @patch('audit_sources.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '200', ''))
    def test_tls_fallback_keeps_original_failure(self, run, urlopen, sleep):
        result = probe_url('https://ec.europa.eu/example.pdf', 2)
        self.assertTrue(result['reachable'])
        self.assertEqual(result['status'], 200)
        self.assertIn('TLS EOF', result['prior_transport_error'])
        run.assert_called_once()

    @patch('audit_sources.time.sleep')
    @patch('audit_sources.urllib.request.urlopen', side_effect=urllib.error.URLError(ssl.SSLError('TLS EOF')))
    @patch('audit_sources.subprocess.run', return_value=subprocess.CompletedProcess([], 60, '000', 'SSL error'))
    def test_failed_tls_fallback_is_not_reachable(self, run, urlopen, sleep):
        self.assertFalse(probe_url('https://ec.europa.eu/example.pdf', 2)['reachable'])

    @patch('audit_sources.urllib.request.urlopen', side_effect=urllib.error.HTTPError('https://example.com', 403, 'Forbidden', {}, None))
    @patch('audit_sources.subprocess.run')
    def test_http_denial_never_uses_fallback(self, run, urlopen):
        result = probe_url('https://example.com', 2)
        self.assertTrue(result['access_limited'])
        run.assert_not_called()

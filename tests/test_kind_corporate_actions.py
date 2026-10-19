from pathlib import Path
import sys
import unittest
import hashlib
import json
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from kind_corporate_actions import parse_list, selected_document, filing_url, cash_ex_notice, verified_saved_response, download, curl_response
from market_metric_windows import metric_windows, action_gap_impact, qualify_metrics


class KindTests(unittest.TestCase):
    def test_curl_checks_tls_and_posts_exact_form(self):
        from types import SimpleNamespace
        def run(cmd, **kwargs):
            self.assertNotIn('--insecure', cmd)
            self.assertNotIn('-k', cmd)
            self.assertNotIn('--location', cmd)
            self.assertEqual(cmd[cmd.index('--proto')+1], '=https')
            self.assertEqual(cmd[cmd.index('--data')+1], 'repIsuSrtCd=A005930')
            Path(cmd[cmd.index('--output')+1]).write_bytes(b'actual body')
            return SimpleNamespace(returncode=0, stdout='200\nhttps://kind.krx.co.kr/test', stderr='')
        with patch('kind_corporate_actions.subprocess.run', side_effect=run):
            self.assertEqual(curl_response('https://kind.krx.co.kr/test', {'repIsuSrtCd':'A005930'})[0], b'actual body')

    def test_curl_failure_or_redirect_never_becomes_empty_success(self):
        from types import SimpleNamespace
        for result in [SimpleNamespace(returncode=35, stdout='', stderr='TLS error'),
                       SimpleNamespace(returncode=0, stdout='302\nhttps://kind.krx.co.kr/test', stderr='')]:
            with patch('kind_corporate_actions.subprocess.run', return_value=result):
                with self.assertRaises((ValueError, OSError)): curl_response('https://kind.krx.co.kr/test')
        with patch('kind_corporate_actions.subprocess.run') as network:
            with self.assertRaises(ValueError): curl_response('http://kind.krx.co.kr/test')
            with self.assertRaises(ValueError): curl_response('https://example.com/test')
            network.assert_not_called()

    def listing(self, total=1, row=True):
        return ("<table>" + ("<tr><td>1</td><td>2026-09-28 15:52</td>"
            "<td><a onclick=\"companysummary_open('00593')\">삼성전자</a></td>"
            "<td><a onclick=\"openDisclsViewer('20260928000389','')\">배당락 안내</a></td>"
            "<td>유가증권시장본부</td></tr>" if row else '') +
            f"</table>전체 <em>{total}</em>건 : <strong>1</strong>/1")

    def test_list_missing_rows_or_wrong_issuer_rejected(self):
        valid = self.listing()
        args = ('005930', '2026-08-01', '2026-10-18', 1)
        self.assertEqual(len(parse_list(valid, *args)['entries']), 1)
        for bad in [self.listing(2), self.listing(row=False), valid.replace("00593", "00066"),
                    valid.replace('2026-09-28', '2026-10-19'), '<html>login</html>']:
            with self.assertRaises(ValueError): parse_list(bad, *args)

    def test_empty_response_is_not_no_corporate_actions(self):
        result = parse_list(self.listing(0, False) + '조회된 결과값이 없습니다.',
                            '005930', '2026-08-01', '2026-10-18', 1)
        self.assertEqual(result['reported_total'], 0)
        self.assertFalse(result['complete_corporate_action_ledger'])

    def test_selected_viewer_identity_and_external_host(self):
        self.assertEqual(selected_document("[삼성전자]<option value='123|Y'selected=\"selected\">", '삼성전자'), '123')
        with self.assertRaises(ValueError): selected_document("[SK하이닉스]<option value='123|Y'selected=>", '삼성전자')
        with self.assertRaises(ValueError): filing_url("parent.setPath('','https://example.com/external/x')")

    def test_saved_wrong_request_and_modified_body_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'capture.body'; p.write_bytes(b'original')
            receipt = {'http_status': 200, 'url': 'https://kind.krx.co.kr/test?a=1', 'params': {'code':'005930'},
                       'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'retrieved_at': '2026-10-19T00:00:00Z'}
            p.with_suffix('.receipt.json').write_text(json.dumps(receipt))
            self.assertEqual(verified_saved_response(p, receipt['url'], receipt['params'])[0], b'original')
            with self.assertRaises(ValueError): verified_saved_response(p, receipt['url'], {'code': '000660'})
            p.write_bytes(b'changed')
            with self.assertRaises(ValueError): verified_saved_response(p, receipt['url'], receipt['params'])

    def test_offline_missing_cache_never_calls_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch('kind_corporate_actions.urlopen') as network:
            out = Path(tmp) / 'out'
            with self.assertRaisesRegex(ValueError, 'Offline replay missing'):
                download('005930', '2026-08-01', '2026-10-18', out, offline=True)
            network.assert_not_called()
            self.assertEqual(json.loads((out / 'manifest.json').read_text())['status'], 'failed')

    def test_unchanged_reference_price_is_not_zero_dividend(self):
        html = '중간(분기)배당락 기준가격 안내<table>' + ''.join(
            '<tr>' + ''.join('<td>'+v+'</td>' for v in row) + '</tr>' for row in [
                ['1. 회사명', '삼성전자'], ['보통주식', '270,000'],
                ['3. 사유', '중간(분기)배당락(기준가격 변동없음)'], ['4. 적용일', '2026-09-29']]) + '</table>'
        event = cash_ex_notice(html.encode(), '005930')
        self.assertEqual(event['ex_date'], '2026-09-29')
        self.assertEqual(event['exchange_reference_price'], '270000')
        self.assertIsNone(event['cash_amount_declared_per_share'])
        with self.assertRaises(ValueError): cash_ex_notice(html.encode(), '000660')


class MetricWindowTests(unittest.TestCase):
    def test_missing_benchmark_does_not_block_stock_metrics(self):
        days = ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09',
                '2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16']
        windows = metric_windows(days, '2026-10-19', rv_sessions=3)
        evidence = {metric: {key: True for key in ['cash_action_coverage', 'noncash_action_coverage',
                    'cash_reinvestment_convention', 'historical_price_version', 'historical_action_version']}
                    for metric in ['week_return', 'excess_return', 'rv20', 'rv20_change']}
        result = qualify_metrics(windows, evidence)
        self.assertTrue(result['week_return']['strict_PIT_eligible'])
        self.assertTrue(result['rv20']['strict_PIT_eligible'])
        self.assertFalse(result['excess_return']['strict_PIT_eligible'])
        # Known earlier action gap remains in prior RV, not current week/RV.
        result = qualify_metrics(windows, evidence, [{'id': 'earlier_dividend', 'ex_date': '2026-10-09'}])
        self.assertTrue(result['week_return']['strict_PIT_eligible'])
        self.assertTrue(result['rv20']['strict_PIT_eligible'])
        self.assertFalse(result['rv20_change']['strict_PIT_eligible'])
        self.assertFalse(qualify_metrics(windows, {})['week_return']['current_version_method_eligible'])

    def test_previous_close_cash_not_recounted_and_gap_scoped(self):
        dates = ['2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02',
                 '2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09',
                 '2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16']
        windows = metric_windows(dates, '2026-10-19', rv_sessions=6)
        impact = action_gap_impact(windows, '2026-10-09')
        self.assertFalse(impact['week_return']['this_gap_affects_metric'])
        self.assertTrue(impact['rv20']['this_gap_affects_metric'])
        self.assertEqual(windows['week_return']['price_dates'][0], '2026-10-09')
        self.assertFalse(impact['week_return']['other_action_coverage_certified'])
        self.assertTrue(action_gap_impact(windows)['week_return']['this_gap_affects_metric'])

    def test_missing_samples_and_future_or_duplicate_dates_rejected(self):
        windows = metric_windows(['2026-10-09', '2026-10-12'], '2026-10-19')
        self.assertEqual(windows['rv20']['status'], 'insufficient_samples')
        self.assertIsNone(action_gap_impact(windows)['rv20']['this_gap_affects_metric'])
        for days in [['2026-10-09', '2026-10-12', '2026-10-19'], ['2026-10-09', '2026-10-12', '2026-10-12']]:
            with self.assertRaises(ValueError): metric_windows(days, '2026-10-19')


if __name__ == '__main__': unittest.main()

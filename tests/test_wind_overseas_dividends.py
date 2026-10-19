import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from wind_overseas_dividends import plan, inspect, corroborate


class OverseasDividendTests(unittest.TestCase):
    def receipt(self):
        return {'request': plan(['META.O', 'AMZN.O'], '2026-10-19', ['2026-06-30'])[0],
                'result': {'ErrorCode': 0, 'Codes': ['META.O', 'AMZN.O'],
                           'Fields': ['DIV_CASHBFTAX', 'DIV_EXDATE'],
                           'Times': ['2026-10-19T14:48:35'],
                           'Data': [[0.525, None], ['2026-09-21T00:00:00', None]]}}

    def inspect(self, receipt=None):
        return inspect(receipt or self.receipt(), {'META.O': 'USD', 'AMZN.O': 'USD'},
                       '2026-08-17', '2026-10-16')

    def event(self):
        return {'instrument': 'META.O', 'event_id': 'example', 'currency': 'USD',
                'ex_date': '2026-09-21', 'cash_amount_declared_per_share': '0.525'}

    def test_report_period_and_response_time_are_not_exdates(self):
        rows = self.inspect()
        self.assertEqual(rows[0]['report_period'], '2026-06-30')
        self.assertEqual(rows[0]['ex_date'], '2026-09-21')
        self.assertTrue(rows[0]['inside_effective_window'])
        self.assertFalse(rows[0]['historical_PIT_certified'])

    def test_empty_success_remains_unknown(self):
        row = self.inspect()[1]
        self.assertEqual(row['status'], 'empty_success')
        self.assertIsNone(row['reported_implemented_cash'])
        self.assertIsNone(row['ex_date'])
        self.assertFalse(row['complete_action_coverage'])

    def test_matched_cash_and_date_does_not_certify_complete_history(self):
        result = corroborate(self.inspect(), self.event())
        self.assertTrue(result['cash_amount_confirmed_by_wind'])
        self.assertEqual(result['matched_report_periods'], ['2026-06-30'])
        self.assertFalse(result['complete_action_coverage'])
        self.assertFalse(result['historical_PIT_certified'])

    def test_matching_cash_on_wrong_date_is_not_corroboration(self):
        event = self.event(); event['ex_date'] = '2026-09-22'
        self.assertFalse(corroborate(self.inspect(), event)['cash_amount_confirmed_by_wind'])

    def test_null_event_amount_cannot_be_corroborated(self):
        event = self.event(); event['cash_amount_declared_per_share'] = None
        with self.assertRaisesRegex(ValueError, 'positive'): corroborate(self.inspect(), event)

    def test_conflict_wins_even_if_one_other_version_matches(self):
        rows = self.inspect(); conflict = copy.deepcopy(rows[0])
        conflict['reported_implemented_cash'] = '0.52'; rows.append(conflict)
        result = corroborate(rows, self.event())
        self.assertEqual(result['status'], 'conflict')
        self.assertFalse(result['cash_amount_confirmed_by_wind'])
        event = self.event(); event['currency'] = 'TWD'
        self.assertEqual(corroborate(self.inspect(), event)['conflicts'], ['currency_mismatch'])

    def test_bad_matrix_identity_and_nonfinite_are_rejected(self):
        for key, value in [('Codes', ['AMZN.O', 'META.O']), ('Data', [[0.525], [None]]),
                           ('Data', [[float('nan'), None], [None, None]]), ('ErrorCode', -1)]:
            r = self.receipt(); r['result'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.inspect(r)

    def test_only_verified_currency_parameter_is_accepted(self):
        r = self.receipt(); r['request']['args'][2] = 'rptDate=20260630;currencyType=CNY;'
        with self.assertRaises(ValueError): self.inspect(r)

    def test_bounded_explicit_period_plan_does_not_claim_event_coverage(self):
        self.assertEqual(len(plan(['META.O'], '2026-10-19', ['2025-12-31', '2026-06-30'])), 2)
        for periods in [['2026-12-31'], ['2020-12-31'], ['2026-06-30'] * 2]:
            with self.assertRaises(ValueError): plan(['META.O'], '2026-10-19', periods)


if __name__ == '__main__': unittest.main()

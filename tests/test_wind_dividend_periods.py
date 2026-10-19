from pathlib import Path
import copy
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from wind_dividend_periods import plan, inspect, corroborate


class PeriodDividendTests(unittest.TestCase):
    def receipt(self):
        return {'request': plan('META.O', '2026-10-19'), 'result': {
            'ErrorCode': 0, 'Codes': ['META.O'],
            'Fields': ['DIV_CASHBEFORETAX', 'DIV_CASHBEFORETAX2', 'DIV_EXDATE'],
            'Times': ['2026-06-30', '2026-09-30'],
            'Data': [[None, None], [None, None], [20260921, None]]}}

    def test_period_outside_lookback_retains_event_inside_it(self):
        result = inspect(self.receipt(), 'META.O', '2026-08-17', '2026-10-16')
        self.assertEqual(result['rows'][0]['report_period'], '2026-06-30')
        self.assertEqual(result['observed_ex_dates_in_window'], ['2026-09-21'])
        self.assertFalse(result['rows'][0]['cash_event_eligible'])
        self.assertIsNone(result['rows'][0]['reported_implemented_cash'])
        proof = corroborate(result, {'instrument': 'META.O', 'ex_date': '2026-09-21', 'event_id': 'test'})
        self.assertTrue(proof['wind_ex_date_confirmed'])
        self.assertFalse(proof['cash_amount_confirmed_by_wind'])

    def test_period_amount_never_becomes_daily_cash(self):
        r = self.receipt(); r['result']['Data'][0][0] = 1.5
        r['result']['Data'][1][0] = 2.0
        row = inspect(r, 'META.O', '2026-08-17', '2026-10-16')['rows'][0]
        self.assertEqual(row['reported_implemented_cash'], '1.5')
        self.assertFalse(row['cash_event_eligible'])

    def test_zero_announced_is_retained_but_not_no_dividends(self):
        r = self.receipt(); r['result']['Data'] = [[None, None], [0, None], [None, None]]
        result = inspect(r, 'META.O', '2026-08-17', '2026-10-16')
        self.assertEqual(result['rows'][0]['reported_announced_cash'], '0')
        self.assertFalse(result['complete_action_coverage'])
        self.assertIsNone(result['rows'][0]['inside_effective_window'])

    def test_future_action_and_old_action_kept_outside_window(self):
        r = self.receipt(); r['result']['Data'][2] = [20260801, 20261101]
        result = inspect(r, 'META.O', '2026-08-17', '2026-10-16')
        self.assertEqual(result['observed_ex_dates_in_window'], [])
        self.assertEqual(len(result['rows']), 2)

    def test_bad_identity_matrix_period_and_nonfinite_fail(self):
        base = self.receipt()
        for key, value in [('Codes', ['AAPL.O']), ('Times', ['2026-06-30']*2),
                           ('Data', [[None], [None], [None]]), ('Data', [[float('nan'), None], [None, None], [20260921, None]])]:
            r = copy.deepcopy(base); r['result'][key] = value
            with self.assertRaises(ValueError): inspect(r, 'META.O', '2026-08-17', '2026-10-16')
        r = self.receipt(); r['result']['Times'][1] = '2026-10-19'
        with self.assertRaises(ValueError): inspect(r, 'META.O', '2026-08-17', '2026-10-16')
        r['request']['args'][3] = '2026-10-19'
        with self.assertRaises(ValueError): inspect(r, 'META.O', '2026-08-17', '2026-10-16')

    def test_plan_is_bounded_and_does_not_request_current_week(self):
        self.assertEqual(plan('META.O', '2026-10-19')['args'][2:4], ['2025-12-01', '2026-10-16'])
        with self.assertRaises(ValueError): plan('META.O', '2026-10-20')
        with self.assertRaises(ValueError): plan('META.O', '2026-10-19', '2020-01-01')


if __name__ == '__main__': unittest.main()

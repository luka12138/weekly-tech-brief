import sys
import unittest
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from return_conventions import cash_comparison, weekly_benchmark_comparison


class ReturnConventionTests(unittest.TestCase):
    def test_cash_reinvestment_matches_holdings_wealth_not_reference_adjustment(self):
        result = cash_comparison(100, 103, 1)
        shares = Decimal(1) + Decimal(1)/Decimal(103)
        wealth_return = shares * Decimal(103)/Decimal(100)-1
        self.assertAlmostEqual(float(result['ex_close_reinvestment_return']), float(wealth_return))
        self.assertNotEqual(result['ex_close_reinvestment_return'], result['ex_reference_adjustment_return'])
        self.assertFalse(result['complete_total_return_certified'])

    def test_actual_zero_is_not_unknown(self):
        result = cash_comparison(100, 103, 0)
        self.assertEqual(Decimal(result['difference_basis_points']), 0)
        for cash in [None, True, 'NaN', -1, 100]:
            with self.assertRaises(ValueError): cash_comparison(100, 103, cash)

    def test_weekly_uses_prior_close_and_does_not_mix_price_and_total(self):
        dates = ['2026-10-08', '2026-10-09', '2026-10-12', '2026-10-16']
        r = weekly_benchmark_comparison(dates, [70, 100, 105, 110], dates, [140, 200, 211, 222], '2026-10-19')
        self.assertEqual(Decimal(r['price_index_return']), Decimal('.1'))
        self.assertEqual(Decimal(r['provider_total_return']), Decimal('.11'))
        self.assertEqual(Decimal(r['total_minus_price_basis_points']), 100)
        self.assertEqual(r['price_start'], '2026-10-09')
        self.assertFalse(r['historical_PIT_certified'])

    def test_mismatched_future_nonfinite_and_missing_prior_inputs_rejected(self):
        dates = ['2026-10-09', '2026-10-16']
        for total_dates, values in [(dates[::-1], [100, 101]), (dates, [100, 'NaN']), (dates, [101])]:
            with self.assertRaises(ValueError):
                weekly_benchmark_comparison(dates, [100, 101], total_dates, values, '2026-10-19')
        for ds in [['2026-10-16', '2026-10-19'], ['2026-10-12', '2026-10-16']]:
            with self.assertRaises(ValueError): weekly_benchmark_comparison(ds, [100, 101], ds, [100, 101], '2026-10-19')


if __name__ == '__main__': unittest.main()

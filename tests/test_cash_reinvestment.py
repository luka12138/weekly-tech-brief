import math
import unittest
from scripts.audit_cash_reinvestment import gross_close_return


class CashReinvestmentTests(unittest.TestCase):
    def test_dividend_price_drop_preserves_wealth(self):
        self.assertAlmostEqual(gross_close_return(100, 99, 1), 0)

    def test_split_and_cash_use_pre_action_share_units(self):
        self.assertAlmostEqual(gross_close_return(100, 49.5, 1, 2), 0)
        self.assertAlmostEqual(gross_close_return(100, 50, 0, 2), 0)

    def test_share_count_cash_reinvestment_matches_wealth_return(self):
        old_shares = 7
        before = old_shares * 665.75
        extra_shares = old_shares * 0.525 / 741.245
        after = (old_shares + extra_shares) * 741.245
        self.assertAlmostEqual(gross_close_return(665.75, 741.245, 0.525), after / before - 1)

    def test_missing_nonfinite_and_impossible_inputs_rejected(self):
        for args in [(None, 99, 1), (100, math.nan, 1), (100, math.inf, 1), (0, 99, 1),
                     (100, 0, 1), (100, 99, -1), (100, 99, True), (100, 99, 1, 0)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                gross_close_return(*args)


if __name__ == '__main__':
    unittest.main()

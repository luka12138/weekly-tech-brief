import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from market_metric_windows import action_gap_impact, qualify_metrics


class ConventionBoundsTests(unittest.TestCase):
    def setUp(self):
        self.window = {'status': 'available', 'price_dates': ['2026-09-07', '2026-09-08'],
                       'return_dates': ['2026-09-08']}
        self.windows = {k: self.window for k in ['week_return', 'rv20', 'prior_rv20', 'rv20_change']}
        self.bound = {'earliest': None, 'latest': '2026-08-31',
                      'evidence_basis': 'Reviewed ordinary cash record-date and exchange settlement rule'}

    def test_bounded_earlier_event_does_not_block_later_metrics(self):
        result = action_gap_impact(self.windows, effective_date_bounds=self.bound)
        self.assertTrue(all(v['this_gap_affects_metric'] is False for v in result.values()))
        self.assertTrue(all(v['other_action_coverage_certified'] is False for v in result.values()))

    def test_overlapping_inclusive_boundary_and_unknown_date_still_block(self):
        for bound in [None, {**self.bound, 'latest': '2026-09-08'},
                      {**self.bound, 'earliest': '2026-09-08', 'latest': None}]:
            result = action_gap_impact(self.windows, effective_date_bounds=bound)
            self.assertTrue(result['rv20']['this_gap_affects_metric'])

    def test_invalid_bounds_rejected(self):
        for bound in [{}, {'latest': '2026-08-31'}, {**self.bound, 'evidence_basis': True},
                      {**self.bound, 'evidence_basis': ' '}, {**self.bound, 'latest': 'bad'},
                      {**self.bound, 'earliest': '2026-09-01'}]:
            with self.assertRaises(ValueError):
                action_gap_impact(self.windows, effective_date_bounds=bound)
        with self.assertRaises(ValueError):
            action_gap_impact(self.windows, '2026-08-28', self.bound)

    def test_no_data_is_not_unaffected(self):
        result = action_gap_impact({'rv20': {'status': 'insufficient_samples', 'return_dates': []}},
                                   effective_date_bounds=self.bound)
        self.assertIsNone(result['rv20']['this_gap_affects_metric'])

    def test_gross_name_cannot_clear_convention_check(self):
        proof = dict.fromkeys(['cash_action_coverage', 'noncash_action_coverage',
                               'cash_reinvestment_convention', 'matching_gross_benchmark',
                               'matching_currency_and_calendar', 'historical_price_version',
                               'historical_action_version', 'historical_benchmark_version'], True)
        evidence = {k: dict(proof) for k in ['week_return', 'excess_return', 'rv20', 'rv20_change']}
        result = qualify_metrics(self.windows, evidence)
        self.assertTrue(result['week_return']['strict_PIT_eligible'])
        self.assertEqual(result['excess_return']['method_blockers'], ['benchmark_convention_compatibility'])
        evidence['excess_return']['benchmark_convention_compatibility'] = True
        self.assertTrue(qualify_metrics(self.windows, evidence)['excess_return']['strict_PIT_eligible'])

    def test_gap_interval_passes_only_that_gap(self):
        gap = {'id': 'date_unknown', 'ex_date': None, 'effective_date_bounds': self.bound}
        result = qualify_metrics(self.windows, {}, [gap])
        for row in result.values():
            self.assertNotIn('action_gap:date_unknown', row['method_blockers'])
            self.assertIn('cash_action_coverage', row['method_blockers'])
            self.assertFalse(row['strict_PIT_eligible'])


if __name__ == '__main__':
    unittest.main()

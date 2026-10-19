import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from reporting_window import reporting_window, validate_declared_window, MORNING, MARKER


class ReportingWindowTests(unittest.TestCase):
    def test_transition_has_no_nine_hour_gap(self):
        start,end=reporting_window('2026-10-19',MORNING)
        self.assertEqual(start.isoformat(),'2026-10-12T00:00:00+08:00')
        self.assertEqual(end.isoformat(),'2026-10-19T09:00:00+08:00')

    def test_future_week_joins_preceding_cutoff(self):
        start,end=reporting_window('2026-10-26',MORNING)
        self.assertEqual(start,reporting_window('2026-10-19',MORNING)[1])
        self.assertEqual((end-start).total_seconds(),7*86400)

    def test_old_frozen_issue_not_rewritten(self):
        self.assertEqual(reporting_window('2026-10-19')[1].hour,0)
        with self.assertRaisesRegex(ValueError,'backdate'):
            reporting_window('2026-10-12',MORNING)
        with self.assertRaisesRegex(ValueError,'09:00'):
            reporting_window('2026-10-26')

    def test_report_evidence_cannot_silently_disagree(self):
        d={'report_date':'2026-10-19','cutoff_policy':MORNING,'cutoff_exclusive':'2026-10-19T09:00:00+08:00'}
        validate_declared_window(d,MARKER)
        with self.assertRaisesRegex(ValueError,'differ'):
            validate_declared_window(d,'old report')
        d['cutoff_exclusive']='2026-10-19T00:00:00+08:00'
        with self.assertRaisesRegex(ValueError,'cutoff'):
            validate_declared_window(d,MARKER)

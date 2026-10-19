import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from download_wind_market import prepare
from wind_readonly_session import required_result_valid


class WindDownloadTests(unittest.TestCase):
    def test_control_needs_real_finite_values(self):
        self.assertFalse(required_result_valid({'ErrorCode':0,'Data':[[None]]}))
        self.assertFalse(required_result_valid({'ErrorCode':0,'Data':[[float('nan')]]}))
        self.assertFalse(required_result_valid({'ErrorCode':0,'Data':[[{'nonfinite':'nan'}]]}))
        self.assertFalse(required_result_valid({'ErrorCode':-1,'Data':[[42.45]]}))
        self.assertTrue(required_result_valid({'ErrorCode':0,'Data':[['招商银行']]}))
        self.assertTrue(required_result_valid({'ErrorCode':0,'Data':[[42.45]]}))

    def test_jobs_are_readonly_bounded_and_registry_is_frozen(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'state').mkdir()
            registry=root/'state/registry.json'
            data={'markets':{'TW':{'benchmark':'TWII.TW','calendar':'TWSE','currency':'TWD'}},
                  'companies':[{'company':'TSMC','symbol':'2330.TW','market':'TW'}]}
            registry.write_text(json.dumps(data))
            manifest,jobs=prepare(root,'2026-10-19',registry)
            m=json.loads(manifest.read_text());j=json.loads(jobs.read_text())
            self.assertEqual(m['window'],['2026-08-17','2026-10-16'])
            self.assertTrue(all(x['method']in{'wss','wsd','tdays'}for x in j))
            self.assertTrue(j[0]['require_nonempty'] and j[1]['require_nonempty'])
            self.assertEqual(len({x['id']for x in j}),len(j))
            frozen=root/m['registry']['path'];before=frozen.read_bytes()
            registry.write_text('{}')
            self.assertEqual(frozen.read_bytes(),before)
            self.assertTrue(all('TradingCalendar=TWSE'in x['args'][-1]for x in j[3:]))

    def test_non_monday_rejected(self):
        with self.assertRaisesRegex(ValueError,'Monday'):
            prepare(Path('.'),'2026-10-20',Path('not-needed'))


if __name__=='__main__':unittest.main()

import copy
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from download_chart_actions import normalize


class ChartActionsTests(unittest.TestCase):
    def setUp(self):
        self.stamp=int(datetime(2026,9,16,9,tzinfo=ZoneInfo('Asia/Taipei')).timestamp())
        self.payload={'chart':{'error':None,'result':[{'meta':{'symbol':'2330.TW','currency':'TWD','exchangeTimezoneName':'Asia/Taipei','instrumentType':'EQUITY'},
             'timestamp':[self.stamp],'indicators':{'quote':[{'close':[100]}]},
             'events':{'dividends':{str(self.stamp):{'date':self.stamp,'amount':7.000001}}}}]}}
    def norm(self):return normalize(self.payload,'2330.TW','2026-09-01','2026-09-30')
    def test_ex_date_uses_exchange_timezone(self):
        r=self.norm();self.assertEqual(r['actions'][0]['ex_date'],'2026-09-16');self.assertEqual(r['actions'][0]['cash_amount_per_share'],'7.000001')
    def test_wrong_security_currency_rejected(self):
        self.payload['chart']['result'][0]['meta']['currency']='USD'
        with self.assertRaisesRegex(ValueError,'currency'):self.norm()
    def test_missing_known_actions_not_turned_into_certification(self):
        self.payload['chart']['result'][0].pop('events');r=self.norm()
        self.assertEqual(r['actions'],[]);self.assertIn('Missing known issuer events',r['limitation'])
    def test_nonfinite_cash_rejected(self):
        self.payload['chart']['result'][0]['events']['dividends'][str(self.stamp)]['amount']=float('nan')
        with self.assertRaisesRegex(ValueError,'cash'):self.norm()
    def test_split_ratio_is_new_shares_over_old(self):
        self.payload['chart']['result'][0]['events']={'splits':{str(self.stamp):{'date':self.stamp,'numerator':4,'denominator':1,'splitRatio':'4:1'}}}
        r=self.norm();self.assertEqual(r['actions'][0]['new_shares'],'4');self.assertEqual(r['actions'][0]['old_shares'],'1')
    def test_unknown_action_and_incomplete_series_rejected(self):
        self.payload['chart']['result'][0]['events']['unknown']={}
        with self.assertRaisesRegex(ValueError,'Unknown'):self.norm()
        self.payload['chart']['result'][0]['events'].pop('unknown');self.payload['chart']['result'][0]['indicators']['quote'][0]['close']=[]
        with self.assertRaisesRegex(ValueError,'Truncated'):self.norm()

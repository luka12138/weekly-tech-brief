import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from market_qualification import cash_effects, qualification, roc_date, tsmc_cash_events, twse_total_return, krx_total_return


class CashQualificationTests(unittest.TestCase):
    def obs(self):
        return {'instrument':{'symbol':'X','currency':'USD','price_basis':'unadjusted_close_price_return'},
                'session_dates':['2026-10-08','2026-10-09','2026-10-12'],'closes':[100,99,100]}
    def event(self):
        return {'instrument':'X','currency':'USD','event_type':'cash_dividend','ex_date':'2026-10-09','cash_amount_declared_per_share':'1'}
    def test_wealth_conservation_and_reinvestment(self):
        d=cash_effects(self.obs(),[self.event()],'2026-10-19')
        self.assertAlmostEqual(d['daily'][0]['return_with_known_cash_events'],0)
        self.assertAlmostEqual(1+d['full_window_return'],100/99)
        self.assertIsNone(d['daily'][1]['known_cash_per_share'])
        self.assertFalse(d['complete_total_return_certified'])
    def test_reject_future_and_currency_and_missing_exdate(self):
        for change in [{'currency':'TWD'},{'ex_date':None},{'ex_date':'2026-10-20'}]:
            with self.assertRaises(ValueError):cash_effects(self.obs(),[{**self.event(),**change}],'2026-10-19')
        with self.assertRaises(ValueError):cash_effects(self.obs(),[],'2026-10-12')
    def test_duplicate_event_not_double_paid(self):
        with self.assertRaises(ValueError):cash_effects(self.obs(),[self.event(),self.event()],'2026-10-19')
    def test_no_generic_true_from_partial_inputs(self):
        base=dict(cash_coverage=True,noncash_coverage=True,benchmark_basis='gross_total_return',price_vintage=True,action_vintage=True,benchmark_vintage=True)
        self.assertFalse(qualification(**base)['strict_PIT_total_return_eligible'])
        base['benchmark_convention_verified']=True
        self.assertTrue(qualification(**base)['strict_PIT_total_return_eligible'])
        for field in ['cash_coverage','noncash_coverage','price_vintage','action_vintage','benchmark_vintage','benchmark_convention_verified']:
            self.assertFalse(qualification(**{**base,field:False})['strict_PIT_total_return_eligible'])
        self.assertFalse(qualification(**{**base,'benchmark_basis':'price'})['strict_PIT_total_return_eligible'])
    def test_twse_does_not_fill_missing_calendar_days(self):
        p={'stat':'OK','fields':['日\u3000期','發行量加權股價報酬指數'],'total':1,'data':[['115/10/16','123,456.78']]}
        self.assertEqual(twse_total_return([p],['2026-10-16'])['closes'],['123456.78'])
        with self.assertRaises(ValueError):twse_total_return([p],['2026-10-15'])
        self.assertEqual(roc_date('115年09月16日'),'2026-09-16')
    def test_tsmc_ads_currency_not_confused_with_common(self):
        html='<table><tr><td>1Q26</td><td>-</td><td>NT$7.00000137</td><td>2026/09/16</td><td>2026/09/22</td><td>2026/10/08</td><td>-</td></tr><tr><td>1Q26</td><td>-</td><td>US$1.0962510</td><td>2026/09/16</td><td>2026/09/16</td><td>2026/10/08</td><td>-</td></tr></table>'
        exchange={'stat':'OK','fields':['資料日期','股票代號','股票名稱','除權息前收盤價','除權息參考價','權值+息值','權/息'],'data':[['115年09月16日','2330','台積電','2385','2377.99','7.000001','息']]}
        events=tsmc_cash_events(html,exchange,'2026-08-17','2026-10-16')
        self.assertEqual(len(events),1);self.assertEqual(events[0]['cash_amount_declared_per_share'],'7.00000137')
        exchange['data'][0][5]='7.01'
        with self.assertRaises(ValueError):tsmc_cash_events(html,exchange,'2026-08-17','2026-10-16')
    def test_krx_response_window_must_match(self):
        payload={'output':[{'trd_dd':'2026/10/16','clsprc_idx':'7,445.96'}]}
        self.assertEqual(krx_total_return(payload,['2026-10-16'])['closes'],['7445.96'])
        with self.assertRaises(ValueError):krx_total_return(payload,['2026-10-15'])
        payload['output'].append(dict(payload['output'][0]))
        with self.assertRaises(ValueError):krx_total_return(payload,['2026-10-16'])


if __name__=='__main__':unittest.main()

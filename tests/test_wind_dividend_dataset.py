import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from wind_dividend_dataset import inspect, plan


class WindDividendDatasetTests(unittest.TestCase):
    def receipt(self):
        return {'request': plan('META.O','USD','2025-01-01','2026-10-16','test'),
                'retrieved_at':'2026-10-19T05:00:00+00:00',
                'result': {'ErrorCode':0,'Codes':['1'],'Fields':[
                    'ex-rights ex-dividend date','dividend per share pre-tax','period',
                    'forecast dividend per share','stock dividend per share'],
                    'Data':[['2026-09-21T00:00:00'],[0.525],['2026-06-30'],[99],[None]]}}

    def run_inspect(self, obj):
        return inspect(obj,'META.O','USD','2026-08-17','2026-10-16')

    def test_actual_forecast_and_unknown_actions_are_separate(self):
        result = self.run_inspect(self.receipt())
        self.assertEqual(result['events'][0]['cash_amount_declared_per_share'],'0.525')
        self.assertIsNone(result['events'][0]['noncash_fields']['stock dividend per share'])
        self.assertFalse(result['complete_cash_coverage'])
        self.assertFalse(result['historical_PIT_certified'])

    def test_empty_success_is_not_no_dividend(self):
        obj = self.receipt(); obj['result'].update(Fields=[],Data=[],Codes=[])
        result=self.run_inspect(obj)
        self.assertEqual(result['status'],'empty_success')
        self.assertFalse(result['absence_of_dividends_certified'])

    def test_error_message_is_not_cash_data(self):
        obj=self.receipt();obj['result']={'ErrorCode':-40520017,'Data':[['未找到分红记录']]}
        result=self.run_inspect(obj)
        self.assertEqual(result['status'],'api_error')
        self.assertEqual(result['events'],[])

    def test_exact_parameter_space_matters(self):
        obj=self.receipt();obj['request']['args'][1]=obj['request']['args'][1].replace('Current Rate','CurrentRate')
        with self.assertRaises(ValueError): self.run_inspect(obj)

    def test_query_window_does_not_define_ex_dates(self):
        obj=self.receipt();obj['result']['Data'][0]=['2026-10-20']
        result=self.run_inspect(obj)
        self.assertEqual(result['events'],[])
        self.assertEqual(len(result['rows_outside_event_window']),1)
        self.assertFalse(result['query_date_semantics_certified'])

    def test_malformed_and_duplicate_columns_rejected(self):
        for mutation in ['ragged','duplicate','codes']:
            obj=self.receipt()
            if mutation=='ragged': obj['result']['Data'][0].append('2026-09-22')
            elif mutation=='duplicate':obj['result']['Fields'][-1]=obj['result']['Fields'][0]
            else:obj['result']['Codes']=[]
            with self.assertRaises(ValueError):self.run_inspect(obj)

    def test_missing_nonfinite_or_zero_cash_never_filled(self):
        for value in [None,0,True,{'nonfinite':'nan'},float('inf')]:
            obj=self.receipt();obj['result']['Data'][1]=[value]
            result=self.run_inspect(obj)
            self.assertEqual(result['events'],[])
            self.assertEqual(result['status'],'rows_require_review')

    def test_identity_currency_and_table_rejected(self):
        for old,new in [('META.O','AAPL.O'),('currency=USD','currency=CNY')]:
            obj=self.receipt();obj['request']['args'][1]=obj['request']['args'][1].replace(old,new)
            with self.assertRaises(ValueError):self.run_inspect(obj)
        obj=self.receipt();obj['request']['args'][0]='dividend'
        with self.assertRaises(ValueError):self.run_inspect(obj)

    def test_conflict_blocks_clean_status(self):
        obj=self.receipt();obj['result']['Codes']=['1','2']
        obj['result']['Data']=[col*2 for col in obj['result']['Data']]
        obj['result']['Data'][1][1]=0.75
        self.assertEqual(self.run_inspect(obj)['status'],'rows_require_review')


if __name__=='__main__': unittest.main()

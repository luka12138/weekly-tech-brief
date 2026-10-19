from copy import deepcopy
from pathlib import Path
import sys
import json
import hashlib
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from dividend_events import normalize_nasdaq, resolve_fields, wind_field_status
from download_dividend_events import run


def payload():
    return {'status':{'rCode':200},'data':{'dividends':{'asOf':None,'rows':[
        {'exOrEffDate':'09/21/2026','type':'Cash','amount':'$0.525','currency':'USD',
         'declarationDate':'09/10/2026','recordDate':'09/21/2026','paymentDate':'09/28/2026'}]}}}


def normalize(data):
    return normalize_nasdaq(data,'META.O','USD','2026-08-17','2026-10-16')


class DividendEventTests(unittest.TestCase):
    def test_realistic_exchange_row_preserves_precision_explicit_dates_and_qualification(self):
        result=normalize(payload());e=result['events'][0]
        self.assertEqual(e['cash_amount_declared_per_share'],'0.525')
        self.assertEqual(e['ex_date'],'2026-09-21')
        self.assertEqual(e['payment_date'],'2026-09-28')
        self.assertEqual(e['ex_date_basis'],'explicit_exchange_api_row')
        self.assertFalse(result['historical_PIT_certified'])

    def test_success_with_null_wind_fields_resolves_from_real_event_without_changing_raw(self):
        winds={f:{'result':{'ErrorCode':0,'Codes':['META.O'],'Fields':[f.upper()],'Data':[[None]]}} for f in ['div_cashbeforetax','div_exdate']}
        before=deepcopy(winds);e=normalize(payload())['events']
        rows=resolve_fields(e,'META.O',winds,{'path':'raw.json','sha256':'a'*64})
        self.assertEqual(winds,before)
        self.assertEqual(rows[0]['fields']['div_cashbeforetax']['value'],'0.525')
        self.assertEqual(rows[0]['fields']['div_exdate']['value'],'2026-09-21')
        self.assertTrue(all(x['raw_wind_status']=='empty_success' for x in rows[0]['fields'].values()))
        self.assertFalse(rows[0]['fields']['div_cashbeforetax']['assignment_to_original_wind_field'])
        self.assertEqual(rows[0]['fields']['div_cashbeforetax']['standard_field'], 'cash_amount_declared_per_share')

    def test_http_success_is_not_api_success(self):
        data=payload();data['status']['rCode']=500
        with self.assertRaisesRegex(ValueError,'application'):normalize(data)

    def test_empty_and_missing_history_do_not_assert_no_dividends(self):
        for data in [{'status':{'rCode':200},'data':None},
                     {'status':{'rCode':200},'data':{'dividends':{'rows':[]}}}]:
            self.assertFalse(normalize(data)['absence_of_dividends_certified'])

    def test_future_events_are_excluded_without_using_their_cash_amounts(self):
        data=payload();data['data']['dividends']['rows'].append({'exOrEffDate':'12/21/2026','amount':'unknown'})
        result=normalize(data);self.assertEqual(len(result['events']),1)
        self.assertEqual(result['rows_outside_window'],1)

    def test_missing_date_currency_or_cash_cannot_be_filled_or_guessed(self):
        for field,value in [('currency','KRW'),('amount',None),('amount','$0'),('amount','NaN'),('type','Stock')]:
            data=payload();data['data']['dividends']['rows'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):normalize(data)

    def test_unknown_old_exdate_keeps_known_event_and_records_unresolved_row(self):
        data=payload();data['data']['dividends']['rows'].append({'exOrEffDate':'N/A','amount':'unknown'})
        result=normalize(data)
        self.assertEqual(len(result['events']),1)
        self.assertEqual(len(result['unresolved_history_rows']),1)
        self.assertFalse(result['absence_of_dividends_certified'])

    def test_null_history_is_distinct_from_failed_api_and_no_dividend_certification(self):
        data=payload();data['data']['dividends']['rows']=None
        result=normalize(data)
        self.assertEqual(result['status'],'no_history_supplied')
        self.assertFalse(result['absence_of_dividends_certified'])

    def test_duplicate_conflict_is_not_silently_deduplicated(self):
        data=payload();row=deepcopy(data['data']['dividends']['rows'][0]);row['amount']='$0.55';data['data']['dividends']['rows'].append(row)
        with self.assertRaisesRegex(ValueError,'Conflicting'):normalize(data)

    def test_revision_changes_version_but_not_event_identity(self):
        a=normalize(payload())['events'][0];data=payload();data['data']['dividends']['rows'][0]['amount']='$0.55';b=normalize(data)['events'][0]
        self.assertEqual(a['event_id'],b['event_id']);self.assertNotEqual(a['event_version_sha256'],b['event_version_sha256'])

    def test_nonempty_or_wrong_wind_values_require_reconciliation(self):
        source={'result':{'ErrorCode':0,'Codes':['META.O'],'Fields':['DIV_CASHBEFORETAX'],'Data':[[9.9]]}}
        with self.assertRaisesRegex(ValueError,'reconciliation'):
            resolve_fields(normalize(payload())['events'],'META.O',{'div_cashbeforetax':source},{})
        source['result']['Codes']=['AAPL.O']
        self.assertEqual(wind_field_status(source,'META.O','div_cashbeforetax'),'identity_or_field_mismatch')

    def test_empty_string_and_nonfinite_wind_are_not_successful_values(self):
        source={'result':{'ErrorCode':0,'Codes':['META.O'],'Fields':['DIV_CASHBEFORETAX'],'Data':[['']]}}
        self.assertEqual(wind_field_status(source,'META.O','div_cashbeforetax'),'empty_success')
        source['result']['Data']=[[{'nonfinite':'nan'}]]
        self.assertEqual(wind_field_status(source,'META.O','div_cashbeforetax'),'nonfinite_value')
        source['result']['Data']=[[0]]
        self.assertEqual(wind_field_status(source,'META.O','div_cashbeforetax'),'returned_value_requires_semantic_validation')

    def test_download_reuses_verified_receipt_and_writes_a_traceable_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'state').mkdir();(root/'logs').mkdir()
            (root/'state/market_instruments_v1.json').write_text(json.dumps({'markets':{'US':{'currency':'USD'},'TW':{}},'companies':[{'symbol':'META.O','market':'US'}]}))
            p=root/'logs/meta.json';p.write_text(json.dumps(payload()))
            proof={'url':'https://api.nasdaq.com/api/quote/META/dividends?assetclass=stocks','http_status':200,'retrieved_at':'2026-10-19T03:05:58+00:00','sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            p.with_suffix('.receipt.json').write_text(json.dumps(proof))
            from wind_dividend_periods import plan
            wr = root/'logs/wind_periods.json'
            wr.write_text(json.dumps({'request': plan('META.O','2026-10-19'), 'retrieved_at':'2026-10-19T05:00:00+00:00',
                'result':{'ErrorCode':0,'Codes':['META.O'],'Fields':['DIV_CASHBEFORETAX','DIV_CASHBEFORETAX2','DIV_EXDATE'],
                          'Times':['2026-06-30'],'Data':[[None],[None],[20260921]]}}))
            overseas = root/'logs/wind_overseas.json'
            overseas.write_text(json.dumps({'request': {'method':'wss', 'args':[
                'META.O','div_cashbftax,div_exdate','rptDate=20260630;currencyType=;']},
                'retrieved_at':'2026-10-19T06:49:23+00:00', 'result':{
                'ErrorCode':0,'Codes':['META.O'],'Fields':['DIV_CASHBFTAX','DIV_EXDATE'],
                'Times':['2026-10-19T00:00:00'],'Data':[[0.525],['2026-09-21T00:00:00']]}}))
            path,result=run(root,'2026-10-19',['META.O'],{'META.O':p},[],[wr],[overseas])
            self.assertTrue(path.exists());self.assertEqual(result['companies']['META.O']['events'],1)
            self.assertEqual(result['unsupported_markets'],['TW'])
            self.assertIn('dividend_events.py',result['code_versions'])
            self.assertFalse(result['historical_PIT_certified'])
            normalized=json.loads((root/result['companies']['META.O']['normalized']['path']).read_text())
            self.assertTrue(normalized['wind_ex_date_corroboration'][0]['wind_ex_date_confirmed'])
            self.assertEqual(normalized['wind_period_observations']['rows'][0]['report_period'],'2026-06-30')
            self.assertFalse(normalized['wind_ex_date_corroboration'][0]['cash_amount_confirmed_by_wind'])
            self.assertTrue(normalized['wind_cash_corroboration'][0]['cash_amount_confirmed_by_wind'])
            self.assertFalse(normalized['wind_cash_corroboration'][0]['historical_PIT_certified'])
            self.assertEqual(normalized['wind_overseas_period_observations'][0]['report_period'],'2026-06-30')
            self.assertEqual(result['wind_overseas_receipts'][0]['sha256'],hashlib.sha256(overseas.read_bytes()).hexdigest())
            vintage=json.loads((path.parent/'vintage_receipt.json').read_text())
            frozen=json.loads((root/vintage['manifest']).read_text())
            self.assertIn('logs/wind_overseas.json', [x['path'] for x in frozen['entries']])
            p.write_text('{}')
            _,failed=run(root,'2026-10-19',['META.O'],{'META.O':p},[])
            self.assertEqual(failed['companies']['META.O']['status'],'unavailable')

    def test_unregistered_symbols_cannot_trigger_external_downloads(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'state').mkdir()
            (root/'state/market_instruments_v1.json').write_text(json.dumps({'companies':[{'symbol':'META.O','market':'US'}]}))
            with self.assertRaisesRegex(ValueError,'registered'):
                run(root,'2026-10-19',['FAKE.O'],{},[])


if __name__=='__main__':unittest.main()

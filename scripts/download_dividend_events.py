#!/usr/bin/env python3
"""Fetch bounded registered Nasdaq dividend histories, preserving failed Wind results."""
import argparse
from market_vintages import freeze
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from dividend_events import normalize_nasdaq, resolve_fields
from wind_dividend_periods import inspect as inspect_periods, corroborate
from wind_overseas_dividends import inspect as inspect_overseas, corroborate as corroborate_overseas

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root, path):
    path = (root/path).resolve() if not path.is_absolute() else path.resolve()
    path.relative_to(root.resolve())
    return path


def run(root, report_date, symbols, saved, wind_paths, wind_period_paths=(), wind_overseas_paths=()):
    root=root.resolve()
    wind_paths=[inside(root,path) for path in wind_paths]
    wind_period_paths=[inside(root,path) for path in wind_period_paths]
    wind_overseas_paths=[inside(root,path) for path in wind_overseas_paths]
    day = date.fromisoformat(report_date)
    if day.weekday() != 0:
        raise ValueError('Report date must be Monday')
    start, end = (day-timedelta(days=63)).isoformat(), (day-timedelta(days=3)).isoformat()
    registry_path = root/'state/market_instruments_v1.json'
    registry = json.loads(registry_path.read_text())
    registered = {x['symbol']:x for x in registry['companies'] if x['market']=='US'}
    symbols = symbols or list(registered)
    if not symbols or any(s not in registered for s in symbols) or len(symbols)!=len(set(symbols)):
        raise ValueError('Only unique currently registered US securities may use this route')
    winds = {}; wind_refs = []; periods = {}; period_refs = []
    overseas_rows = []; overseas_refs = []
    currencies = {x['symbol']: registry['markets'][x['market']]['currency']
                  for x in registry['companies'] if x.get('symbol')}
    for path in wind_overseas_paths:
        data = json.loads(path.read_text())
        ref = {'path': str(path.relative_to(root)), 'sha256': sha(path), 'retrieved_at': data['retrieved_at']}
        overseas_rows.extend({**row, 'source': ref} for row in inspect_overseas(data, currencies, start, end))
        overseas_refs.append(ref)
    for path in wind_period_paths:
        data = json.loads(path.read_text()); out = data.get('result') or {}
        codes = out.get('Codes', [])
        if len(codes) != 1 or codes[0] not in symbols or codes[0] in periods:
            raise ValueError('Period receipt must identify one unique requested security')
        periods[codes[0]] = inspect_periods(data, codes[0], start, end)
        period_refs.append({'instrument': codes[0], 'path': str(path.relative_to(root)), 'sha256': sha(path),
                            'retrieved_at': data['retrieved_at']})
    for path in wind_paths:
        path = inside(root,path); data = json.loads(path.read_text()); out=data.get('result') or {}
        if len(out.get('Codes', []))!=1 or len(out.get('Fields', []))!=1:
            raise ValueError('Wind diagnostic must identify one security and one field')
        winds[(out['Codes'][0],out['Fields'][0].lower())]=data
        wind_refs.append({'path':str(path.relative_to(root)), 'sha256':sha(path)})
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    directory=root/'logs'/f'{report_date}_dividend_events_{stamp}'; directory.mkdir()
    (directory/'instrument_registry.json').write_bytes(registry_path.read_bytes())
    manifest={'schema_version':1,'report_date':report_date,'started_at':datetime.now(timezone.utc).isoformat(),
              'window':[start,end], 'registry':{'path':str((directory/'instrument_registry.json').relative_to(root)), 'sha256':sha(registry_path)},
              'wind_original_receipts':wind_refs, 'wind_period_receipts':period_refs,
              'wind_overseas_receipts': overseas_refs,
              'companies':{}, 'historical_PIT_certified':False,
              'qualification':'Cash dividend field resolution; no complete corporate-action or historical-price-version certification'}
    manifest['code_versions']={name:sha(Path(__file__).resolve().parent/name) for name in ['download_dividend_events.py','dividend_events.py','wind_dividend_periods.py','wind_overseas_dividends.py']}
    manifest['unsupported_markets']=[key for key in registry['markets'] if key!='US']
    for symbol in symbols:
        ticker=symbol.removesuffix('.O'); url=f'https://api.nasdaq.com/api/quote/{ticker}/dividends?assetclass=stocks'
        began=datetime.now(timezone.utc).isoformat(); target=directory/(ticker+'_nasdaq_response.json')
        try:
            if symbol in saved:
                original=inside(root,saved[symbol]); proof=original.with_suffix('.receipt.json')
                receipt=json.loads(proof.read_text())
                if receipt['url']!=url or receipt['http_status']!=200 or receipt['sha256']!=sha(original):
                    raise ValueError('Saved exchange response identity, status or hash mismatch')
                raw=original.read_bytes(); reuse={'path':str(original.relative_to(root)),'sha256':sha(original),'receipt_path':str(proof.relative_to(root))}
            else:
                with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'}),timeout=20) as response:
                    raw=response.read(); status=response.status
                if status!=200:raise ValueError('Exchange HTTP request did not succeed')
                receipt={'url':url,'started_at':began,'retrieved_at':datetime.now(timezone.utc).isoformat(), 'http_status':status,'sha256':hashlib.sha256(raw).hexdigest()};reuse=None
            with target.open('xb') as file:file.write(raw)
            receipt={**receipt,'copied_from':reuse}; target.with_suffix('.receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
            payload=json.loads(target.read_text()); source={'path':str(target.relative_to(root)),'sha256':sha(target), 'url':url,'retrieved_at':receipt['retrieved_at']}
            normalized=normalize_nasdaq(payload,symbol,'USD',start,end)
            normalized.update({'instrument':symbol,'source':source,'field_resolutions':resolve_fields(normalized['events'],symbol,{f:obj for (s,f),obj in winds.items() if s==symbol},source)})
            if symbol in periods:
                normalized['wind_period_observations'] = periods[symbol]
                normalized['wind_period_source'] = next(x for x in period_refs if x['instrument'] == symbol)
                normalized['wind_ex_date_corroboration'] = [corroborate(periods[symbol], e) for e in normalized['events']]
            if wind_overseas_paths:
                normalized['wind_overseas_period_observations'] = [r for r in overseas_rows if r['instrument'] == symbol]
                normalized['wind_cash_corroboration'] = [corroborate_overseas(overseas_rows, e) for e in normalized['events']]
                if any(x['status'] == 'conflict' for x in normalized['wind_cash_corroboration']):
                    normalized['status'] = 'source_conflict'
            out=directory/(ticker+'_cash_events.json');out.write_text(json.dumps(normalized,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
            assert json.loads(out.read_text())['instrument']==symbol
            manifest['companies'][symbol]={'status':normalized['status'],'events':len(normalized['events']),'normalized':{'path':str(out.relative_to(root)),'sha256':sha(out)},'source':source}
        except Exception as exc:
            failure={'url':url,'started_at':began,'ended_at':datetime.now(timezone.utc).isoformat(),'type':type(exc).__name__,'error':str(exc),'unknown_is_not_no_dividend':True}
            out=directory/(ticker+'_failure.json');out.write_text(json.dumps(failure,ensure_ascii=False,indent=2)+'\n')
            manifest['companies'][symbol]={'status':'unavailable','failure':str(out.relative_to(root))}
    manifest['finished_at']=datetime.now(timezone.utc).isoformat()
    path=directory/'manifest.json'; path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    assert json.loads(path.read_text())['companies'].keys()==manifest['companies'].keys()
    vintage,frozen=freeze(root,list(directory.glob('*.json'))+wind_paths+wind_period_paths+wind_overseas_paths,root/'state/market_vault',report_date+'-dividend-events')
    with (directory/'vintage_receipt.json').open('x') as target:
        json.dump({'manifest':str(vintage.relative_to(root)),'preserved_at':frozen['preserved_at'],
                   'historical_PIT_certified':False},target,ensure_ascii=False,indent=2)
    return path,manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-date',required=True)
    parser.add_argument('--symbols',help='Comma separated registered Wind symbols; defaults to all seven US securities')
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--saved-response',action='append',default=[],metavar='SYMBOL=PATH',help='Reuse a hash verified response and adjacent .receipt.json')
    parser.add_argument('--wind-receipt',action='append',type=Path,default=[])
    parser.add_argument('--wind-period-receipt',action='append',type=Path,default=[],
                        help='Corroborate ex-dates from verified WSD report-period rows; not daily cash')
    parser.add_argument('--wind-overseas-receipt',action='append',type=Path,default=[],
                        help='Match DIV_CASHBFTAX and explicit ex-dates to exchange events; preserves all period rows')
    args=parser.parse_args(); saved={}
    for item in args.saved_response:
        key,value=item.split('=',1)
        if key in saved:raise ValueError('Duplicate saved response')
        saved[key]=Path(value)
    path,data=run(args.root.resolve(),args.report_date,args.symbols.split(',') if args.symbols else None,saved,args.wind_receipt,args.wind_period_receipt,args.wind_overseas_receipt)
    print(json.dumps({'manifest':str(path),'companies':data['companies']},ensure_ascii=False))
    if any(x['status'] in {'unavailable', 'source_conflict'} for x in data['companies'].values()):raise SystemExit(2)


if __name__=='__main__':main()

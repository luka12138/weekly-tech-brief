#!/usr/bin/env python3
"""Bounded Yahoo Finance cash/split cross-check; Wind remains the price source.

Uses a public chart endpoint, not a contracted historical-vintage service.
Missing events mean this response reports none, not universal absence proof.
Known issuer/venue events remain authoritative when the response omits them.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from weekly_data_store import put, immutable, encode, now

MAPPINGS={**{s+'.O':(s,'USD','America/New_York') for s in ['AAPL','MSFT','GOOGL','AMZN','META','NVDA','TSLA']},
          '005930.KS':('005930.KS','KRW','Asia/Seoul'),'000660.KS':('000660.KS','KRW','Asia/Seoul'),
          '2330.TW':('2330.TW','TWD','Asia/Taipei')}


def normalize(payload,symbol,start,end):
    ticker,currency,zone=MAPPINGS[symbol]
    chart=payload.get('chart',{})
    if chart.get('error') is not None or not isinstance(chart.get('result'),list) or len(chart['result'])!=1:
        raise ValueError('Missing or failed chart payload')
    data=chart['result'][0];meta=data['meta'];tz=ZoneInfo(zone)
    if any(meta.get(k)!=v for k,v in [('symbol',ticker),('currency',currency),('exchangeTimezoneName',zone),('instrumentType','EQUITY')]):
        raise ValueError('Wrong symbol/currency/market/type')
    to_day=lambda t:datetime.fromtimestamp(t,tz).date().isoformat()
    dates=[to_day(t) for t in data.get('timestamp',[])]
    if not dates or dates!=sorted(set(dates)) or any(not start<=d<=end for d in dates):
        raise ValueError('Missing, duplicate, or out-of-window sessions')
    prices=data.get('indicators',{}).get('quote',[])
    if len(prices)!=1 or len(prices[0].get('close',[]))!=len(dates):
        raise ValueError('Truncated chart series')
    actions=[];groups=data.get('events',{})
    if not isinstance(groups,dict) or set(groups)-{'dividends','splits'}:
        raise ValueError('Unknown corporate-action type requires explicit adapter')
    for kind,events in groups.items():
        if not isinstance(events,dict):raise ValueError('Invalid event collection')
        for identity,event in events.items():
            ex=to_day(event['date'])
            if str(event['date'])!=identity or ex not in dates:raise ValueError('Invalid event identity/date')
            row={'event_id':f'{symbol}:{kind}:{ex}','instrument':symbol,'ex_date':ex,'currency':currency,'provider':'Yahoo Finance'}
            if kind=='dividends':
                amount=Decimal(str(event['amount']))
                if not amount.is_finite() or amount<=0:raise ValueError('Invalid cash amount')
                row.update(event_type='cash_dividend',cash_amount_per_share=str(amount),amount_basis='provider_reported_not_Wind_field')
            else:
                numerator=Decimal(str(event['numerator']));denominator=Decimal(str(event['denominator']))
                if not numerator.is_finite() or not denominator.is_finite() or min(numerator,denominator)<=0:
                    raise ValueError('Invalid split ratio')
                row.update(event_type='stock_split',new_shares=str(numerator),old_shares=str(denominator),split_ratio_text=event.get('splitRatio'))
            actions.append(row)
    return {'schema_version':1,'symbol':symbol,'provider_symbol':ticker,'currency':currency,'timezone':zone,
            'requested_window':[start,end],'session_dates':dates,'actions':sorted(actions,key=lambda e:e['event_id']),
            'reported_event_types':['cash_dividend','stock_split'],
            'limitation':'Public current-version cash/split cross-check only; no complete special-action or historical-PIT certification. Missing known issuer events must remain unresolved.'}


def download(symbol,start,end,store,out,transport='urllib'):
    ticker,_,zone=MAPPINGS[symbol];tz=ZoneInfo(zone)
    left=int(datetime.combine(date.fromisoformat(start),time.min,tz).timestamp())
    right=int(datetime.combine(date.fromisoformat(end)+timedelta(days=1),time.min,tz).timestamp())
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+quote(ticker,safe='')+'?'+urlencode({'period1':left,'period2':right,'interval':'1d','events':'div,splits'})
    receipt={'provider':'Yahoo Finance','symbol':symbol,'url':url,'started_at':now(),'transport':transport}
    try:
        if transport=='curl':
            completed=subprocess.run(['curl','--fail','--silent','--show-error','--max-time','20','--max-filesize','5000000',
                                      '--proto','=https','-A','WeeklyBriefResearch/1.0','-H','Accept: application/json',
                                      '-w','\n%{http_code}',url],capture_output=True,check=True,timeout=25)
            raw,status=completed.stdout.rsplit(b'\n',1);receipt['http_status']=int(status)
        elif transport=='urllib':
            with urlopen(Request(url,headers={'User-Agent':'WeeklyBriefResearch/1.0','Accept':'application/json'}),timeout=20) as response:
                raw=response.read(5_000_001);receipt['http_status']=response.status
        else:raise ValueError('Unknown transport')
        if len(raw)>5_000_000:raise ValueError('Response exceeds bound; not stored as complete')
        receipt['retrieved_at']=now();payload=json.loads(raw)
        receipt['response_ref']=put(store,payload)
        normalized=normalize(payload,symbol,start,end)
        receipt['normalized_ref']=put(store,normalized);receipt['status']='received_and_normalized'
        receipt['events']=len(normalized['actions']);receipt['sessions']=len(normalized['session_dates'])
    except Exception as error:
        receipt.update(retrieved_at=now(),status='failed',error=type(error).__name__+': '+str(error))
    immutable(out/(symbol.replace('.','_')+'.receipt.json'),encode(receipt))
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--start',required=True);p.add_argument('--end',required=True)
    p.add_argument('--store',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--symbols',nargs='+',choices=list(MAPPINGS),default=list(MAPPINGS))
    p.add_argument('--transport',choices=['urllib','curl'],default='urllib')
    a=p.parse_args();left=date.fromisoformat(a.start);right=date.fromisoformat(a.end)
    if not 0<=(right-left).days<=100:p.error('Use a bounded daily window up to 100 days')
    a.output.mkdir(parents=True,exist_ok=False)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results=list(executor.map(lambda symbol:download(symbol,a.start,a.end,a.store,a.output,a.transport),dict.fromkeys(a.symbols)))
    immutable(a.output/'manifest.json',encode({'schema_version':1,'completed_at':now(),'requests':results}))
    print(json.dumps([{k:r.get(k) for k in ['symbol','status','sessions','events','error']} for r in results],ensure_ascii=False,indent=2))
    if any(r['status']=='failed' for r in results):raise SystemExit(2)


if __name__=='__main__':main()

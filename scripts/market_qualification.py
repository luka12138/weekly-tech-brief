#!/usr/bin/env python3
"""Typed cash-event adapters and qualified return calculations.

Calculating known cash effects does not certify complete corporate actions,
historical input vintages, or an equivalent total-return benchmark.
"""
from datetime import date, timedelta
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
import math
import re
import statistics


class Rows(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=None; self.cell=None
    def handle_starttag(self, tag, attrs):
        if tag=='tr': self.row=[]
        if tag in {'td','th'} and self.row is not None: self.cell=[]
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in {'td','th'} and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split())); self.cell=None
        if tag=='tr' and self.row is not None:
            self.rows.append(self.row);self.row=None


def roc_date(value):
    parts=re.fullmatch(r'(\d{3})[年/](\d{2})[月/](\d{2})日?',value.strip())
    if not parts: raise ValueError('Invalid ROC session date')
    y,m,d=map(int,parts.groups());return date(y+1911,m,d).isoformat()


def positive(value):
    n=Decimal(str(value).replace(',',''))
    if not n.is_finite() or n<=0: raise ValueError('Missing/nonfinite/nonpositive number')
    return n


def twse_total_return(payloads, sessions):
    points={}
    for data in payloads:
        if data.get('stat')!='OK' or data.get('fields')!=['日\u3000期','發行量加權股價報酬指數']:
            raise ValueError('Not an actual TWSE total-return response')
        if data.get('total')!=len(data['data']): raise ValueError('Incomplete TWSE response')
        for row in data['data']:
            day=roc_date(row[0]); value=str(positive(row[1]))
            if day in points and points[day]!=value: raise ValueError('Conflicting index versions')
            points[day]=value
    if any(day not in points for day in sessions): raise ValueError('Missing benchmark session; do not forward fill')
    return {'symbol':'TWSE:MFI94U','name':'台湾加权报酬指数','currency':'TWD',
            'basis':'provider_total_return_index','session_dates':sessions,
            'closes':[points[day] for day in sessions], 'historical_PIT_certified':False}


def krx_total_return(payload, sessions):
    candidates=[v for v in payload.values() if isinstance(v,list) and v and isinstance(v[0],dict)
                and 'trd_dd' in v[0] and 'clsprc_idx' in v[0]]
    if len(candidates)!=1:raise ValueError('Missing or ambiguous KRX historical dataset')
    points={}
    for row in candidates[0]:
        day=date.fromisoformat(row['trd_dd'].replace('/','-')).isoformat()
        if day in points:raise ValueError('Duplicate KRX session')
        points[day]=str(positive(row['clsprc_idx']))
    if set(points)!=set(sessions):raise ValueError('KRX returned a different date window/calendar')
    return {'symbol':'KRX:KGG01T','name':'KOSPI TR','currency':'KRW','basis':'provider_total_return_index',
            'session_dates':sessions,'closes':[points[d] for d in sessions],'historical_PIT_certified':False}


def tsmc_cash_events(html, exchange, start, end):
    parser=Rows();parser.feed(html); events=[]
    if exchange.get('stat')!='OK' or exchange.get('fields',[])[:7]!=[
        '資料日期','股票代號','股票名稱','除權息前收盤價','除權息參考價','權值+息值','權/息']:
        raise ValueError('Invalid TWSE action table')
    exchange_rows={roc_date(x[0]):x for x in exchange['data'] if x[1]=='2330'}
    for row in parser.rows:
        # Common-share currency and seven-column schema exclude the USD ADS table.
        if len(row)!=7 or not row[2].startswith('NT$'): continue
        ex=date.fromisoformat(row[3].replace('/','-')).isoformat()
        if not start<=ex<=end: continue
        if row[1]!='-': raise ValueError('Stock distribution requires a separate action adapter')
        cash=positive(row[2].removeprefix('NT$')); other=exchange_rows.get(ex)
        if other is None or other[6]!='息': raise ValueError('Issuer and exchange action dates/types differ')
        # Exchange table rounds to six decimals; preserve issuer's precise amount.
        if abs(cash-positive(other[5]))>Decimal('0.0000005'):
            raise ValueError('Issuer and exchange cash values disagree beyond published precision')
        events.append({'instrument':'2330.TW','event_type':'cash_dividend','currency':'TWD',
                       'cash_amount_declared_per_share':str(cash),'ex_date':ex,
                       'ex_date_basis':'explicit_issuer_and_exchange_rows',
                       'record_date':row[4].replace('/','-'),'payment_date':row[5].replace('/','-'),
                       'period':row[0],'historical_PIT_certified':False})
    if len(events)!=len({e['ex_date'] for e in events}): raise ValueError('Duplicate issuer event')
    if set(exchange_rows)-{e['ex_date'] for e in events}: raise ValueError('Unreconciled exchange action')
    return events


def sk_dart_event(body):
    text=' '.join(unescape(re.sub('<[^>]*>',' ',body.decode('cp949'))).split())
    if '에스케이하이닉스(주)' not in text or '현금배당' not in text:
        raise ValueError('Not SK Hynix cash distribution disclosure')
    def find(pattern):
        match=re.search(pattern,text)
        if not match: raise ValueError('DART field missing')
        return match.group(1)
    return {'instrument':'000660.KS','event_type':'cash_dividend','currency':'KRW',
            'cash_amount_declared_per_share':str(positive(find(r'1주당 배당금\(원\) 보통주식 ([\d,]+)'))),
            'record_date':find(r'배당기준일 (\d{4}-\d{2}-\d{2})'),
            'declaration_date':find(r'이사회결의일\(결정일\) (\d{4}-\d{2}-\d{2})'),
            'ex_date':None,'ex_date_basis':'not_explicit_in_this_filing',
            'payment_date':None,'payment_constraint':'within_one_month_of_record_date',
            'historical_PIT_certified':False}


def cash_effects(observation, events, report_date):
    """Known-event diagnostic; explicitly does not turn other dates into certified zeros."""
    dates=observation['session_dates']; prices=[positive(x) for x in observation['closes']]
    if len(dates)!=len(prices) or dates!=sorted(set(dates)): raise ValueError('Invalid price vector')
    if any(d>=report_date for d in dates): raise ValueError('Future prices')
    symbol=observation['instrument']['symbol']; currency=observation['instrument']['currency']
    if observation['instrument']['price_basis']!='unadjusted_close_price_return': raise ValueError('Requires raw closes')
    by_day={}; rows=[]
    for e in events:
        if e['instrument']!=symbol or e['currency']!=currency: raise ValueError('Action identity/currency mismatch')
        if e['event_type']!='cash_dividend': raise ValueError('Unsupported action')
        day=e['ex_date']
        if day is None or day not in dates[1:]: raise ValueError('Explicit applicable ex-session and previous close required')
        if day in by_day: raise ValueError('Multiple cash events require explicit consolidation')
        by_day[day]=positive(e['cash_amount_declared_per_share'])
    for i,day in enumerate(dates[1:],1):
        cash=by_day.get(day,Decimal(0))
        r=(prices[i]+cash)/prices[i-1]-1
        rows.append({'session_date':day,'known_cash_per_share':str(cash) if day in by_day else None,
                     'return_with_known_cash_events':float(r)})
    start=(date.fromisoformat(report_date)-timedelta(days=7)).isoformat()
    indices=[i for i,r in enumerate(rows) if r['session_date']>=start]
    logs=[math.log1p(r['return_with_known_cash_events']) for r in rows]
    rv=lambda x:statistics.stdev(x[-20:])*math.sqrt(252) if len(x)>=20 else None
    current=rv(logs); prior=rv(logs[:indices[0]]) if indices else None
    return {'symbol':symbol,'basis':'known_cash_events_only_diagnostic',
            'cash_reinvestment_convention':'gross_cash_at_ex_session_close_no_tax_no_fees',
            'cash_event_count':len(events),'daily':rows,
            'week_return':math.prod(1+rows[i]['return_with_known_cash_events'] for i in indices)-1 if indices else None,
            'rv20':current,'rv20_change':current-prior if current is not None and prior is not None else None,
            'full_window_return':math.prod(1+r['return_with_known_cash_events'] for r in rows)-1,
            'other_action_absence_assumed_for_diagnostic':True,
            'complete_total_return_certified':False,'historical_PIT_certified':False}


def qualification(*, cash_coverage, noncash_coverage, benchmark_basis, price_vintage, action_vintage,
                  benchmark_vintage, benchmark_convention_verified=False):
    reasons=[]
    for ready,name in [(cash_coverage,'cash_action_coverage'),(noncash_coverage,'non_cash_action_coverage'),
                       (benchmark_basis=='gross_total_return','matching_gross_total_return_benchmark'),
                       (benchmark_convention_verified,'benchmark_convention_compatibility'),
                       (price_vintage,'historical_price_version'),(action_vintage,'historical_action_version'),
                       (benchmark_vintage,'historical_benchmark_version')]:
        if ready is not True: reasons.append(name)
    return {'strict_PIT_total_return_eligible':not reasons,'blocking_requirements':reasons}

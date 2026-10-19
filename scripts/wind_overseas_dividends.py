#!/usr/bin/env python3
"""Wind's implemented-dividend field with explicit report-period/event separation.

The installed generator produces DIV_CASHBFTAX (help formula HKS_DIV_CASHBFTAX)
with rptDate and currencyType= for original currency. This is a different field
from DIV_CASHBEFORETAX. Period rows alone do not establish action completeness.
"""
import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from wind_dividend_periods import number

FIELDS = ['DIV_CASHBFTAX', 'DIV_EXDATE']


def plan(symbols, report_date, periods):
    day = date.fromisoformat(report_date)
    if day.weekday() != 0:
        raise ValueError('Report date must be Monday')
    if not symbols or any(
            not isinstance(s, str) or not s or any(c in s for c in ',;\n') for s in symbols) or len(symbols) != len(set(symbols)):
        raise ValueError('Unique explicit security codes required')
    if not periods or len(periods) != len(set(periods)):
        raise ValueError('Unique explicit report periods required')
    jobs = []
    for period in periods:
        p = date.fromisoformat(period)
        if not day - timedelta(days=400) <= p < day:
            raise ValueError('Report-period diagnostic is bounded to the preceding 400 days')
        stamp = p.strftime('%Y%m%d')
        identity = hashlib.sha256(','.join(symbols).encode()).hexdigest()[:10]
        jobs.append({'id': f'overseasdiv_{identity}_{stamp}_{day:%Y%m%d}', 'method': 'wss',
                     'args': [','.join(symbols), ','.join(FIELDS).lower(),
                              f'rptDate={stamp};currencyType=;']})
    return jobs


def inspect(receipt, currencies, start, end):
    begin, finish = date.fromisoformat(start), date.fromisoformat(end)
    if begin > finish:
        raise ValueError('Invalid effective-date window')
    req, res = receipt['request'], receipt['result']
    args = req.get('args', [])
    if req.get('method') != 'wss' or len(args) != 3 or args[1].upper().split(',') != FIELDS:
        raise ValueError('Unexpected Wind method or fields')
    symbols = args[0].split(',')
    if not symbols or len(symbols) != len(set(symbols)) or any(s not in currencies for s in symbols):
        raise ValueError('Unknown or duplicate security')
    if not args[2].startswith('rptDate=') or not args[2].endswith(';currencyType=;'):
        raise ValueError('Only verified original-currency parameters are supported')
    period_text = args[2][len('rptDate='):-len(';currencyType=;')]
    period = datetime.strptime(period_text, '%Y%m%d').date().isoformat()
    if args[2] != f'rptDate={period.replace("-", "")};currencyType=;':
        raise ValueError('Unexpected report-period options')
    if not finish - timedelta(days=400) <= date.fromisoformat(period) <= finish:
        raise ValueError('Unbounded or future report-period diagnostic')
    if res.get('ErrorCode') != 0 or res.get('Codes') != symbols or res.get('Fields') != FIELDS:
        raise ValueError('Wind error or returned identity mismatch')
    matrix = res.get('Data')
    if not isinstance(matrix, list) or len(matrix) != 2 or any(
            not isinstance(c, list) or len(c) != len(symbols) for c in matrix):
        raise ValueError('Malformed field-major security matrix')
    # WSS Times identifies its response context, not an ex-date or publication time.
    if not isinstance(res.get('Times'), list) or len(res['Times']) != 1:
        raise ValueError('Unexpected snapshot time axis')
    rows = []
    for i, symbol in enumerate(symbols):
        cash = number(matrix[0][i]); raw_date = matrix[1][i]
        ex = None
        if raw_date is not None:
            if not isinstance(raw_date, str):
                raise ValueError('Expected explicit Wind datetime for ex-date')
            parsed = datetime.fromisoformat(raw_date)
            if parsed.time().isoformat() != '00:00:00':
                raise ValueError('Unexpected ex-date precision')
            ex = parsed.date().isoformat()
        currency = currencies[symbol]
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isupper():
            raise ValueError('Explicit registered original currency required')
        rows.append({'instrument': symbol, 'report_period': period, 'currency': currency,
                     'currency_basis': 'registered_security_currency_with_generator_original_currency_option',
                     'reported_implemented_cash': cash, 'ex_date': ex,
                     'inside_effective_window': None if ex is None else start <= ex <= end,
                     'status': 'empty_success' if cash is None and ex is None else 'observed_period_row',
                     'original_field': 'div_cashbftax',
                     'assignment_to_div_cashbeforetax': False,
                     'complete_action_coverage': False, 'historical_PIT_certified': False})
    return rows


def corroborate(rows, event):
    matching = [r for r in rows if r['instrument'] == event['instrument'] and r['ex_date'] == event['ex_date']]
    matched, conflicts = [], []
    parsed_amount = number(event['cash_amount_declared_per_share'])
    if parsed_amount is None:
        raise ValueError('A cash event requires a positive amount')
    amount = Decimal(parsed_amount)
    if amount <= 0:
        raise ValueError('A cash event requires a positive amount')
    for row in matching:
        if row['currency'] != event['currency']:
            conflicts.append('currency_mismatch')
        elif row['reported_implemented_cash'] is not None:
            if Decimal(row['reported_implemented_cash']) == amount:
                matched.append(row)
            else:
                conflicts.append('cash_amount_mismatch')
    return {'instrument': event['instrument'], 'event_id': event['event_id'],
            'ex_date': event['ex_date'], 'wind_ex_date_confirmed': bool(matching),
            'cash_amount_confirmed_by_wind': bool(matched) and not conflicts,
            'status': 'conflict' if conflicts else 'amount_and_ex_date_match' if matched else 'not_confirmed',
            'conflicts': sorted(set(conflicts)),
            'matched_report_periods': sorted({r['report_period'] for r in matched}),
            'matched_sources': [r['source'] for r in matched if 'source' in r],
            'complete_action_coverage': False, 'historical_PIT_certified': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report-date', required=True)
    p.add_argument('--symbols', required=True)
    p.add_argument('--periods', required=True, help='Explicit comma separated ISO report periods; not event coverage')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    jobs = plan(a.symbols.split(','), a.report_date, a.periods.split(','))
    with a.output.open('x') as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    if json.loads(a.output.read_text()) != jobs:
        raise RuntimeError('Plan readback failed')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Inspect Wind dividend *report-period* rows, never relabel their time axis.

The installed Wind help defines DIV_CASHBEFORETAX as implemented dividends for
the specified dividend year. A WSD Times value is not the action's ex-date.
These rows provide corroboration, not a complete effective-date action ledger.
"""
import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

FIELDS = ('DIV_CASHBEFORETAX', 'DIV_CASHBEFORETAX2', 'DIV_EXDATE')


def plan(symbol, report_date, query_start=None):
    day = date.fromisoformat(report_date)
    if day.weekday() != 0:
        raise ValueError('Report date must be Monday')
    # Bounded diagnostic range includes prior year end. It is NOT a guarantee
    # that every issuer fiscal period or effective action is covered.
    start = date.fromisoformat(query_start) if query_start else date(day.year - 1, 12, 1)
    end = day - timedelta(days=3)
    if not 0 <= (end - start).days <= 400:
        raise ValueError('Query range must be between 0 and 400 days')
    return {'id': 'divperiod_' + symbol.replace('.', '_') + '_' + day.strftime('%Y%m%d'),
            'method': 'wsd', 'args': [symbol, ','.join(FIELDS).lower(), start.isoformat(),
                                      end.isoformat(), 'currencyType=BB;Days=ALLDAYS']}


def number(value):
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, (dict, list)):
        raise ValueError('Invalid/nonfinite numeric value')
    try:
        n = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('Invalid numeric value') from exc
    if not n.is_finite() or n < 0:
        raise ValueError('Invalid/nonfinite numeric value')
    return format(n, 'f')


def exdate(value):
    if value is None:
        return None
    n = number(value)
    d = Decimal(n)
    if d != d.to_integral_value():
        raise ValueError('Ex-date must be an integer YYYYMMDD')
    return datetime.strptime(str(int(d)), '%Y%m%d').date().isoformat()


def inspect(receipt, symbol, start, end):
    begin, finish = date.fromisoformat(start), date.fromisoformat(end)
    if begin > finish:
        raise ValueError('Invalid effective-date window')
    req, res = receipt['request'], receipt['result']
    if req.get('method') != 'wsd' or len(req.get('args', [])) != 5 or req['args'][0] != symbol:
        raise ValueError('Request identity mismatch')
    if (req['args'][1].upper().split(',') != list(FIELDS) or
            req['args'][4] != 'currencyType=BB;Days=ALLDAYS'):
        raise ValueError('Unverified field set or query parameters')
    query_start, query_end = (date.fromisoformat(x) for x in req['args'][2:4])
    if not 0 <= (query_end-query_start).days <= 400 or query_end > finish:
        raise ValueError('Unbounded or future report-period request')
    if res.get('ErrorCode') != 0:
        raise ValueError('Wind request failed')
    if res.get('Codes') != [symbol] or res.get('Fields') != list(FIELDS):
        raise ValueError('Returned identity or fields mismatch')
    times, matrix = res.get('Times'), res.get('Data')
    if not isinstance(times, list) or not times or times != sorted(set(times)):
        raise ValueError('Missing, duplicate or unordered report periods')
    if not isinstance(matrix, list) or len(matrix) != 3 or any(not isinstance(c, list) or len(c) != len(times) for c in matrix):
        raise ValueError('Invalid field-major matrix')
    rows = []
    for i, period in enumerate(times):
        date.fromisoformat(period)
        if not req['args'][2] <= period <= req['args'][3]:
            raise ValueError('Report-period row outside request')
        if all(c[i] is None for c in matrix):
            continue
        cash, announced, ex = number(matrix[0][i]), number(matrix[1][i]), exdate(matrix[2][i])
        rows.append({'report_period': period, 'reported_implemented_cash': cash,
                     'reported_announced_cash': announced, 'ex_date': ex,
                     'inside_effective_window': None if ex is None else start <= ex <= end,
                     'cash_event_eligible': False,
                     'reason': 'Period amount and declared amount require event-scope confirmation; never repeat as daily cash'})
    return {'instrument': symbol, 'status': 'observed_period_rows' if rows else 'empty_success',
            'time_axis': 'provider_report_period_not_ex_date', 'effective_window': [start, end],
            'rows': rows, 'observed_ex_dates_in_window': sorted({r['ex_date'] for r in rows if r['inside_effective_window']}),
            'complete_action_coverage': False, 'historical_PIT_certified': False}


def corroborate(normalized, event):
    if normalized['instrument'] != event['instrument']:
        raise ValueError('Event security mismatch')
    matches = [r['report_period'] for r in normalized['rows'] if r['ex_date'] == event['ex_date']]
    return {'instrument': event['instrument'], 'event_id': event['event_id'],
            'ex_date': event['ex_date'], 'wind_ex_date_confirmed': bool(matches),
            'wind_report_periods': matches,
            'cash_amount_confirmed_by_wind': False, 'historical_PIT_certified': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report-date', required=True); p.add_argument('--symbol', required=True)
    p.add_argument('--receipt', type=Path); p.add_argument('--query-start')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    job = plan(a.symbol, a.report_date, a.query_start)
    if a.receipt:
        day = date.fromisoformat(a.report_date)
        raw = a.receipt.read_bytes()
        result = inspect(json.loads(raw), a.symbol, (day-timedelta(days=63)).isoformat(), (day-timedelta(days=3)).isoformat())
        result['source'] = {'path': str(a.receipt.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}
    else:
        result = job
    with a.output.open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
    if json.loads(a.output.read_text()) != result:
        raise RuntimeError('Output readback failed')


if __name__ == '__main__':
    main()

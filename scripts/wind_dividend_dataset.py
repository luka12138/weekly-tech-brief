#!/usr/bin/env python3
"""Plan code-generator-verified WSET requests and inspect immutable receipts.

This adapter never turns an empty response, missing action, or retrieval date
into evidence of no dividends or a historical database version.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

TABLE = 'cashandstockdividend'
RATE = 'Current Rate'  # Preserve the literal space from Wind's code generator.
REQUIRED = {'ex-rights ex-dividend date', 'dividend per share pre-tax', 'period'}
ROOT = Path(__file__).resolve().parents[1]


def options(value):
    result = {}
    for pair in value.split(';'):
        if not pair:
            continue
        key, sep, val = pair.partition('=')
        if not sep or not val or key in result:
            raise ValueError('Malformed or duplicate Wind option')
        result[key] = val
    return result


def plan(symbol, currency, start, end, request_id):
    begin, finish = date.fromisoformat(start), date.fromisoformat(end)
    if begin > finish:
        raise ValueError('Invalid retrieval window')
    if not symbol or any(x in symbol for x in ';=,') or currency not in {'USD', 'KRW', 'TWD', 'CNY'}:
        raise ValueError('Invalid security or currency')
    return {'id': request_id, 'method': 'wset', 'args': [TABLE,
            f'startdate={begin:%Y%m%d};enddate={finish:%Y%m%d};windcode={symbol};'
            f'currency={currency};exchange rate={RATE};exclude special dividend=No;']}


def explicit_date(value):
    if not isinstance(value, str):
        raise ValueError('Missing explicit event date')
    return datetime.fromisoformat(value).date().isoformat()


def amount(value):
    if isinstance(value, (bool, dict)) or value is None:
        raise ValueError('Missing/nonfinite cash amount')
    try:
        out = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('Invalid cash amount') from exc
    if not out.is_finite() or out <= 0:
        raise ValueError('Nonpositive or nonfinite cash amount')
    return format(out, 'f')


def inspect(receipt, symbol, currency, start, end):
    """Parse field-major WSET data, preserving query and ex-date windows separately."""
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError('Invalid event window')
    request = receipt.get('request') or {}
    args = request.get('args') or []
    if request.get('method') != 'wset' or len(args) != 2 or args[0] != TABLE:
        raise ValueError('Not a verified cashandstockdividend request')
    params = options(args[1])
    if params.get('windcode') != symbol or params.get('currency') != currency:
        raise ValueError('Security/currency mismatch')
    if params.get('exchange rate') != RATE or params.get('exclude special dividend') != 'No':
        raise ValueError('Request differs from verified code-generator options')
    query_start = datetime.strptime(params['startdate'], '%Y%m%d').date()
    query_end = datetime.strptime(params['enddate'], '%Y%m%d').date()
    if query_start > query_end:
        raise ValueError('Invalid query window')
    out = receipt.get('result')
    if not isinstance(out, dict) or type(out.get('ErrorCode')) is not int:
        raise ValueError('Malformed Wind receipt')
    result = {'instrument': symbol, 'currency': currency,
              'source_provider': 'Wind', 'retrieved_at': receipt['retrieved_at'],
              'query_window': [query_start.isoformat(), query_end.isoformat()],
              'event_window': [start, end], 'query_date_semantics_certified': False,
              'events': [], 'unresolved_rows': [], 'rows_outside_event_window': [],
              'absence_of_dividends_certified': False, 'complete_cash_coverage': False,
              'complete_non_cash_actions': False, 'historical_PIT_certified': False,
              'error_code': out['ErrorCode']}
    if out['ErrorCode'] != 0:
        result.update(status='api_error', raw_error=out.get('Data'))
        return result
    fields, data = out.get('Fields'), out.get('Data')
    if fields == [] and data == []:
        result['status'] = 'empty_success'
        return result
    if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields) or not isinstance(data, list):
        raise ValueError('Missing WSET field-major table')
    fields = [f.lower() for f in fields]
    if len(set(fields)) != len(fields) or len(fields) != len(data) or not REQUIRED <= set(fields):
        raise ValueError('Missing/duplicate fields or invalid table shape')
    if not all(isinstance(col, list) for col in data) or len({len(col) for col in data}) != 1:
        raise ValueError('Ragged field-major data')
    count = len(data[0])
    codes = out.get('Codes')
    if not isinstance(codes, list) or len(codes) != count:
        raise ValueError('Record identifiers differ from table length')
    result['rows_received'] = count
    result['raw_rows'] = [dict(zip(fields, row)) for row in zip(*data)]
    seen = {}
    for i, row in enumerate(result['raw_rows']):
        try:
            day = explicit_date(row['ex-rights ex-dividend date'])
            if not start <= day <= end:
                result['rows_outside_event_window'].append({'row_index': i, 'ex_date': day})
                continue
            cash = amount(row['dividend per share pre-tax'])
            event = {'instrument': symbol, 'currency': currency, 'event_type': 'cash_dividend',
                     'cash_amount_declared_per_share': cash, 'ex_date': day,
                     'ex_date_basis': 'explicit_Wind_dataset_row',
                     'period': row['period'], 'source_row': i,
                     'source_provider': 'Wind', 'historical_PIT_certified': False}
            for key in ['plan announcement date', 'payment date', 'record date']:
                value = row.get(key)
                event[key.replace(' ', '_')] = explicit_date(value) if value is not None else None
            # Preserve missing stock/capitalization fields; do not equate them to zero.
            event['noncash_fields'] = {k: row.get(k) for k in ['capitalization per share', 'stock dividend per share']}
            identity = (symbol, day, str(row['period']), str(row.get('dividend types')))
            if identity in seen:
                if seen[identity] != cash:
                    raise ValueError('Conflicting amounts for the same event')
                continue
            seen[identity] = cash
            result['events'].append(event)
        except ValueError as exc:
            result['unresolved_rows'].append({'row_index': i, 'reason': str(exc)})
    result['status'] = ('rows_require_review' if result['unresolved_rows'] else
                        'observed_cash_events' if result['events'] else
                        'no_rows_in_event_window' if count else 'empty_success')
    return result


def write_new(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as out:
        json.dump(payload, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write('\n')
    if json.loads(path.read_text()) != payload:
        raise RuntimeError('Artifact readback failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['plan', 'inspect'])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--report-date', required=True)
    parser.add_argument('--symbols', required=True)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--query-start', help='Bounded broad date window, distinct from event window')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    day = date.fromisoformat(args.report_date)
    if day.weekday() != 0:
        raise ValueError('Report date must be Monday')
    registry = json.loads((args.root/'state/market_instruments_v1.json').read_text())
    mapping = {x['symbol']: registry['markets'][x['market']]['currency']
               for x in registry['companies'] if x.get('symbol')}
    mapping['600519.SH'] = 'CNY'  # Explicit code-generator diagnostic control only.
    symbols = args.symbols.split(',')
    if len(symbols) != len(set(symbols)) or any(s not in mapping for s in symbols):
        raise ValueError('Unknown or duplicate securities')
    end = (day-timedelta(days=3)).isoformat()
    start = (day-timedelta(days=63)).isoformat()
    if args.mode == 'plan':
        if not args.query_start:
            raise ValueError('Provide an explicit query start; endpoint date semantics are not certified')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        payload = [plan(s, mapping[s], args.query_start, end, f'cashset_{s.replace(".","_")}_{stamp}') for s in symbols]
    else:
        if not args.receipt or len(symbols) != 1:
            raise ValueError('Inspect requires one security and its immutable receipt')
        raw = args.receipt.read_bytes()
        payload = inspect(json.loads(raw), symbols[0], mapping[symbols[0]], start, end)
        payload['source'] = {'path': str(args.receipt.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}
    write_new(args.output, payload)
    print(args.output)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Normalize cash dividend events and resolve unusable Wind fields with provenance."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re


def api_date(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Missing explicit dividend date')
    return datetime.strptime(value.strip(), '%m/%d/%Y').date().isoformat()


def cash_amount(value):
    if not isinstance(value, str) or not re.fullmatch(r'\$?\d+(?:\.\d+)?', value.strip()):
        raise ValueError('Missing or invalid cash amount')
    try:
        result = Decimal(value.strip().removeprefix('$'))
    except InvalidOperation as exc:
        raise ValueError('Invalid decimal cash amount') from exc
    if not result.is_finite() or result <= 0:
        raise ValueError('Cash event amount must be positive; unknown is not zero')
    return format(result, 'f')


def normalize_nasdaq(payload, symbol, currency, start, end):
    """A received empty table is distinct from a declared absence of dividends."""
    if currency != 'USD' or not symbol.endswith('.O'):
        raise ValueError('This route is limited to registered USD Nasdaq securities')
    begin, finish = date.fromisoformat(start), date.fromisoformat(end)
    if begin > finish:
        raise ValueError('Invalid observation window')
    if not isinstance(payload, dict) or (payload.get('status') or {}).get('rCode') != 200:
        raise ValueError('Nasdaq application request failed, regardless of HTTP success')
    data = payload.get('data')
    if not isinstance(data, dict):
        return {'status': 'unavailable', 'events': [], 'reason': 'No structured dividend dataset',
                'absence_of_dividends_certified': False}
    table = data.get('dividends')
    if isinstance(table, dict) and table.get('rows') is None:
        return {'status':'no_history_supplied','events':[],
                'reason':'Exchange returned no cash dividend history; issuer confirmation is required to establish no dividends',
                'absence_of_dividends_certified':False,'complete_non_cash_actions':False,
                'historical_PIT_certified':False}
    if not isinstance(table, dict) or not isinstance(table.get('rows'), list):
        return {'status': 'unavailable', 'events': [], 'reason': 'Missing dividend history rows',
                'absence_of_dividends_certified': False}
    rows = table['rows']; events = []; outside = []; seen = {}; unresolved = []; known_dates=[]
    for index,row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('Invalid dividend row')
        try:
            ex_date = api_date(row.get('exOrEffDate'))
        except ValueError:
            unresolved.append({'row_index':index,'reason':'Missing explicit ex-date; cannot locate this row in or outside the window'})
            continue
        known_dates.append(ex_date)
        if not begin <= date.fromisoformat(ex_date) <= finish:
            outside.append(ex_date)
            continue
        if row.get('type', '').strip().lower() != 'cash':
            raise ValueError('Unsupported event type requires a separate typed adapter')
        if row.get('currency') != currency:
            raise ValueError('Cash dividend currency is absent or differs from security currency')
        declaration = api_date(row.get('declarationDate'))
        record = api_date(row.get('recordDate')); payment = api_date(row.get('paymentDate'))
        if declaration > ex_date or payment < ex_date:
            raise ValueError('Contradictory dividend dates')
        event = {'instrument': symbol, 'event_type': 'cash_dividend',
                 'cash_amount_declared_per_share': cash_amount(row.get('amount')),
                 'currency': currency, 'ex_date': ex_date, 'ex_date_basis': 'explicit_exchange_api_row',
                 'declaration_date': declaration, 'record_date': record, 'payment_date': payment,
                 'amount_adjusted_for_later_splits': False}
        identity = '|'.join([symbol, event['event_type'], ex_date, declaration, record, payment])
        event['event_id'] = hashlib.sha256(identity.encode()).hexdigest()[:24]
        version = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
        event['event_version_sha256'] = version
        if event['event_id'] in seen:
            if seen[event['event_id']] != version:
                raise ValueError('Conflicting amounts for one dividend event; do not merge silently')
            continue
        seen[event['event_id']] = version
        events.append(event)
    events.sort(key=lambda x:(x['ex_date'],x['event_id']))
    return {'status': 'observed_cash_events' if events else 'no_rows_in_window' if rows else 'empty_history',
            'events': events, 'history_rows_received': len(rows), 'rows_outside_window': len(outside),
            'oldest_received_ex_date': min(known_dates, default=None),
            'unresolved_history_rows':unresolved,
            'absence_of_dividends_certified': False,
            'complete_non_cash_actions': False, 'historical_PIT_certified': False,
            'version_basis': 'Current retrieved exchange API response; asOf or trade dates are not historical version certification'}


def wind_field_status(receipt, symbol, field):
    out = receipt.get('result') or {}
    if out.get('ErrorCode') != 0:
        return 'api_error'
    if out.get('Codes') != [symbol] or out.get('Fields') != [field.upper()]:
        return 'identity_or_field_mismatch'
    values = out.get('Data')
    if values == [[None]] or values == [[]] or not values:
        return 'empty_success'
    if not isinstance(values,list) or len(values)!=1 or not isinstance(values[0],list) or len(values[0])!=1:
        return 'malformed_value'
    value=values[0][0]
    if isinstance(value,str) and not value.strip():
        return 'empty_success'
    if isinstance(value,float) and not math.isfinite(value) or isinstance(value,dict) and 'nonfinite' in value:
        return 'nonfinite_value'
    return 'returned_value_requires_semantic_validation'


def resolve_fields(events, symbol, wind_receipts, source_reference):
    """Return per-event values, never invent a latest event or relabel its provider."""
    out = []
    for event in events:
        if event['instrument'] != symbol:
            raise ValueError('Event identity mismatch')
        row = {'event_id': event['event_id'], 'instrument': symbol, 'fields': {}}
        for wind_field, key in [('div_cashbeforetax','cash_amount_declared_per_share'), ('div_exdate','ex_date')]:
            receipt = wind_receipts.get(wind_field)
            if receipt and wind_field_status(receipt, symbol, wind_field) not in {'empty_success','api_error','nonfinite_value'}:
                raise ValueError('Nonempty or mismatched Wind field needs event-scope reconciliation before fallback')
            row['fields'][wind_field] = {
                'value': event[key], 'status': 'resolved_from_exchange_cash_declaration',
                'source_provider': 'Nasdaq', 'source': source_reference,
                'standard_field': key,
                'assignment_to_original_wind_field': False,
                'wind_field_scope': 'specified_dividend_year_implemented_plan' if key.startswith('cash') else 'provider_report_period_row',
                'raw_wind_status': wind_field_status(receipt, symbol, wind_field) if receipt else 'not_requested',
                'semantic_basis': 'Declared cash per share before investor withholding' if key.startswith('cash') else event['ex_date_basis'],
                'historical_PIT_certified': False,
            }
        out.append(row)
    return out

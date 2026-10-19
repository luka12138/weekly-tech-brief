#!/usr/bin/env python3
"""Validate receipt-backed price observations without granting historical PIT status."""
from datetime import date, timedelta
import hashlib
import json
import math
import statistics


def need(ok, message):
    if not ok:
        raise ValueError(message)


def read_ref(root, ref):
    need(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'invalid observation receipt reference')
    path = (root/ref['path']).resolve()
    need(path.is_relative_to(root.resolve()) and path.is_file(), 'observation receipt missing or outside root')
    raw = path.read_bytes()
    need(hashlib.sha256(raw).hexdigest() == ref['sha256'], 'observation receipt hash mismatch')
    receipt = json.loads(raw)
    need(receipt['result']['ErrorCode'] == 0, 'failed API call is not price data')
    return receipt


def column(receipt, code, field):
    out = receipt['result']
    need(code in out['Codes'] and field in out['Fields'], 'receipt code/field mismatch')
    if receipt['request']['method'] == 'wss':
        return [out['Data'][out['Fields'].index(field)][out['Codes'].index(code)]]
    need(len(out['Codes']) == 1 or len(out['Fields']) == 1, 'ambiguous Wind result shape')
    index = out['Codes'].index(code) if len(out['Fields']) == 1 else out['Fields'].index(field)
    return out['Data'][index]


def calculate_price_observation(raw, cutoff, root):
    need(set(raw) == {'instrument', 'session_dates', 'closes', 'benchmark_closes', 'provenance'}, 'unexpected observation fields')
    instrument = raw['instrument']
    need(set(instrument) == {'symbol', 'venue', 'currency', 'benchmark', 'calendar', 'price_basis'}, 'invalid observation instrument')
    need(all(isinstance(v, str) and v.strip() for v in instrument.values()), 'missing observation identity')
    need(instrument['price_basis'] == 'unadjusted_close_price_return', 'price observations must not claim total returns')
    expected_calendar = {'NASDAQ': 'NYSE', 'KRX': 'KSE', 'TWSE': 'TWSE'}.get(instrument['venue'])
    need(expected_calendar is None or instrument['calendar'] == expected_calendar, 'venue uses a different market calendar')
    dates, closes, bench = raw['session_dates'], raw['closes'], raw['benchmark_closes']
    need(isinstance(dates, list) and 2 <= len(dates) <= 61, 'observation requires 2-61 closes')
    need(dates == sorted(set(dates)), 'observation dates must be unique and ascending')
    parsed = [date.fromisoformat(x) for x in dates]
    need(all(d < cutoff.date() for d in parsed), 'future observation date')
    need(len(closes) == len(dates) == len(bench), 'observation vector lengths differ')
    finite = lambda v: type(v) in (int, float) and math.isfinite(v) and v > 0
    need(all(finite(v) for v in closes), 'missing/nonfinite/nonpositive stock close')
    need(all(v is None or finite(v) for v in bench), 'invalid benchmark close')
    provenance = raw['provenance']
    need(set(provenance) == {'stock', 'benchmark', 'calendar', 'stock_identity', 'benchmark_identity'}, 'observation provenance required')
    stock = read_ref(root, provenance['stock'])
    need(stock['request']['method'] == 'wsd', 'expected WSD price receipt')
    options = dict(item.split('=', 1) for item in stock['request']['args'][4].split(';') if '=' in item)
    need(options.get('PriceAdj') == 'U', 'stock price receipt is adjusted')
    need(options.get('Currency') == instrument['currency'], 'stock currency must be explicit')
    need(options.get('TradingCalendar') == instrument['calendar'], 'stock calendar mismatch')
    need(stock['result']['Times'] == dates and column(stock, instrument['symbol'], 'CLOSE') == closes, 'normalized stock differs from raw receipt')
    calendar = read_ref(root, provenance['calendar'])
    need(calendar['request']['method'] == 'tdays' and calendar['result']['Times'] == dates, 'incomplete actual calendar')
    identity = read_ref(root, provenance['stock_identity'])
    name = column(identity, instrument['symbol'], 'SEC_NAME')
    need(any(isinstance(x, str) and x.strip() and '退市' not in x for x in name), 'stock identity unavailable')
    if provenance['benchmark'] is None:
        benchmark_name = '基准未取得'
        need(all(v is None for v in bench) and provenance['benchmark_identity'] is None, 'missing benchmark must remain missing')
    else:
        benchmark = read_ref(root, provenance['benchmark'])
        opts = dict(item.split('=', 1) for item in benchmark['request']['args'][4].split(';') if '=' in item)
        need(opts.get('PriceAdj') == 'U' and opts.get('Currency') == instrument['currency'], 'benchmark price basis/currency differs')
        need(opts.get('TradingCalendar') == instrument['calendar'], 'benchmark calendar differs')
        need(benchmark['result']['Times'] == dates and column(benchmark, instrument['benchmark'], 'CLOSE') == bench, 'normalized benchmark differs from raw receipt')
        identity = read_ref(root, provenance['benchmark_identity'])
        name = column(identity, instrument['benchmark'], 'SEC_NAME')
        need(any(isinstance(x, str) and x.strip() and '退市' not in x for x in name), 'benchmark identity unavailable or retired')
        benchmark_name = name[0]
    returns = [closes[i]/closes[i-1]-1 for i in range(1, len(dates))]
    benchmarks = [bench[i]/bench[i-1]-1 if bench[i] is not None and bench[i-1] is not None else None for i in range(1, len(dates))]
    indices = [i for i, d in enumerate(parsed[1:]) if cutoff.date()-timedelta(days=7) <= d]
    logs = [math.log1p(v) for v in returns]
    rv = lambda values: statistics.stdev(values[-20:])*math.sqrt(252) if len(values) >= 20 else None
    current, prior = rv(logs), rv(logs[:indices[0]]) if indices else None
    week = math.prod(1+returns[i] for i in indices)-1 if indices else None
    base = math.prod(1+benchmarks[i] for i in indices)-1 if indices and all(benchmarks[i] is not None for i in indices) else None
    return {'week_return': week, 'excess_return': week-base if week is not None and base is not None else None,
            'rv20': current, 'rv20_change': current-prior if current is not None and prior is not None else None,
            'week_shock': math.sqrt(252*statistics.mean(logs[i]**2 for i in indices)) if indices else None,
            'sessions': len(indices), 'last_close': dates[-1], 'last_close_price': closes[-1],
            'instrument': instrument, 'benchmark_name': benchmark_name, 'basis': 'price_observation', 'pit_qualified': False,
            'quote_count': len(closes), 'return_count': len(returns),
            'previous_return_count': indices[0] if indices else 0}

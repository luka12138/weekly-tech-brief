"""Compare explicitly supplied cash conventions; never infer missing dividends.

Reference-price adjustment and ex-close reinvestment coincide only in special
cases. Diagnostic arithmetic does not certify action completeness or vintages.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


def finite(value, allow_zero=False):
    if isinstance(value, bool) or value is None:
        raise ValueError('A numeric observed value is required')
    try:
        n = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('Invalid number') from exc
    if not n.is_finite() or n < 0 or (not allow_zero and n == 0):
        raise ValueError('Invalid numeric domain')
    return n


def cash_comparison(previous_close, ex_close, cash_per_share):
    previous, current = finite(previous_close), finite(ex_close)
    cash = finite(cash_per_share, allow_zero=True)
    if cash >= previous:
        raise ValueError('Nonpositive ex-reference price; requires separate handling')
    close_reinvestment = (current + cash) / previous - 1
    reference_adjustment = current / (previous - cash) - 1
    return {'ex_close_reinvestment_return': str(close_reinvestment),
            'ex_reference_adjustment_return': str(reference_adjustment),
            'difference_basis_points': str((reference_adjustment-close_reinvestment)*10000),
            'scope': 'one supplied cash event; no other action assumed in this diagnostic',
            'complete_total_return_certified': False, 'historical_PIT_certified': False}


def weekly_benchmark_comparison(price_dates, price_closes, total_dates, total_closes, report_date):
    day = date.fromisoformat(report_date)
    if day.weekday() != 0:
        raise ValueError('Report date must be Monday')
    dates = list(price_dates)
    if dates != list(total_dates) or dates != sorted(set(dates)):
        raise ValueError('Benchmark calendars must match exactly')
    if len(dates) != len(price_closes) or len(dates) != len(total_closes):
        raise ValueError('Benchmark vector length mismatch')
    if any(date.fromisoformat(d) >= day for d in dates):
        raise ValueError('Future benchmark values')
    first = (day-timedelta(days=7)).isoformat()
    week = [i for i, d in enumerate(dates) if d >= first]
    if not week or week[0] == 0:
        raise ValueError('Report-week sessions and prior close required')
    prices = [finite(v) for v in price_closes]
    totals = [finite(v) for v in total_closes]
    start = week[0]-1
    price_return = prices[-1]/prices[start]-1
    total_return = totals[-1]/totals[start]-1
    return {'price_start': dates[start], 'price_end': dates[-1], 'sessions': len(week),
            'price_index_return': str(price_return), 'provider_total_return': str(total_return),
            'total_minus_price_basis_points': str((total_return-price_return)*10000),
            'basis': 'current retrieved provider index observations; conventions remain separate',
            'historical_PIT_certified': False}

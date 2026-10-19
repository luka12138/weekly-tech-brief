"""Exact input dependencies for weekly returns and rolling RV; no qualification by inference."""
from datetime import date, timedelta


def metric_windows(session_dates, report_date, rv_sessions=20):
    days = list(session_dates); cutoff = date.fromisoformat(report_date)
    if type(rv_sessions) is not int or rv_sessions < 2:
        raise ValueError('RV needs at least two return observations')
    if days != sorted(set(days)) or any(date.fromisoformat(d) >= cutoff for d in days):
        raise ValueError('Duplicate, unordered, or future sessions')
    first_week = (cutoff - timedelta(days=7)).isoformat()
    week_indices = [i for i, d in enumerate(days) if d >= first_week]
    if not week_indices or week_indices[0] == 0:
        raise ValueError('A report-week session and previous close are required')
    i = week_indices[0]
    def window(first_return, last_return):
        if first_return < 1 or last_return < first_return:
            return {'status': 'insufficient_samples', 'price_dates': [], 'return_dates': []}
        return {'status': 'available', 'price_dates': days[first_return-1:last_return+1],
                'return_dates': days[first_return:last_return+1]}
    result = {'week_return': window(i, len(days)-1),
              'rv20': window(len(days)-rv_sessions, len(days)-1),
              'prior_rv20': window(i-rv_sessions, i-1)}
    current, prior = result['rv20'], result['prior_rv20']
    result['rv20_change'] = {'status': 'available' if current['status'] == prior['status'] == 'available'
                            else 'insufficient_samples',
                            'price_dates': sorted(set(current['price_dates'] + prior['price_dates'])),
                            'return_dates': sorted(set(current['return_dates'] + prior['return_dates']))}
    return result


def action_gap_impact(windows, effective_date=None, effective_date_bounds=None):
    """A known action's missing amount affects only returns including its ex-session.

An unbounded unknown date affects every available window. An evidenced inclusive
date interval can exclude a gap without inventing an exact ex-date. False means
ONLY this specified gap is outside the window, not that other actions are absent.
"""
    if effective_date is not None and effective_date_bounds is not None:
        raise ValueError('Use an exact date or an interval, not both')
    if effective_date is not None:
        date.fromisoformat(effective_date)
    lower = upper = None
    if effective_date_bounds is not None:
        if not isinstance(effective_date_bounds, dict):
            raise ValueError('Effective-date interval must be an object')
        lower, upper = (effective_date_bounds.get(k) for k in ['earliest', 'latest'])
        if lower is None and upper is None:
            raise ValueError('An interval needs at least one finite boundary')
        for boundary in [lower, upper]:
            if boundary is not None: date.fromisoformat(boundary)
        if lower is not None and upper is not None and lower > upper:
            raise ValueError('Inverted effective-date interval')
        basis = effective_date_bounds.get('evidence_basis')
        if not isinstance(basis, str) or not basis.strip():
            raise ValueError('A date bound requires an explicit evidence basis')
    def overlaps(days):
        if effective_date is not None: return effective_date in days
        if effective_date_bounds is None: return True
        return any((lower is None or d >= lower) and (upper is None or d <= upper) for d in days)
    return {metric: {'this_gap_affects_metric': None if window['status'] != 'available' else
                     overlaps(window['return_dates']),
                     'other_action_coverage_certified': False,
                     'historical_PIT_certified': False}
            for metric, window in windows.items()}


def qualify_metrics(windows, evidence, gaps=()):
    """Require explicit true evidence per metric; an index gap does not block stock RV.

Coverage means actual actions affecting that metric's input interval, not merely a
publication-date filing list. Qualifying one metric never qualifies another one.
"""
    mapping = {'week_return': 'week_return', 'excess_return': 'week_return',
               'rv20': 'rv20', 'rv20_change': 'rv20_change'}
    result = {}
    for metric, window_name in mapping.items():
        window = windows[window_name]; proof = evidence.get(metric, {})
        blockers = []
        if window['status'] != 'available': blockers.append('insufficient_samples')
        required = ['cash_action_coverage', 'noncash_action_coverage', 'cash_reinvestment_convention']
        if metric == 'excess_return':
            required += ['matching_gross_benchmark', 'matching_currency_and_calendar',
                         'benchmark_convention_compatibility']
        blockers += [key for key in required if proof.get(key) is not True]
        for gap in gaps:
            effect = action_gap_impact({window_name: window}, gap.get('ex_date'),
                                       gap.get('effective_date_bounds'))[window_name]
            if effect['this_gap_affects_metric'] is not False:
                blockers.append('action_gap:' + gap['id'])
        vintage_keys = ['historical_price_version', 'historical_action_version']
        if metric == 'excess_return': vintage_keys.append('historical_benchmark_version')
        vintage = [key for key in vintage_keys if proof.get(key) is not True]
        result[metric] = {'current_version_method_eligible': not blockers,
                          'strict_PIT_eligible': not (blockers or vintage),
                          'method_blockers': blockers, 'vintage_blockers': vintage,
                          'price_dates': window['price_dates'], 'return_dates': window['return_dates']}
    return result

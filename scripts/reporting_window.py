"""Versioned Shanghai publication windows; never rewrite legacy cutoffs."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo('Asia/Shanghai')
ACTIVATION = date(2026, 10, 19)
LEGACY = 'shanghai_midnight_v1'
MORNING = 'shanghai_monday_0900_v2'
MARKER = '<!-- cutoff-policy: ' + MORNING + ' -->'


def reporting_window(day, policy=None):
    day = date.fromisoformat(day) if isinstance(day, str) else day
    if day.weekday() != 0:
        raise ValueError('report date must be Monday')
    # Existing October 19 snapshots remain inspectable under their old contract.
    policy = policy or LEGACY
    if policy not in {LEGACY, MORNING}:
        raise ValueError('unknown cutoff policy')
    if policy == MORNING and day < ACTIVATION:
        raise ValueError('09:00 policy cannot backdate legacy reports')
    if policy == LEGACY and day > ACTIVATION:
        raise ValueError('new reports require the Monday 09:00 cutoff policy')
    cutoff = datetime.combine(day, time(9 if policy == MORNING else 0), SHANGHAI)
    start = cutoff - timedelta(days=7)
    if policy == MORNING and day == ACTIVATION:
        # Transition from the preceding issue's midnight cutoff without a gap.
        start = datetime.combine(day - timedelta(days=7), time.min, SHANGHAI)
    return start, cutoff


def default_policy(day):
    return MORNING if date.fromisoformat(str(day)) >= ACTIVATION else LEGACY


def validate_declared_window(data, report_text=None, cutoff_key='cutoff_exclusive'):
    policy = data.get('cutoff_policy', LEGACY)
    start, cutoff = reporting_window(data['report_date'], policy)
    declared = datetime.fromisoformat(data[cutoff_key].replace('Z', '+00:00'))
    if declared != cutoff:
        raise ValueError('cutoff does not match declared reporting-window policy')
    if report_text is not None and ((MARKER in report_text) != (policy == MORNING)):
        raise ValueError('report and evidence cutoff policies differ')
    return start, cutoff

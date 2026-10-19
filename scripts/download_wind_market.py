#!/usr/bin/env python3
"""Prepare or execute one bounded, read-only Wind session for the registered markets."""
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from reporting_window import default_policy, reporting_window

ROOT = Path(__file__).resolve().parents[1]


def prepare(root, report_date, registry_path):
    day = date.fromisoformat(report_date)
    if day.weekday() != 0:
        raise ValueError('Report date must be Monday')
    registry = json.loads(registry_path.read_text())
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    (root/'logs').mkdir(exist_ok=True)
    frozen_registry = root/'logs'/f'{report_date}_wind_registry_{stamp}.json'
    frozen_registry.write_bytes(registry_path.read_bytes())
    prefix = f'market_{report_date.replace("-", "")}_{stamp}'
    end = day-timedelta(days=3)  # Last Friday; actual calendars remain authoritative.
    start = day-timedelta(days=63)  # Plenty of pre-week samples for both RV20 windows.
    jobs = []
    def add(role, method, args, **kwargs):
        identity = prefix+'_'+role
        jobs.append({'id': identity, 'method': method, 'args': args, **kwargs})
        return identity
    control_day = end.isoformat()
    add('control_name', 'wss', ['600036.SH', 'sec_name', 'tradeDate='+control_day.replace('-', '')], require_nonempty=True)
    add('control_close', 'wsd', ['600036.SH', 'close', control_day, control_day, 'PriceAdj=U;TradingCalendar=SSE;Currency=CNY'], require_nonempty=True)
    codes = [c['symbol'] for c in registry['companies'] if c['symbol']]
    codes += [g['benchmark'] for g in registry['markets'].values()]
    identity = add('identity', 'wss', [','.join(codes), 'sec_name', 'tradeDate='+control_day.replace('-', '')])
    groups = {}
    for key, group in registry['markets'].items():
        symbols = [c['symbol'] for c in registry['companies'] if c['market'] == key]
        options = f"PriceAdj=U;Days=Trading;Fill=Blank;TradingCalendar={group['calendar']};Currency={group['currency']}"
        groups[key] = {
            'stock': add(key+'_stock', 'wsd', [','.join(symbols), 'close', start.isoformat(), end.isoformat(), options]),
            'benchmark': add(key+'_benchmark', 'wsd', [group['benchmark'], 'close', start.isoformat(), end.isoformat(), options]),
            'calendar': add(key+'_calendar', 'tdays', [start.isoformat(), end.isoformat(), 'TradingCalendar='+group['calendar']]),
        }
    policy = default_policy(report_date)
    window_start, cutoff = reporting_window(report_date, policy)
    manifest = {'schema_version': 1, 'report_date': report_date, 'prepared_at': datetime.now(timezone.utc).isoformat(),
                'cutoff_policy': policy, 'cutoff_exclusive': cutoff.isoformat(), 'window_start': window_start.isoformat(),
                'registry': {'path': str(frozen_registry.relative_to(root)), 'sha256': hashlib.sha256(frozen_registry.read_bytes()).hexdigest()},
                'prefix': prefix, 'window': [start.isoformat(), end.isoformat()], 'identity': identity, 'groups': groups,
                'jobs': jobs, 'status': 'prepared_not_executed'}
    out = root/'logs'/f'{report_date}_wind_download_{stamp}.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    job_path = out.with_suffix('.jobs.json')
    job_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2)+'\n')
    return out, job_path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report-date', required=True)
    p.add_argument('--registry', type=Path, default=ROOT/'state/market_instruments_v1.json')
    p.add_argument('--execute', action='store_true', help='Start one worker process; user may need to log in to Wind API')
    args = p.parse_args()
    manifest, jobs = prepare(ROOT, args.report_date, args.registry.resolve())
    print(json.dumps({'manifest': str(manifest), 'jobs': str(jobs), 'mode': 'execute' if args.execute else 'prepare_only'}, ensure_ascii=False), flush=True)
    if args.execute:
        subprocess.run([sys.executable, '-u', str(ROOT/'scripts/wind_readonly_session.py'), '--jobs', str(jobs)], check=True)


if __name__ == '__main__':
    main()

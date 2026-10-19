#!/usr/bin/env python3
"""Batch Wind prices, adjustment diagnostics, and calendars into a weekly store.

prepare prints JSONL for an already authenticated worker. execute starts exactly
one official SDK worker. resume only ingests matching saved receipts; it never
quietly re-queries or overwrites the sole selected issue version.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from download_wind_market import prepare
from weekly_data_store import create_run, ingest, seal, verify_run, immutable, encode

ROOT = Path(__file__).resolve().parents[1]


def prepare_pipeline(root, store, day, purpose):
    download, _ = prepare(root, day, root/'state/market_instruments_v1.json')
    data = json.loads(download.read_text()); jobs = data['jobs'][:]
    registry = json.loads((root/data['registry']['path']).read_text())
    for name, group in registry['markets'].items():
        codes = ','.join(c['symbol'] for c in registry['companies'] if c['market'] == name)
        options = f"Days=Trading;Fill=Blank;TradingCalendar={group['calendar']};Currency={group['currency']}"
        fields=[('factor','adjfactor','U')]
        if purpose=='diagnostic':
            fields += [('backward','close','B'),('change','pct_chg','U')]
        for label, field, adjustment in fields:
            jobs.append({'id':data['prefix']+'_'+name+'_'+label, 'method':'wsd',
                         'args':[codes,field,*data['window'],f'PriceAdj={adjustment};'+options]})
    jobs.append({'id':data['prefix']+'_nasdaq_total_return','method':'wsd',
                 'args':['XCMP.GI','close',*data['window'],'PriceAdj=U;Days=Trading;Fill=Blank;TradingCalendar=NYSE;Currency=USD']})
    run = create_run(store, day, jobs, purpose=purpose)
    immutable(run/'download_manifest.json', encode(data))
    immutable(run/'jobs.json', encode(jobs))
    immutable(run/'jobs.jsonl', ''.join(json.dumps(j,ensure_ascii=False)+'\n' for j in jobs).encode())
    return run


def resume(root, store, run):
    if (run/'manifest.json').exists():
        return verify_run(store,run)
    plan=json.loads((run/'run.json').read_text()); missing=[]
    for job in plan['jobs']:
        receipt=root/'logs/wind_raw'/(job['id']+'.json')
        if receipt.exists():
            ingest(store,run,json.loads(receipt.read_text()))
        else: missing.append(job['id'])
    if missing:
        return {'transport_complete':False,'missing':missing,'resume_from_saved_responses':True}
    return seal(store,run)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=['prepare','execute','resume'])
    p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--store',type=Path,default=ROOT/'state/weekly_data')
    p.add_argument('--report-date');p.add_argument('--run',type=Path)
    p.add_argument('--purpose',choices=['scheduled','late_rerun','diagnostic'],default='diagnostic')
    a=p.parse_args();root=a.root.resolve();store=a.store.resolve()
    if a.operation=='resume':
        if not a.run:p.error('--run required')
        run=a.run.resolve();result=resume(root,store,run)
    else:
        if a.run:
            if a.operation!='execute':p.error('--run is only used for execute/resume')
            run=a.run.resolve()
        else:
            if not a.report_date:p.error('--report-date required')
            run=prepare_pipeline(root,store,a.report_date,a.purpose)
        print(json.dumps({'run':str(run),'jobs':str(run/'jobs.jsonl')},ensure_ascii=False),flush=True)
        if a.operation=='prepare':return
        prior=resume(root,store,run)
        if prior['transport_complete']:
            print(json.dumps({'run':str(run),'requests':len(prior['entries']),'reused_sealed_run':True},ensure_ascii=False));return
        jobs=json.loads((run/'run.json').read_text())['jobs']
        pending=[j for j in jobs if j['id'] in prior['missing']]
        pending_path=run/('pending_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.json')
        immutable(pending_path,encode(pending))
        completed=subprocess.run([sys.executable,'-u',str(root/'scripts/wind_readonly_session.py'),'--jobs',str(pending_path),
                                  '--store',str(store),'--run',str(run)])
        result=resume(root,store,run)
        if completed.returncode:result['worker_exit_code']=completed.returncode
    print(json.dumps({'run':str(run),'transport_complete':result['transport_complete'],
                      'requests':len(result.get('entries',[])), 'statuses':{x['id']:x['status'] for x in result.get('entries',[])},
                      'missing':result.get('missing',[])},ensure_ascii=False))
    if not result['transport_complete']:sys.exit(2)


if __name__=='__main__': main()

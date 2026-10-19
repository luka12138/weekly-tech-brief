#!/usr/bin/env python3
"""Measure actual files, unique contents, categories and issue storage scenarios."""
import argparse
from collections import defaultdict
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path


def classify(relative):
    parts=relative.parts
    if len(parts)>3 and parts[:2]==('state','staging'):
        parts=parts[3:]
    if '.git' in parts:return 'git'
    if 'market_vault' in parts:return 'content_archive'
    if 'archives' in parts:return 'historical_archives'
    if 'tmp' in parts:return 'render_and_temporary'
    if any(x in parts for x in ['reports','output']):return 'reports'
    if 'assets' in parts:return 'graphs_and_assets'
    if any(x in parts for x in ['wind_raw','wind_official_docs']):return 'raw_market_and_method_sources'
    if 'logs' in parts:return 'evidence_and_run_logs'
    if any(x in parts for x in ['scripts','tests','docs','.agents']):return 'code_rules_tests'
    if 'state' in parts:return 'state_and_registry'
    return 'other'


def inventory(root,issue,report_date):
    root=root.resolve();issue=issue.resolve(); rows=[]; skipped=[]; inodes=set(); unique={};categories=defaultdict(lambda:{'files':0,'logical_bytes':0,'allocated_blocks_bytes':0})
    for folder,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=[x for x in dirs if not (Path(folder)/x).is_symlink()]
        for name in sorted(files):
            path=Path(folder)/name;rel=path.relative_to(root)
            if path.is_symlink():skipped.append({'path':str(rel),'reason':'symlink_not_followed'});continue
            before=path.stat();sha=hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda:source.read(1024*1024),b''):sha.update(chunk)
            after=path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('File changed during inventory: '+str(rel))
            key=(after.st_dev,after.st_ino);allocated=after.st_blocks*512 if key not in inodes else 0;inodes.add(key)
            row={'path':str(rel),'bytes':after.st_size,'allocated_blocks_bytes':allocated,'sha256':sha.hexdigest(),'category':classify(rel),'in_current_issue':path.is_relative_to(issue)}
            rows.append(row);unique.setdefault(row['sha256'],row['bytes'])
            cat=categories[row['category']];cat['files']+=1;cat['logical_bytes']+=row['bytes'];cat['allocated_blocks_bytes']+=allocated
    current=[x for x in rows if x['in_current_issue']]
    # Full current staging is a deliberately conservative observed working envelope:
    # it includes copied rules/history and diagnostic manuals, not just weekly deltas.
    full=sum(x['bytes'] for x in current)
    final=[x for x in current if x['category'] in {'reports','graphs_and_assets','state_and_registry'}]
    final_bytes=sum(x['bytes'] for x in final)
    baseline=sum(x['bytes'] for x in rows)
    scenarios=[]
    for years in [1,3,5]:
        for name,weekly in [('current_full_staging_each_week',full),('five_times_current_full_staging',full*5)]:
            projected=baseline+52*years*weekly
            scenarios.append({'years':years,'scenario':name,'weekly_assumption_bytes':weekly,
                              'one_copy_bytes':projected,'one_copy_with_30pct_headroom_bytes':int(projected*1.3),
                              'two_independent_copies_with_30pct_headroom_bytes':int(projected*2*1.3)})
    return {'schema_version':1,'measured_at':datetime.now(timezone.utc).isoformat(),'root':str(root),'issue':str(issue),
            'report_date':report_date,'files':len(rows),'logical_bytes':baseline,
            'allocated_blocks_bytes':sum(x['allocated_blocks_bytes'] for x in rows),
            'unique_content_bytes':sum(unique.values()),'unique_contents':len(unique),
            'exact_duplicate_logical_bytes':baseline-sum(unique.values()),
            'current_issue_full_logical_bytes':full,'current_issue_files':len(current),
            'current_issue_reading_and_state_bytes':final_bytes,'categories':dict(categories),'scenarios':scenarios,
            'limitations':['Allocated st_blocks are file accounting, not physical APFS clone/compression savings.',
                          'One observed issue is not a measured weekly growth distribution.',
                          'Full staging includes reused code/history, diagnostic downloads and QA.',
                          'External drives, Codex conversation logs outside this root and cloud data are not included.',
                          'No files are deleted, moved or deduplicated by this inventory.'],
            'skipped':skipped,'entries':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--issue',type=Path,required=True)
    p.add_argument('--report-date',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    d=inventory(a.root,a.issue,a.report_date)
    with a.output.open('x') as f:json.dump(d,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in d.items() if k not in {'entries','categories'}},ensure_ascii=False))

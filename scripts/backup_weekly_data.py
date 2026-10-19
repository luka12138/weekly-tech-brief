#!/usr/bin/env python3
"""Incremental verified copy of the immutable store; no formatting or deletion.

The destination is an explicit project directory on the chosen disk. Offline
backup never blocks local report generation. Each invocation records exactly
which files were checked; a backup receipt does not certify financial semantics.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import uuid

from weekly_data_store import immutable, encode


def digest_file(path):
    h=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def backup(source,destination):
    source=source.resolve();destination=destination.resolve()
    if not source.is_dir():raise ValueError('Source store is missing')
    if destination==source or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Backup must be independent of source directory')
    if not destination.parent.is_dir():raise ValueError('Destination parent unavailable; disk may be disconnected')
    entries=[];needed=0
    for src in sorted(source.rglob('*')):
        if src.is_symlink():raise ValueError('Symlink not allowed in portable backup')
        if not src.is_file() or any(x.endswith('.lock') or x.startswith('.pending-') for x in src.relative_to(source).parts):continue
        relative=src.relative_to(source);dst=destination/relative
        size=src.stat().st_size;entries.append((src,dst,str(relative),size))
        if not dst.exists():needed+=size
    if shutil.disk_usage(destination.parent).free<needed+16*1024*1024:
        raise ValueError('Insufficient destination space')
    records=[];copied=0
    for src,dst,relative,size in entries:
        digest=digest_file(src)
        if dst.exists():
            if dst.stat().st_size!=size or digest_file(dst)!=digest:
                raise ValueError('Backup conflict/corruption; preserve both and investigate: '+relative)
            status='verified_existing'
        else:
            immutable(dst,src.read_bytes())
            if digest_file(dst)!=digest:raise ValueError('Backup readback failed: '+relative)
            status='copied_and_verified';copied+=1
        records.append({'path':relative,'bytes':size,'sha256':digest,'status':status})
    receipt={'schema_version':1,'completed_at':datetime.now(timezone.utc).isoformat(),'files':records,
             'copied':copied,'verified_existing':len(records)-copied,'all_hashes_verified':True}
    path=destination/'backup_receipts'/(str(uuid.uuid4())+'.json')
    immutable(path,encode(receipt))
    return path,receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path)
    p.add_argument('--destination',required=True,type=Path);a=p.parse_args()
    path,r=backup(a.source,a.destination)
    print(json.dumps({'receipt':str(path),'copied':r['copied'],'verified_existing':r['verified_existing'],'all_hashes_verified':True},ensure_ascii=False))

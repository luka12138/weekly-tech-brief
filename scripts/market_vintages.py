#!/usr/bin/env python3
"""Append-only local content snapshots with conservative availability checks.

First preservation is stamped by this process, never supplied by the caller.
An archive proves local preservation from then onward, not earlier publication,
semantic validity, provider vintage access, or historical trading availability.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import uuid


def digest(data): return hashlib.sha256(data).hexdigest()


def timestamp(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None: raise ValueError('Timezone is required')
    return result


def safe_relative(value):
    p=PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or not p.parts: raise ValueError('Unsafe archive path')
    return p


def freeze(root, paths, vault, label):
    root=root.resolve();vault=vault.resolve();entries=[]
    inputs=sorted(set(Path(p).resolve() for p in paths))
    if not inputs: raise ValueError('Empty snapshot')
    (vault/'objects').mkdir(parents=True,exist_ok=True)
    (vault/'manifests').mkdir(exist_ok=True)
    for path in inputs:
        relative=path.relative_to(root).as_posix();safe_relative(relative)
        raw=path.read_bytes();sha=digest(raw); blob=vault/'objects'/sha[:2]/sha
        blob.parent.mkdir(exist_ok=True)
        if blob.exists():
            if digest(blob.read_bytes())!=sha: raise ValueError('Existing archive object is corrupt')
        else:
            # x creation never replaces a historical object; no mtime-based identity.
            with blob.open('xb') as output: output.write(raw)
        entries.append({'path':relative,'sha256':sha,'bytes':len(raw)})
    manifest={'schema_version':1,'id':str(uuid.uuid4()),'label':label,
              'preserved_at':datetime.now(timezone.utc).isoformat(),'entries':entries,
              'availability_basis':'local_preservation_only_not_earlier_vendor_vintage',
              'semantic_or_historical_certification':False}
    target=vault/'manifests'/(manifest['id']+'.json')
    with target.open('x') as output:json.dump(manifest,output,ensure_ascii=False,indent=2)
    verify(vault,target)
    return target,manifest


def verify(vault, manifest_path):
    data=json.loads(manifest_path.read_text());timestamp(data['preserved_at'])
    if data['schema_version']!=1 or data['availability_basis']!='local_preservation_only_not_earlier_vendor_vintage':
        raise ValueError('Unknown snapshot contract')
    seen=set()
    for entry in data['entries']:
        safe_relative(entry['path'])
        if entry['path'] in seen:raise ValueError('Duplicate archive path')
        seen.add(entry['path']);sha=entry['sha256']
        if len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha): raise ValueError('Invalid SHA-256')
        blob=vault/'objects'/sha[:2]/sha;raw=blob.read_bytes()
        if len(raw)!=entry['bytes'] or digest(raw)!=sha: raise ValueError('Archive content hash/size mismatch')
    if not seen:raise ValueError('Empty snapshot')
    return data


def availability(vault, manifest_path, cutoff):
    data=verify(vault,manifest_path)
    available=timestamp(data['preserved_at'])<timestamp(cutoff)
    return {'snapshot_id':data['id'],'cutoff_exclusive':cutoff,'preserved_at':data['preserved_at'],
            'locally_preserved_before_cutoff':available,
            'reason':'exact_frozen_files_existed_locally' if available else 'snapshot_created_at_or_after_cutoff',
            'semantic_inputs_still_require_validation':True,
            'earlier_vendor_database_version_certified':False}


def restore(vault, manifest_path, destination):
    data=verify(vault,manifest_path);destination=destination.resolve()
    if destination.exists():raise FileExistsError('Restore never overwrites an existing path')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='.weekly-restore-',dir=destination.parent))
    try:
        for entry in data['entries']:
            target=temp/entry['path'];target.parent.mkdir(parents=True,exist_ok=True)
            sha=entry['sha256'];shutil.copyfile(vault/'objects'/sha[:2]/sha,target)
            if digest(target.read_bytes())!=sha: raise ValueError('Restore readback mismatch')
        temp.rename(destination)
    except BaseException:
        shutil.rmtree(temp,ignore_errors=True);raise
    return {'restored_files':len(data['entries']),'destination':str(destination),
            'all_hashes_verified':True,'snapshot_id':data['id']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=['freeze','verify','asof','restore'])
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--vault',type=Path,required=True)
    p.add_argument('--paths-json',type=Path);p.add_argument('--label',default='weekly-market-data')
    p.add_argument('--manifest',type=Path);p.add_argument('--cutoff');p.add_argument('--destination',type=Path)
    a=p.parse_args()
    if a.operation=='freeze':
        target,data=freeze(a.root,[a.root/x for x in json.loads(a.paths_json.read_text())],a.vault,a.label)
        result={'manifest':str(target),'files':len(data['entries']),'preserved_at':data['preserved_at']}
    elif a.operation=='verify':result={'files':len(verify(a.vault,a.manifest)['entries']),'all_hashes_verified':True}
    elif a.operation=='asof':result=availability(a.vault,a.manifest,a.cutoff)
    else:result=restore(a.vault,a.manifest,a.destination)
    print(json.dumps(result,ensure_ascii=False))

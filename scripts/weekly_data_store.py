#!/usr/bin/env python3
"""Portable, append-only weekly data runs with deduplicated response payloads.

No database server, symlinks, external disk dependency, or fabricated as-of time.
Each week can select one business version. Diagnostic runs remain separate.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import tempfile
import os
import uuid

from reporting_window import default_policy, reporting_window


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def immutable(path, raw):
    """Publish complete bytes atomically; retries never replace another version."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Immutable path already has different content: '+str(path))
        return
    # mkdir + rename works on APFS and exFAT; no hardlink/symlink requirement.
    lock = path.with_name(path.name+'.lock')
    lock.mkdir()
    fd, name = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(raw); out.flush(); os.fsync(out.fileno())
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('Concurrent immutable write differs: '+str(path))
        else:
            os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)
        lock.rmdir()


def put(store, value):
    raw = encode(value); digest = sha(raw)
    immutable(Path(store)/'objects'/digest[:2]/(digest+'.json'), raw)
    return {'sha256': digest, 'bytes': len(raw)}


def get(store, ref):
    digest = ref['sha256']
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Invalid content hash')
    raw = (Path(store)/'objects'/digest[:2]/(digest+'.json')).read_bytes()
    if sha(raw) != digest or len(raw) != ref['bytes']:
        raise ValueError('Stored response hash/size mismatch')
    return json.loads(raw)


def request_key(request):
    return sha(encode({k: request[k] for k in ('method', 'args')}))


def create_run(store, day, jobs, *, purpose='diagnostic'):
    if purpose not in {'scheduled', 'late_rerun', 'diagnostic'}:
        raise ValueError('Unknown run purpose')
    ids = [x['id'] for x in jobs]
    if len(ids) != len(set(ids)) or not ids or any(not re.fullmatch('[A-Za-z0-9_-]+', x) for x in ids):
        raise ValueError('Invalid or duplicate request IDs')
    if len({request_key(x) for x in jobs}) != len(jobs):
        raise ValueError('Duplicate API requests should be batched/reused')
    if any(x['method'] not in {'wss','wsd','tdays','wset'} for x in jobs):
        raise ValueError('Read-only requests required')
    policy = default_policy(day); start, cutoff = reporting_window(day, policy)
    created = datetime.now(timezone.utc)
    requested_purpose = purpose
    if purpose == 'scheduled' and not cutoff <= created < cutoff + timedelta(minutes=1):
        purpose = 'late_rerun'
    run = {'schema_version': 1, 'run_id': str(uuid.uuid4()), 'report_date': day,
           'cutoff_policy': policy, 'cutoff_exclusive': cutoff.isoformat(),
           'window_start': start.isoformat(), 'created_at': created.isoformat(), 'purpose': purpose,
           'requested_purpose': requested_purpose,
           'jobs': jobs, 'snapshot_basis': 'one_designated_collection_batch_actual_times_retained'}
    path = Path(store)/'runs'/day/run['run_id']
    immutable(path/'run.json', encode(run))
    return path


def classify(result):
    if result.get('ErrorCode') != 0:
        return 'api_error'
    vals = [v for row in (result.get('Data') or []) for v in (row if isinstance(row, list) else [row])]
    valid = lambda v: ((isinstance(v, str) and bool(v.strip())) or
                       (type(v) in (int, float) and math.isfinite(v)))
    count = sum(valid(v) for v in vals)
    return 'empty' if not count else ('partial' if count != len(vals) else 'nonempty')


def ingest(store, run_dir, receipt):
    run_dir = Path(run_dir)
    if (run_dir/'manifest.json').exists():
        raise ValueError('Run is sealed; use a separate diagnostic run')
    run = json.loads((run_dir/'run.json').read_text())
    request = receipt['request']; jobs = {x['id']: x for x in run['jobs']}
    if request['id'] not in jobs or request_key(request) != request_key(jobs[request['id']]):
        raise ValueError('Receipt does not match planned request')
    for key in ('started_at', 'retrieved_at'):
        instant = datetime.fromisoformat(receipt[key].replace('Z', '+00:00'))
        if instant.tzinfo is None:
            raise ValueError('Actual request timestamps require timezone')
    began = datetime.fromisoformat(receipt['started_at'].replace('Z', '+00:00'))
    ended = datetime.fromisoformat(receipt['retrieved_at'].replace('Z', '+00:00'))
    if ended < began or ended > datetime.now(timezone.utc):
        raise ValueError('Invalid actual request chronology')
    # Identical provider payloads across weeks occupy one content object.
    payload = put(store, receipt['result'])
    meta = {k: v for k, v in receipt.items() if k != 'result'}
    meta.update(result_ref=payload, result_status=classify(receipt['result']), request_sha256=request_key(request))
    ref = put(store, meta)
    immutable(run_dir/'receipts'/(request['id']+'.json'), encode(ref))
    return meta


def seal(store, run_dir):
    run_dir = Path(run_dir)
    if (run_dir/'manifest.json').exists():
        return verify_run(store, run_dir)
    run = json.loads((run_dir/'run.json').read_text()); entries = []
    for request in run['jobs']:
        p = run_dir/'receipts'/(request['id']+'.json')
        if not p.exists():
            raise ValueError('Unfinished request: '+request['id'])
        ref = json.loads(p.read_text()); meta = get(store, ref); get(store, meta['result_ref'])
        entries.append({'id':request['id'], 'receipt_ref':ref, 'status':meta['result_status']})
    manifest = {'schema_version':1, 'run':run, 'sealed_at':now(), 'entries':entries,
                'transport_complete':True, 'all_nonempty':all(x['status']=='nonempty' for x in entries),
                'semantic_qualification':'requires_field_calendar_and_return_basis_validation'}
    immutable(run_dir/'manifest.json', encode(manifest))
    return verify_run(store, run_dir)


def verify_run(store, run_dir):
    run_dir = Path(run_dir); manifest = json.loads((run_dir/'manifest.json').read_text())
    if manifest['run'] != json.loads((run_dir/'run.json').read_text()):
        raise ValueError('Run plan changed after sealing')
    jobs = {j['id']:j for j in manifest['run']['jobs']}
    if len(manifest['entries']) != len(jobs) or {e['id'] for e in manifest['entries']} != set(jobs):
        raise ValueError('Manifest request inventory mismatch')
    for item in manifest['entries']:
        meta = get(store, item['receipt_ref']); result = get(store, meta['result_ref'])
        if (meta['request']['id'] != item['id'] or request_key(meta['request']) != request_key(jobs[item['id']])
                or item['status'] != classify(result)):
            raise ValueError('Manifest receipt request/status mismatch')
    return manifest


def select_issue_version(store, run_dir):
    manifest = verify_run(store, run_dir); run = manifest['run']
    if run['purpose'] == 'diagnostic' or not manifest['all_nonempty']:
        raise ValueError('Diagnostic/partial run cannot be selected as the issue data version')
    path = Path(store)/'issues'/(run['report_date']+'.json')
    raw = (Path(run_dir)/'manifest.json').read_bytes()
    selection = {'schema_version':1, 'report_date':run['report_date'], 'run_id':run['run_id'],
                 'manifest_sha256':sha(raw), 'cutoff_exclusive':run['cutoff_exclusive'],
                 'purpose':run['purpose']}
    immutable(path, encode(selection))
    return selection


def archive_artifacts(store, run_dir, root, paths, label):
    """Attach immutable code, normalized inputs, evidence, reports, and QA files."""
    verify_run(store,run_dir)
    if not re.fullmatch('[A-Za-z0-9_-]+',label): raise ValueError('Invalid artifact label')
    root=Path(root).resolve();entries=[]
    for path in sorted(set(Path(x).resolve() for x in paths)):
        name=path.relative_to(root).as_posix();raw=path.read_bytes();digest=sha(raw)
        immutable(Path(store)/'objects'/digest[:2]/(digest+'.bin'),raw)
        entries.append({'path':name,'sha256':digest,'bytes':len(raw),'object_suffix':'.bin'})
    if not entries:raise ValueError('Empty artifact archive')
    out=Path(run_dir)/'artifacts'/(label+'.json')
    immutable(out,encode({'schema_version':1,'preserved_at':now(),'entries':entries}))
    for e in entries:
        raw=(Path(store)/'objects'/e['sha256'][:2]/(e['sha256']+'.bin')).read_bytes()
        if sha(raw)!=e['sha256'] or len(raw)!=e['bytes']:raise ValueError('Artifact readback mismatch')
    return out


def restore_artifacts(store, manifest_path, destination):
    """Verify the complete archive before restoring into a new empty directory."""
    manifest = json.loads(Path(manifest_path).read_text())
    entries = manifest.get('entries', [])
    if manifest.get('schema_version') != 1 or not entries:
        raise ValueError('Invalid artifact manifest')
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('Restore destination must not exist')
    checked = []; names = set()
    for entry in entries:
        name = entry['path']; relative = PurePosixPath(name); digest = entry['sha256']
        if (not name or relative.is_absolute() or '..' in relative.parts or
                '\\' in name or ':' in name or name != relative.as_posix() or name in names):
            raise ValueError('Unsafe or duplicate restore path')
        if not re.fullmatch('[0-9a-f]{64}', digest) or entry.get('object_suffix') != '.bin':
            raise ValueError('Invalid artifact object reference')
        obj = Path(store)/'objects'/digest[:2]/(digest+'.bin')
        raw = obj.read_bytes()
        if sha(raw) != digest or len(raw) != entry['bytes']:
            raise ValueError('Artifact hash/size mismatch')
        names.add(name); checked.append((entry, obj))
    destination.mkdir(parents=True, exist_ok=False)
    for entry, obj in checked:
        raw = obj.read_bytes()
        # Verify again to catch source changes between validation and copy.
        if sha(raw) != entry['sha256']: raise ValueError('Artifact changed during restore')
        target = destination/entry['path']; immutable(target, raw)
        if sha(target.read_bytes()) != entry['sha256']: raise ValueError('Restore readback mismatch')
    return {'restored_files':len(checked), 'all_hashes_verified':True}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    restore_parser = sub.add_parser('restore-artifacts')
    restore_parser.add_argument('--store', type=Path, required=True)
    restore_parser.add_argument('--manifest', type=Path, required=True)
    restore_parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore_artifacts(args.store, args.manifest, args.destination), ensure_ascii=False))

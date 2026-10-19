#!/usr/bin/env python3
"""Capture explicit public GET sources with immutable bodies and real timestamps.

No authentication, retries, browser bypass, or availability certification. A plan
contains only named URLs selected by the researcher; this is not a news crawler.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
from urllib.parse import urlparse


def capture(plan, destination):
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for item in plan:
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', item['id']):
            raise ValueError('Invalid source ID')
        if urlparse(item['url']).scheme != 'https':
            raise ValueError('Only explicitly selected HTTPS public sources')
        record = dict(item, requested_at=datetime.now(timezone.utc).isoformat())
        try:
            request = Request(item['url'], headers={'User-Agent': 'WeeklyBriefResearch/1.0', 'Accept': '*/*'})
            with urlopen(request, timeout=25) as response:
                body = response.read(20_000_001)
                if len(body) > 20_000_000:
                    raise ValueError('Source exceeds capture limit; no truncated evidence saved')
                record.update(http_status=response.status, final_url=response.url,
                              content_type=response.headers.get('Content-Type'))
            file = destination / (item['id'] + '.body')
            with file.open('xb') as target:
                target.write(body)
            record.update(path=file.name, sha256=hashlib.sha256(body).hexdigest(), bytes=len(body), status='captured')
        except Exception as exc:
            record.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        record['retrieved_at'] = datetime.now(timezone.utc).isoformat()
        record['historical_version_certified'] = False
        with (destination / (item['id'] + '.receipt.json')).open('x') as target:
            json.dump(record, target, ensure_ascii=False, indent=2)
        records.append(record)
        print(json.dumps({k:record[k] for k in ['id','status','retrieved_at']}), flush=True)
    with (destination/'manifest.json').open('x') as target:
        json.dump(records, target, ensure_ascii=False, indent=2)
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    results = capture(json.loads(args.plan.read_text()), args.output)
    raise SystemExit(0 if all(x['status']=='captured' for x in results) else 2)

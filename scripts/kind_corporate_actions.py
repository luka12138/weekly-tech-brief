#!/usr/bin/env python3
"""Read the registered Korean issuers' public KIND forms; preserve exact receipts.

The public form and viewer flow were inspected on 2026-10-19. A complete list of
filings by publication date is NOT a complete ledger by action effective date.
No login, inferred empty dividends, or historical-version certification.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
from html import unescape
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlencode, urlparse, parse_qsl
from urllib.request import Request, urlopen

from market_qualification import Rows, positive

ISSUERS = {'000660': 'SK하이닉스', '005930': '삼성전자'}
BASE = 'https://kind.krx.co.kr'
FORM = BASE + '/disclosure/searchdisclosurebycorp.do'


def curl_response(url, params=None):
    """Use the OS TLS implementation; never disable certificate verification.

No automatic retries or redirects. Failures remain failures in the calling
receipt, so a TLS error cannot become an empty list or a cached success.
"""
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != 'kind.krx.co.kr':
        raise ValueError('Only the observed official KIND host is supported')
    with tempfile.TemporaryDirectory(prefix='weekly-kind-') as folder:
        body_path = Path(folder) / 'response.body'
        cmd = ['curl', '--silent', '--show-error', '--proto', '=https',
               '--connect-timeout', '10', '--max-time', '30', '--max-filesize', '20000000',
               '--user-agent', 'WeeklyBriefResearch/1.0', '--referer', FORM + '?method=searchDisclosureByCorpMain',
               '--output', str(body_path), '--write-out', '%{http_code}\n%{url_effective}', url]
        if params is not None:
            cmd += ['--data', urlencode(params)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
        if result.returncode:
            raise OSError('curl exit ' + str(result.returncode) + ': ' + result.stderr.strip())
        status, final_url = result.stdout.split('\n', 1)
        if status != '200' or final_url != url:
            raise ValueError('Unexpected KIND HTTP status/location: ' + status + ' ' + final_url)
        body = body_path.read_bytes()
        if len(body) > 20_000_000:
            raise ValueError('Oversized source; reject truncated evidence')
        return body, 200, final_url


def decode(body):
    try:
        return body.decode('utf-8')
    except UnicodeDecodeError:
        return body.decode('cp949')


def parse_list(html, code, start, end, page, page_size=100):
    if code not in ISSUERS:
        raise ValueError('Issuer must have a verified registry mapping')
    marker = re.search(r'전체\s*<em>([\d,]+)</em>건\s*:\s*<strong>(\d+)</strong>/(\d+)', html)
    if not marker:
        raise ValueError('Missing KIND pagination; do not treat shell/error as zero')
    total, current, pages = (int(x.replace(',', '')) for x in marker.groups())
    if current != page or pages != max(1, math.ceil(total / page_size)):
        raise ValueError('Unexpected pagination or page size')
    entries = []
    for row in re.findall(r'<tr\b[^>]*>[\s\S]*?</tr>', html):
        match = re.search(r"openDisclsViewer\('([0-9]{14})','([^']*)'\)", row)
        if not match:
            continue
        parsed = Rows(); parsed.feed(row)
        values = parsed.rows[0]
        issuer = re.search(r"companysummary_open\('([0-9]+)'\)", row)
        if len(values) < 5 or not issuer or issuer.group(1) != code[:-1] or values[2] != ISSUERS[code]:
            raise ValueError('Wrong issuer or changed filing-row schema')
        publication = datetime.strptime(values[1], '%Y-%m-%d %H:%M')
        if not start <= publication.date().isoformat() <= end:
            raise ValueError('Response outside the requested publication window')
        entries.append({'accession': match.group(1), 'symbol': code + '.KS',
                        'issuer_name': values[2], 'title': values[3], 'submitter': values[4],
                        'publication_displayed': values[1],
                        'publication_timezone': 'not_explicit_in_captured_list',
                        'viewer_url': BASE + '/common/disclsviewer.do?' + urlencode({
                            'method': 'search', 'acptno': match.group(1), 'docno': match.group(2),
                            'viewerhost': '', 'viewerport': ''})})
    expected = min(page_size, max(0, total - (page - 1) * page_size))
    if len(entries) != expected or len({e['accession'] for e in entries}) != len(entries):
        raise ValueError('Missing or duplicate filing rows')
    if total == 0 and '조회된 결과값이 없습니다.' not in html:
        raise ValueError('Zero result lacks explicit empty-state text')
    return {'reported_total': total, 'page': current, 'pages': pages, 'entries': entries,
            'complete_corporate_action_ledger': False}


def selected_document(viewer_html, issuer_name):
    if '[' + issuer_name + ']' not in viewer_html:
        raise ValueError('Viewer identity mismatch')
    values = re.findall(r'<option\s+value=[\'"]([0-9]+)\|Y[\'"][^>]*selected=', viewer_html)
    if len(values) != 1:
        raise ValueError('Missing or ambiguous selected document')
    return values[0]


def filing_url(contents_html):
    match = re.search(r"parent.setPath\('','(https://[^']+)'", contents_html)
    if not match:
        raise ValueError('Missing public document location')
    url = unescape(match.group(1)); parsed = urlparse(url)
    if parsed.netloc != 'kind.krx.co.kr' or not parsed.path.startswith('/external/'):
        raise ValueError('Unexpected document host/path')
    return url


def cash_ex_notice(body, code):
    """KRX ex-cash reference price is not the cash amount (including unchanged ref)."""
    html = decode(body); parser = Rows(); parser.feed(html)
    rows = parser.rows
    if code not in ISSUERS or '중간(분기)배당락 기준가격 안내' not in html:
        raise ValueError('Not a supported KRX cash ex-date notice')
    def value(label):
        matches = [r[-1] for r in rows if r and r[0] == label]
        if len(matches) != 1:
            raise ValueError('Missing/duplicate field: ' + label)
        return matches[0]
    if value('1. 회사명') != ISSUERS[code]:
        raise ValueError('Notice issuer mismatch')
    ordinary = [r for r in rows if r and r[0] == '보통주식']
    if len(ordinary) != 1 or len(ordinary[0]) != 2:
        raise ValueError('Ordinary-share reference row required')
    reason = value('3. 사유')
    if reason != '중간(분기)배당락(기준가격 변동없음)':
        raise ValueError('Changed notice reason requires semantic review')
    return {'instrument': code + '.KS', 'event_type': 'cash_dividend', 'currency': 'KRW',
            'ex_date': date.fromisoformat(value('4. 적용일')).isoformat(),
            'ex_date_basis': 'explicit_exchange_effective_date',
            'cash_amount_declared_per_share': None,
            'amount_status': 'not_disclosed_in_ex_date_notice',
            'exchange_reference_price': str(positive(ordinary[0][1])),
            'exchange_reference_price_unchanged': True,
            'historical_PIT_certified': False}


def verified_saved_response(path, url, params):
    path = Path(path); body = path.read_bytes()
    receipt = json.loads(path.with_suffix('.receipt.json').read_text())
    def canonical(value):
        parsed = urlparse(value)
        return parsed.scheme, parsed.netloc, parsed.path, sorted(parse_qsl(parsed.query, keep_blank_values=True))
    if (receipt.get('http_status') != 200 or receipt.get('sha256') != hashlib.sha256(body).hexdigest()
            or canonical(receipt['url']) != canonical(url) or receipt.get('params') != params
            or not receipt.get('retrieved_at')):
        raise ValueError('Saved response identity, parameters, hash or timestamp mismatch')
    return body, receipt


def download(code, start, end, output, accessions=(), saved=None, offline=False, transport='curl'):
    if transport not in {'curl', 'urllib'}:
        raise ValueError('Unknown HTTPS transport')
    if code not in ISSUERS or not (0 <= (date.fromisoformat(end) - date.fromisoformat(start)).days <= 366):
        raise ValueError('Use a registered issuer and a bounded <= 366-day window')
    if len(set(accessions)) != len(accessions):
        raise ValueError('Duplicate requested filing')
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    saved = saved or {}
    receipts = []; entries = []; manifest = {'status': 'started', 'code': code,
        'publication_window': [start, end], 'offline_replay': offline, 'transport': transport,
        'complete_corporate_action_ledger': False,
        'historical_PIT_certified': False, 'receipts': receipts}
    def read(name, url, params=None):
        rec = {'id': name, 'url': url, 'params': params,
               'requested_at': datetime.now(timezone.utc).isoformat()}
        receipts.append(rec)
        try:
            if name in saved:
                body, original = verified_saved_response(saved[name], url, params)
                target = output / (name + '.body'); target.write_bytes(body)
                rec.update(status='reused_verified_capture', path=target.name, bytes=len(body),
                    http_status=200, sha256=hashlib.sha256(body).hexdigest(),
                    source_path=str(Path(saved[name]).resolve()), source_receipt=original,
                    retrieved_at=original['retrieved_at'], replayed_at=datetime.now(timezone.utc).isoformat())
                return body
            if offline:
                raise ValueError('Offline replay missing required saved response: ' + name)
            rec['transport'] = transport
            if transport == 'curl':
                body, status, final_url = curl_response(url, params)
                rec.update(http_status=status, final_url=final_url)
            else:
                request = Request(url, data=urlencode(params).encode() if params is not None else None,
                                  headers={'User-Agent': 'WeeklyBriefResearch/1.0',
                                           'Referer': FORM + '?method=searchDisclosureByCorpMain'})
                with urlopen(request, timeout=25) as response:
                    body = response.read(20_000_001)
                    rec.update(http_status=response.status, final_url=response.url)
                if rec['http_status'] != 200 or urlparse(rec['final_url']).netloc != 'kind.krx.co.kr':
                    raise ValueError('Unexpected KIND status or redirect host')
            if len(body) > 20_000_000:
                raise ValueError('Oversized source; reject truncated evidence')
            target = output / (name + '.body'); target.write_bytes(body)
            rec.update(status='captured', path=target.name, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
            return body
        except Exception as exc:
            rec.update(status='failed', error=type(exc).__name__ + ': ' + str(exc)); raise
        finally:
            rec.setdefault('retrieved_at', datetime.now(timezone.utc).isoformat())
            (output / (name + '.receipt.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    try:
        pages = 1; expected = None; page = 1
        while page <= pages:
            params = {'method': 'searchDisclosureByCorpSub', 'forward': 'searchdisclosurebycorp_sub',
                'searchCorpName': ISSUERS[code], 'repIsuSrtCd': 'A' + code, 'fromDate': start, 'toDate': end,
                'currentPageSize': '100', 'pageIndex': str(page), 'orderMode': 'D', 'orderStat': 'D',
                'orderIndex': '1', 'reportNm': '', 'reportNmTemp': ''}
            batch = parse_list(decode(read('list_' + str(page), FORM, params)), code, start, end, page)
            if expected is not None and batch['reported_total'] != expected:
                raise ValueError('List changed during pagination; no complete-list claim')
            expected = batch['reported_total']; pages = batch['pages']
            if pages > 20:
                raise ValueError('Too many pages; narrow publication window')
            entries.extend(batch['entries']); page += 1
        if len(entries) != expected or len({e['accession'] for e in entries}) != len(entries):
            raise ValueError('Incomplete/duplicate cross-page list')
        selected = {e['accession']: e for e in entries}
        if set(accessions) - selected.keys():
            raise ValueError('Requested accession absent from verified issuer list')
        manifest.update(entries=entries, reported_total=expected, publication_list_complete=True, filings=[])
        for accession in accessions:
            entry = selected[accession]
            doc = selected_document(decode(read(accession + '_viewer', entry['viewer_url'])), ISSUERS[code])
            contents = BASE + '/common/disclsviewer.do?' + urlencode({
                'method': 'searchContents', 'acptNo': accession, 'docNo': doc})
            url = filing_url(decode(read(accession + '_contents', contents)))
            read(accession + '_filing', url)
            manifest['filings'].append({'accession': accession, 'document_number': doc, 'url': url,
                                        'path': accession + '_filing.body'})
        manifest['status'] = 'downloaded_requires_semantic_review'
    except Exception as exc:
        manifest.update(status='failed', error=type(exc).__name__ + ': ' + str(exc)); raise
    finally:
        (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--code', choices=sorted(ISSUERS), required=True)
    p.add_argument('--start', required=True); p.add_argument('--end', required=True)
    p.add_argument('--output', type=Path, required=True); p.add_argument('--filing', action='append', default=[])
    p.add_argument('--saved-response', action='append', default=[], metavar='REQUEST_ID=BODY_PATH')
    p.add_argument('--offline', action='store_true', help='Require saved captures for every request; never access network')
    p.add_argument('--transport', choices=['curl', 'urllib'], default='curl')
    a = p.parse_args(); saved = {}
    for value in a.saved_response:
        key, path = value.split('=', 1)
        if key in saved: p.error('Duplicate saved request ID')
        saved[key] = Path(path)
    result = download(a.code, a.start, a.end, a.output, a.filing, saved, a.offline, a.transport)
    print(json.dumps({'status': result['status'], 'filings_listed': result['reported_total'],
                      'bodies_downloaded': len(result['filings'])}, ensure_ascii=False))

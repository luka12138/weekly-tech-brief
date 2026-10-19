#!/usr/bin/env python3
"""Normalize real Wind receipt columns, retaining raw references and data qualifications."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from market_observations import calculate_price_observation, column
from investment_review import timestamp
from market_vintages import freeze
from reporting_window import validate_declared_window

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(root, manifest_path):
    manifest = json.loads(manifest_path.read_text())
    ref = manifest['registry'];registry_path = root/ref['path']
    if digest(registry_path) != ref['sha256']:
        raise ValueError('Registry changed after download preparation')
    registry = json.loads(registry_path.read_text())
    day = manifest['report_date']
    if 'cutoff_exclusive' in manifest:
        _, cutoff = validate_declared_window(manifest)
    else:
        # Legacy saved download plans retain their original cutoff.
        from reporting_window import reporting_window
        _, cutoff = reporting_window(day)
    def receipt(identity):
        path = root/'logs/wind_raw'/(identity+'.json')
        data = json.loads(path.read_text())
        if data['request']['id'] != identity or data['result']['ErrorCode'] != 0:
            raise ValueError('Missing or failed Wind receipt: '+identity)
        return data, {'path': str(path.relative_to(root)), 'sha256': digest(path)}
    identity, identity_ref = receipt(manifest['identity'])
    output = {'schema_version': 1, 'report_date': day, 'normalized_at': datetime.now(timezone.utc).isoformat(),
              'download_manifest': {'path': str(manifest_path.relative_to(root)), 'sha256': digest(manifest_path)},
              'observations': {}, 'companies': {}, 'metrics_audit': {},
              'qualification': 'Descriptive unadjusted-price observations only; no historical PIT or cash-dividend total-return promotion.'}
    directory = root/'logs'/f'{day}_market_observations';directory.mkdir(exist_ok=True)
    for item in registry['companies']:
        company, code = item['company'], item['symbol']
        if code is None:
            output['companies'][company] = {'market_status': 'not_mapped', 'market_source': None,
                                             'limitation': '未建立可核独立证券映射；不以合作方股价代替。'}
            continue
        group = registry['markets'][item['market']];ids = manifest['groups'][item['market']]
        stock, stock_ref = receipt(ids['stock']);cal, cal_ref = receipt(ids['calendar'])
        benchmark, bench_ref = receipt(ids['benchmark'])
        dates = stock['result']['Times']
        normalized = {'instrument': {'symbol': code, 'venue': group['venue'], 'currency': group['currency'],
                                     'benchmark': group['benchmark'], 'calendar': group['calendar'], 'price_basis': 'unadjusted_close_price_return'},
                      'session_dates': dates, 'closes': column(stock, code, 'CLOSE'),
                      'benchmark_closes': column(benchmark, group['benchmark'], 'CLOSE'),
                      'provenance': {'stock': stock_ref, 'benchmark': bench_ref, 'calendar': cal_ref,
                                     'stock_identity': identity_ref, 'benchmark_identity': identity_ref}}
        metrics = calculate_price_observation(normalized, cutoff, root)
        path = directory/(code.replace('.', '_')+'.json')
        if path.exists():
            raise FileExistsError('Never overwrite frozen observations: '+str(path))
        path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
        key = 'PRICE_'+code.replace('.', '_')
        retrieved = max(stock['retrieved_at'], benchmark['retrieved_at'], cal['retrieved_at'], identity['retrieved_at'])
        output['observations'][key] = {'path': str(path.relative_to(root)), 'sha256': digest(path),
                                      'url': 'https://www.wind.com.cn/portal/zh/ClientApi/index.html',
                                      'retrieved_at': retrieved, 'version': '实际API回执冻结于'+retrieved,
                                      'locator': f"{code}收盘与{group['benchmark']}价格指数；{dates[0]}至{dates[-1]}，{len(dates)}个真实交易日；具体回执和哈希位于文件provenance。",
                                      'limitation': '当前提取版本；历史PIT未认证；价格回报未计现金分红，不作含分红总回报。'}
        output['companies'][company] = {'market_status': 'observed', 'market_source': key,
                                        'limitation': f"对照{group['benchmark_name']}；未复权价格口径、未计现金分红；除权除息可影响波动。当前提取版本，历史PIT未认证。"}
        output['metrics_audit'][company] = metrics
    out = root/'logs'/f'{day}_wind_market_observations_manifest.json'
    if out.exists():
        raise FileExistsError(out)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    paths=[out,manifest_path,registry_path,*directory.glob('*.json')]
    for group in manifest['groups'].values():
        paths.extend(root/'logs/wind_raw'/(identity+'.json') for identity in group.values())
    paths.append(root/'logs/wind_raw'/(manifest['identity']+'.json'))
    vintage, frozen=freeze(root,paths,root/'state/market_vault',day+'-price-observations')
    with (root/'logs'/f'{day}_price_vintage_receipt.json').open('x') as target:
        json.dump({'manifest':str(vintage.relative_to(root)),'preserved_at':frozen['preserved_at'],
                   'historical_PIT_certified':False},target,ensure_ascii=False,indent=2)
    return out, output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    args = p.parse_args()
    path, data = normalize(ROOT, args.manifest.resolve())
    print(json.dumps({'manifest': str(path), 'observations': len(data['observations']),
                      'metrics': {c: {k: m[k] for k in ['week_return', 'excess_return', 'rv20', 'rv20_change', 'sessions', 'quote_count', 'last_close', 'last_close_price']} for c, m in data['metrics_audit'].items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()

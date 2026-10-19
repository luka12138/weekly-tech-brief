#!/usr/bin/env python3
"""Read KRX's public KOSPI TR historical form using its ordinary request flow.

Parameters are taken from the public KGG01T Data page. No account/key, no login,
no access-denial retry. Current observations never certify historical vintages.
"""
import argparse
from datetime import date,datetime,timezone
import hashlib
from http.cookiejar import CookieJar
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,build_opener,HTTPCookieProcessor


def download(start,end,output):
    if date.fromisoformat(start)>date.fromisoformat(end):raise ValueError('Inverted date interval')
    output.mkdir(parents=True,exist_ok=False)
    base='https://eindex.krx.co.kr';page=base+'/contents/GLB/05/0502/0502030101/GLB0502030101T2.jsp?upmidCd=0306&idxCd=1195&idxId=KGG01T'
    opener=build_opener(HTTPCookieProcessor(CookieJar()));records=[]
    def read(name,url,params=None):
        began=datetime.now(timezone.utc).isoformat()
        req=Request(url,data=urlencode(params).encode() if params else None,
                    headers={'User-Agent':'Mozilla/5.0','Referer':page})
        with opener.open(req,timeout=25) as r:raw=r.read();status=r.status
        file=output/(name+'.body');file.write_bytes(raw)
        records.append({'id':name,'url':url,'request':params,'started_at':began,
                        'retrieved_at':datetime.now(timezone.utc).isoformat(),'http_status':status,
                        'path':file.name,'sha256':hashlib.sha256(raw).hexdigest()})
        return raw
    try:
        token=read('public_form_token',base+'/contents/COM/GenerateOTP.jspx?'+urlencode({
            'bld':'/IDXE/05/0502/0502030101/glb0502030101T2_02','name':'form'})).decode().strip()
        params={'idx_cd':'1195','ind_tp_cd':'1','idx_ind_cd':'195','idx_id':'KGG01T',
                'add_data_yn':'','lang':'en','fromdate':start.replace('-',''),'todate':end.replace('-',''),
                'pagePath':'/contents/GLB/05/0502/0502030101/GLB0502030101T2.jsp','code':token}
        raw=read('kospi_tr_history',base+'/contents/IDXE/99/IDXE99000001.jspx',params)
        payload=json.loads(raw)
        lists=[v for v in payload.values() if isinstance(v,list) and v and 'trd_dd' in v[0] and 'clsprc_idx' in v[0]]
        if len(lists)!=1:raise ValueError('Missing or ambiguous KRX historical rows')
        rows=lists[0];print(json.dumps({'rows':len(rows),'first':rows[0],'last':rows[-1]},ensure_ascii=False))
        records.append({'status':'received_unqualified_rows','rows':len(rows),'historical_PIT_certified':False})
        return payload
    except Exception as exc:
        records.append({'status':'failed','error':f'{type(exc).__name__}: {exc}','at':datetime.now(timezone.utc).isoformat()})
        raise
    finally:
        (output/'receipts.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--start',required=True);p.add_argument('--end',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();download(a.start,a.end,a.output)

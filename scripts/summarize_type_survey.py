"""只读探路结果，汇总各类型的谱适用性与筛选差异；不决定画法。"""
import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean


def describe(values,reference):
    x=[v/reference if reference>0 else 0 for v in values]
    mu=mean(x) if x else 0
    cv=math.sqrt(mean([(v-mu)**2 for v in x]))/mu if mu>0 else None
    return {'cells':len(x),'minimum':min(x,default=0),'maximum':max(x,default=0),'mean':mu,'cv':cv,
            'selected':{str(t):sum(v>t for v in x) for t in (0,.05,.1,.15,.2,.25,.3,.4,.5)}}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path);args=parser.parse_args()
    root=args.folder.resolve();manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    tensors={};files={}
    for item in manifest['tensors']:
        path=root/item['data_file'];digest=hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest==item['data_sha256'];files[path.name]=digest
        data=json.loads(path.read_text(encoding='utf-8'))
        descriptions={}
        for channel in ('full','feature','rowcol','residual'):
            values=[v for p in data['parts'] for v in (p.get(channel) or [])]
            descriptions[channel]=describe(values,data['reference_white']) if values else None
        tensors[item['key']]={'key':item['key'],'shape':item['shape'],'method':item['spectral']['method'],
            'retained':item['spectral']['retained'],'capped':item['spectral']['rank_capped'],
            'iteration_change':item['spectral']['pooled_iteration_change'],'channels':descriptions,
            'statistics':item['statistics'],'seconds':item['seconds'],'parts':len(data['parts'])}
    groups=[]
    for b in manifest['blocks']:
        keys=[t['file']+':'+t['gguf'] for t in b['tensors']]
        missing=[k for k in keys if k not in tensors]
        item={'id':b['id'],'role':b['role'],'label':b['label'],'tensor_count':len(keys),'missing':missing}
        channels={}
        for channel in ('full','feature','rowcol'):
            present=[tensors[k]['channels'][channel] for k in keys if k in tensors and tensors[k]['channels'][channel]]
            channels[channel]={'cells':sum(t['cells'] for t in present),
                'selected':{str(t):sum(d['selected'][str(t)] for d in present) for t in (0,.05,.1,.15,.2,.25,.3,.4,.5)}}
        item['channels']=channels;groups.append(item)
    logs=[json.loads(line) for line in (root/'progress.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    report={'source':root.name,'success':len(tensors),'failures':manifest['failures'],'groups':groups,
            'methods':dict(Counter(v['method'] for v in tensors.values())),
            'capped':[k for k,v in tensors.items() if v['capped']],
            'iteration_changes':sorted([{'key':k,'relative_l2':v['iteration_change']} for k,v in tensors.items() if v['iteration_change'] is not None],key=lambda v:v['relative_l2'],reverse=True),
            'rss_mib_max_observed':max((r.get('worker_rss_mib',0) for r in logs),default=0),
            'private_mib_max_observed':max((r.get('worker_private_mib',0) for r in logs),default=0),
            'seconds':manifest['elapsed_seconds'],'tensors':list(tensors.values()),'files_sha256':files}
    output=root/('analysis-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(exist_ok=False)
    with (output/'summary.json').open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,allow_nan=False,indent=2)
    examples=['L03.mix0','L03.mix1','L03.mix2','L00.mix0','L00.mix1','L00.mix2','L16.gate','L16.up','L16.down','embed','lm_head','V.patch','V.merger']
    print(json.dumps({k:report[k] for k in ('success','failures','methods','capped','seconds','private_mib_max_observed')},ensure_ascii=False))
    print(json.dumps({'largest_iteration_changes':report['iteration_changes'][:8],
                      'groups':[v for v in groups if v['id'] in examples]},ensure_ascii=False))
    print(json.dumps({'output':str(output)},ensure_ascii=False))


if __name__=='__main__':main()

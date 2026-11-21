"""全类型灰度展开的独立副本，不读取权重、不调用SVD、不覆盖已有。

方法与结果见 docs/contrast_survey.md。每次建立新的 prototype/contrast_survey/<时间戳>/。
"""
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
SOURCE=ROOT/'prototype/data/type_surveys/run-20261122-002935-897005'
FILES=['type_survey.html','type_survey.js','type_survey_scene.js','type_survey.css','gray_samples_scene.js','gray_samples.css']
CHANNELS=('full','feature','rowcol','residual')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path,obj):
    with path.open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,allow_nan=False,separators=(',',':'))


def map_window(value,lo,hi,reference):
    if hi>lo:return max(0.,min(1.,(value-lo)/(hi-lo)))
    return max(0.,min(1.,value/reference)) if reference>0 else 0.


def distribution(values):
    n=len(values);lo=min(values);hi=max(values);mu=math.fsum(values)/n
    variance=math.fsum((v-mu)**2 for v in values)/n
    ordered=sorted(values)
    def quantile(q):
        i=(n-1)*q;a=int(i);b=min(a+1,n-1)
        return ordered[a]+(ordered[b]-ordered[a])*(i-a)
    return {'count':n,'low':lo,'high':hi,'mean':mu,'cv':math.sqrt(variance)/mu if mu>0 else None,
            'constant':hi==lo,'zero_source_count':sum(v==0 for v in values),'p005':quantile(.005),'p995':quantile(.995)}


def main():
    manifest=json.loads((SOURCE/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['status']=='complete' and len(manifest['tensors'])==124 and len(manifest['blocks'])==65
    folder=ROOT/'prototype/contrast_survey'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    for name in ('source_data','data','original_files','assets'): (folder/name).mkdir(parents=True,exist_ok=False)
    originals=[SOURCE/'manifest.json']+[SOURCE/t['data_file'] for t in manifest['tensors']]
    originals += [ROOT/'prototype'/name for name in FILES]
    before={str(p.relative_to(ROOT)):sha(p) for p in originals}
    # 原件快照逐字复制，映射后的数据另写，源文件永不编辑。
    for p in originals:
        dst=folder/('source_data' if p.parent==SOURCE else 'original_files')/p.name
        with dst.open('xb') as f:f.write(p.read_bytes())
        assert sha(dst)==before[str(p.relative_to(ROOT))]
    for source,target in [('gray_samples.css','base.css'),('type_survey.css','layout.css'),
                          ('gray_samples_scene.js','base_scene.js'),('type_survey_scene.js','scene.js')]:
        with (folder/'assets'/target).open('xb') as f:f.write((ROOT/'prototype'/source).read_bytes())
    entries=[];summaries=[]
    for item in manifest['tensors']:
        path=SOURCE/item['data_file'];assert sha(path)==item['data_sha256']
        data=json.loads(path.read_text(encoding='utf-8'));windows={};coverage={}
        for channel in CHANNELS:
            values=[v for p in data['parts'] for v in (p.get(channel) or [])]
            if not values:windows[channel]=None;continue
            assert all(math.isfinite(v) and v>=0 for v in values)
            window=distribution(values);windows[channel]=window
            expanded=[map_window(v,window['low'],window['high'],data['reference_white']) for v in values]
            if not window['constant']:
                assert min(expanded)==0 and max(expanded)==1
            else:
                assert len(set(expanded))==1
            coverage[channel]={'source_range':[window['low'],window['high']],
                'relative_range_old':[window['low']/data['reference_white'],window['high']/data['reference_white']] if data['reference_white'] else [0,0],
                'old_gain2_saturation':sum(data['reference_white']>0 and v/data['reference_white']*2>=1 for v in values)/len(values),
                'expanded_range':[min(expanded),max(expanded)],'constant':window['constant']}
        for part in data['parts']:
            part['expanded']={channel:[map_window(v,windows[channel]['low'],windows[channel]['high'],data['reference_white']) for v in part[channel]]
                              if part.get(channel) is not None else None for channel in CHANNELS}
        data['windows']=windows
        data['original_data_sha256']=item['data_sha256']
        write(folder/'data'/item['data_file'],data)
        entries.append({**item,'data_sha256':sha(folder/'data'/item['data_file']),'windows':windows})
        summaries.append({'key':item['key'],'channels':coverage})
    output={**manifest,'schema':'snowglass.contrast-survey.v1','source_run':SOURCE.name,'tensors':entries,
            'mapping':'per tensor per channel actual min/max; same window across all subregions; no spatial selection',
            'constant_policy':'unchanged fixed-reference gray; never introduce texture',
            'source_hashes':before,'prepare_script_sha256':sha(Path(__file__))}
    write(folder/'data/manifest.json',output)
    write(folder/'contrast_summary.json',{'tensors':summaries,'timestamp':folder.name,'source_hashes':before})
    after={str(p.relative_to(ROOT)):sha(p) for p in originals};assert before==after
    write(folder/'copy_verification.json',{'source_unchanged':True,'snapshots_identical':True,'tensors':124,'groups':65,'hashes':before})
    print(json.dumps({'folder':str(folder),'tensors':124,'groups':65,'source_unchanged':True,
        'variable_channel_count':sum(not w['constant'] for t in entries for w in t['windows'].values() if w),
        'constant_channels':[{'key':t['key'],'channel':c} for t in entries for c,w in t['windows'].items() if w and w['constant']]},ensure_ascii=False),flush=True)


if __name__=='__main__':main()

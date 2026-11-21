# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2,<3", "gguf==0.19.0", "threadpoolctl>=3,<4", "psutil>=6,<8"]
# ///
"""全类型＋前中后层探路。方法与范围：docs/type_survey.md。"""
import argparse
import gc
import hashlib
import importlib.metadata
import multiprocessing as mp
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil
from gguf import GGUFReader
from threadpoolctl import threadpool_limits,threadpool_info

import survey_data as d
import survey_math as m

BASE=d.ROOT/'prototype/data/type_surveys'


def json_scalar(value):
    if isinstance(value,np.generic):return value.item()
    raise TypeError(f'不能序列化 {type(value).__name__}')


def write(path,obj):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,allow_nan=False,separators=(',',':'),default=json_scalar)


class Log:
    def __init__(self,path):
        self.path=path;self.start=time.perf_counter();self.state={};self.lock=threading.Lock();self.stop=threading.Event();self.deadline=float('inf')
        self.path.touch(exist_ok=False)
        threading.Thread(target=self.heartbeat,daemon=True).start()
    def emit(self,stage,**data):
        self.state={'stage':stage,**data}
        mem=psutil.Process().memory_info()
        record={'seconds':round(time.perf_counter()-self.start,2),'rss_mib':round(mem.rss/1024**2,1),
                'private_mib':round(getattr(mem,'private',mem.vms)/1024**2,1),**self.state}
        with self.lock:
            line=json.dumps(record,ensure_ascii=False,default=json_scalar)
            if stage in ('整批完成','输出目录','张量完成','张量失败，继续下一项','开始张量') or data.get('heartbeat'):
                print(line,flush=True)
            with self.path.open('a',encoding='utf-8') as f:f.write(line+'\n')
        if time.perf_counter()>self.deadline:raise TimeoutError('超过单张量时间上限，保留失败记录')
    def heartbeat(self):
        while not self.stop.wait(10):
            state={k:v for k,v in self.state.items() if k!='heartbeat'}
            if not state:continue
            try:self.emit(**state,heartbeat=True)
            except TimeoutError:pass


def id_of(key):return key.replace(':','__').replace('/','_')


def validate(result):
    total=0
    for part in result['parts']:
        count=int(np.prod(part['grid']));counts=np.asarray(part['counts']);total+=int(counts.sum())
        assert counts.size==count and counts.min()>0
        for name in ('full','feature','residual','rowcol','signed'):
            if part.get(name) is None:continue
            a=np.asarray(part[name]);assert a.size==count and np.isfinite(a).all()
            if name!='signed':assert (a>=0).all()
    assert total==np.prod(result['shape'])
    expected=result['statistics']['mean_abs']
    weighted=sum(sum(v*c for v,c in zip(p['full'],p['counts'])) for p in result['parts'])/total
    np.testing.assert_allclose(weighted,expected,rtol=2e-6,atol=1e-9)


def finish_tensor(key,ref,source,folder,log):
    start=time.perf_counter();big=np.prod(source.shape)>100_000_000
    log.deadline=start+(420 if big else 180)
    def tick(stage,**kwargs):log.emit(stage,tensor=key,**kwargs)
    tick('开始张量',shape=list(source.shape),streaming=big)
    output=m.streaming(source,tick) if big else m.dense(source,tick)
    result={'key':key,'name':ref['gguf'],'file':ref['file'],'shape':list(source.shape),'quantization':ref['qtype'],
            'restore':ref.get('restore'),'restoration_caveat':'沿用已记录转换约定；未在本轮重新远程逐元素核对',
            'packed_sha256':source.packed_sha256,'reference_white':2*output['statistics']['mean_abs'],**output}
    validate(result)
    reference=result['reference_white']
    sensitivity=[]
    for channel in ('full','feature','rowcol'):
        values=np.concatenate([p[channel] for p in result['parts'] if p.get(channel) is not None]) if any(p.get(channel) is not None for p in result['parts']) else np.array([])
        if not values.size:continue
        x=values/reference if reference else values*0
        for cutoff in (0,.05,.1,.15,.2,.24,.25,.26,.3,.4,.5):
            sensitivity.append({'channel':channel,'cutoff':cutoff,'cells':int(x.size),'retained':int((x>cutoff).sum()),
                                'original_selected_mean':float(x[x>cutoff].mean()) if (x>cutoff).any() else None})
    result['selection_sensitivity']=sensitivity
    result['seconds']=time.perf_counter()-start
    file=id_of(key)+'.json';write(folder/file,result)
    index={k:result[k] for k in ('key','name','file','shape','quantization','restore','statistics','spectral','reference_white','seconds')}
    index['data_file']=file;index['data_sha256']=d.sha(folder/file);index['part_count']=len(result['parts'])
    log.emit('张量完成',tensor=key,seconds_tensor=round(result['seconds'],2),method=result['spectral']['method'],
             retained=result['spectral']['retained'],capped=result['spectral']['rank_capped'],convergence=result['spectral']['pooled_iteration_change'])
    return index


def probe(plan,folder,log):
    records=[]
    log.emit('读取文本文件头')
    reader=GGUFReader(str(d.FILES['text']),'r');lookup={t.name:t for t in reader.tensors}
    for key in ('text:blk.0.ssm_conv1d.weight','text:blk.3.attn_k.weight','text:token_embd.weight','text:output.weight'):
        ref=plan['references'][key];source=d.TensorSource(lookup[ref['gguf']],ref)
        if source.shape[0]>100000:
            rows=2048;t=time.perf_counter();w=source.rows(0,rows);decode=time.perf_counter()-t
            rng=np.random.default_rng(42);z=rng.standard_normal((w.shape[1],112),dtype=np.float32)
            t=time.perf_counter();y=w.T@(w@z);product=time.perf_counter()-t
            assert np.isfinite(y).all()
            record={'key':key,'rows':rows,'decode_seconds':decode,'two_products_seconds':product,
                    'estimated_full_pass_seconds':(decode+product)*source.shape[0]/rows,
                    'batch_mib':w.nbytes/1024**2,'warning':'按首批外推，非总时长承诺'}
            records.append(record);log.emit('大矩阵探针',**record)
        else:
            t=time.perf_counter();w=source.decode()
            if not ref.get('restore'):
                np.testing.assert_array_equal(source.rows(0,8),w[:8])
            parts=d.pack_parts(w,ref)
            if min(w.shape)>=64:
                info=m.stats(w);spectral=m.spectral_matrix(w,ref,parts,info,lambda stage,**x:log.emit(stage,**x))
            else:spectral=None
            record={'key':key,'seconds':time.perf_counter()-t,'parts':len(parts),'spectral':spectral}
            records.append(record);log.emit('普通张量探针',key=key,seconds=record['seconds'])
        del source,w;gc.collect()
    write(folder/'probe.json',{'records':records,'threads':threadpool_info()})


class WorkerLog:
    def __init__(self,connection):self.connection=connection;self.deadline=float('inf')
    def emit(self,stage,**data):
        mem=psutil.Process().memory_info()
        self.connection.send(('stage',stage,{**data,'worker_rss_mib':round(mem.rss/1024**2,1),
            'worker_private_mib':round(getattr(mem,'private',mem.vms)/1024**2,1)}))


def worker_loop(connection,folder):
    # 只隔离本次计算任务，不涉及其他终端或用户进程。
    reader=lookup=None;current_file=None
    with threadpool_limits(limits=4):
        while True:
            task=connection.recv()
            if task is None:break
            key,ref=task
            try:
                if ref['file']!=current_file:
                    reader=lookup=None;gc.collect()
                    reader=GGUFReader(str(d.FILES[ref['file']]),'r')
                    lookup={t.name:t for t in reader.tensors};current_file=ref['file']
                source=d.TensorSource(lookup[ref['gguf']],ref)
                index=finish_tensor(key,ref,source,folder,WorkerLog(connection))
                connection.send(('result',index));del source
            except Exception as e:
                connection.send(('error',repr(e)))
            gc.collect()
    connection.close()


def run_batch(plan,folder,log):
    tensors=[];failures=[];process=None;connection=None
    refs=sorted(plan['references'].items(),key=lambda p:(p[1]['file'],np.prod(p[1]['shape'])>100_000_000,p[0]))
    try:
        for position,(key,ref) in enumerate(refs,1):
            if process is None or not process.is_alive():
                parent,child=mp.Pipe()
                process=mp.Process(target=worker_loop,args=(child,folder),daemon=True)
                process.start();child.close();connection=parent
            limit=420 if np.prod(ref['shape'])>100_000_000 else 180
            begin=time.perf_counter();connection.send((key,ref))
            log.emit('开始张量',tensor=key,number=position,total=len(refs),limit_seconds=limit)
            failure=None
            while True:
                if connection.poll(.5):
                    message=connection.recv()
                    if message[0]=='stage':log.emit(message[1],**message[2],completed=position-1)
                    elif message[0]=='result':
                        tensors.append(message[1])
                        write(folder/(id_of(key)+'.completed.json'),message[1])
                        log.emit('张量完成',tensor=key,completed=position,total=len(refs),
                            seconds_tensor=round(time.perf_counter()-begin,2))
                        break
                    else:failure=message[1];break
                if not process.is_alive():failure='计算进程意外退出';break
                if time.perf_counter()-begin>limit:failure=f'单张量超时 {limit}s';break
                try:
                    mem=psutil.Process(process.pid).memory_info()
                    if getattr(mem,'private',0)>3*1024**3:failure='计算进程私有内存超过 3 GiB';break
                except psutil.NoSuchProcess:failure='计算进程已退出';break
            if failure:
                failures.append({'key':key,'error':failure})
                write(folder/(id_of(key)+'.failed.json'),failures[-1])
                log.emit('张量失败，继续下一项',tensor=key,error=failure)
                if process.is_alive():process.terminate()
                process.join(5);connection.close();process=connection=None
    finally:
        if process is not None:
            if process.is_alive():connection.send(None)
            process.join(5)
            if process.is_alive():process.terminate();process.join(5)
            connection.close()
    return tensors,failures


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['scope','probe','run','check'],required=True)
    parser.add_argument('--folder',type=Path)
    args=parser.parse_args()
    if args.mode=='check':
        manifest=json.loads((args.folder/'manifest.json').read_text(encoding='utf-8'))
        for item in manifest['tensors']:
            assert d.sha(args.folder/item['data_file'])==item['data_sha256']
            validate(json.loads((args.folder/item['data_file']).read_text(encoding='utf-8')))
        print(json.dumps({'validated_tensors':len(manifest['tensors']),'failures':manifest['failures'],'blocks':len(manifest['blocks'])},ensure_ascii=False));return
    plan=d.scope()
    if args.mode=='scope':
        print(json.dumps({'blocks':len(plan['blocks']),'tensors':len(plan['references']),'layers':plan['layers'],
                          'type_coverage':plan['all_type_signatures_covered'],'unselected_quantization_variants':plan['quantization_variants_not_selected'],
                          'tests':d.self_test()},ensure_ascii=False));return
    folder=BASE/(args.mode+'-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    folder.mkdir(parents=True,exist_ok=False)
    write(folder/'scope.json',plan)
    log=Log(folder/'progress.jsonl')
    try:
        with threadpool_limits(limits=4):
            if args.mode=='probe':probe(plan,folder,log)
            else:
                tensors,failures=run_batch(plan,folder,log)
                log.deadline=float('inf')
                result={'schema':'snowglass.type-survey.v1','status':'complete' if not failures else 'partial',
                        'layers':plan['layers'],'blocks':plan['blocks'],'geometry_only':plan['geometry_only'],
                        'expected_tensor_count':124,'tensors':tensors,'failures':failures,'scope':plan['all_type_signatures_covered'],
                        'quantization_variants_not_selected':plan['quantization_variants_not_selected'],
                        'elapsed_seconds':time.perf_counter()-log.start,'environment':{'python':sys.version,
                            'packages':{n:importlib.metadata.version(n) for n in ('numpy','gguf','threadpoolctl','psutil')},'blas':threadpool_info()},
                        'sources':{name:{'path':str(path.relative_to(d.ROOT)),'size':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns} for name,path in d.FILES.items()},
                        'scripts':{path.name:d.sha(path) for path in (Path(__file__),Path(d.__file__),Path(m.__file__))}}
                write(folder/'manifest.json',result)
                log.emit('整批完成',success=len(tensors),failed=len(failures),elapsed=result['elapsed_seconds'])
            log.emit('输出目录',folder=str(folder))
    finally:log.stop.set()


if __name__=='__main__':main()

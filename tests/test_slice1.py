# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2,<3", "gguf==0.19.0", "threadpoolctl>=3,<4", "psutil>=6,<8"]
# ///
"""一级切片的合成GGUF、网格、复用、取消与本机接口测试；不读取真实模型。"""
import functools
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
from gguf import GGUFWriter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import slice1 as s
import serve_editor as web


class Synthetic:
    def __init__(self, values):
        self.values=values
        self.shape=values.shape
        self.ref={}
        self.visited=[]
    def decode(self):
        return self.values.copy()
    def rows(self,start,end):
        self.visited.append((start,end));return self.values[start:end].copy()


class SliceTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'out').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT / 'out', prefix='slice-test-')
        self.folder=Path(self.temp.name)
        self.old_topo,self.old_files=s.d.TOPO,s.d.FILES
        self.old_functions=s.d.pooled,s.m.pooled,s.m.stream_reduce
        self.gguf=self.folder / 'synthetic.gguf'
        self.write_gguf()
        ref=lambda name:{'file':'text','gguf':name,'shape':[64],'qtype':'F32','restore':None}
        topo={'blocks':[{'id':'A','label':'A','tensors':[ref('a.weight')]},
                        {'id':'B','label':'B','tensors':[ref('b.weight')]}]}
        s.d.TOPO=self.folder / 'topology.json'
        s.write_new(s.d.TOPO,topo)
        s.d.FILES={'text':self.gguf}
        self.store=self.folder / 'slices'
        self.request={'blocks':[{'id':'A','grid':[16,16,32]},{'id':'B','grid':[16,16,32]}]}

    def tearDown(self):
        s.d.TOPO,s.d.FILES=self.old_topo,self.old_files
        s.d.pooled,s.m.pooled,s.m.stream_reduce=self.old_functions
        self.temp.cleanup()

    def write_gguf(self,delta=0):
        writer=GGUFWriter(str(self.gguf),'test')
        writer.add_tensor('a.weight',np.linspace(-1,1,64,dtype=np.float32)+delta)
        writer.add_tensor('b.weight',np.linspace(-2,2,64,dtype=np.float32))
        writer.write_header_to_file()
        writer.write_kv_data_to_file()
        writer.write_tensors_to_file()
        writer.close()

    def run_request(self,request=None):
        job=s.create_job(request or self.request,self.store)
        s.run_job(job,self.store)
        status=s.read_json(job / 'status.json')
        self.assertEqual(status['state'],'complete',status)
        return job,status,s.read_json(job / 'manifest.json')

    def test_scope_and_validation(self):
        plan=s.make_plan(self.request)
        self.assertEqual((plan['block_count'],plan['tensor_count']),(2,2))
        reversed_request={'blocks':list(reversed(self.request['blocks']))}
        self.assertEqual(s.make_plan(reversed_request)['signature'],plan['signature'])
        for request in ({'blocks':[]},{'blocks':[{'id':'mtp','grid':[1,1,1]}]},
                        {'blocks':[self.request['blocks'][0]]*2},
                        {'blocks':[{'id':'A','grid':[0,16,32]}]},
                        {'blocks':[{'id':'A','grid':[64,64,64]}]}):
            with self.assertRaises(ValueError):
                s.make_plan(request)

    def test_default_math_is_unchanged(self):
        source=Synthetic(np.random.default_rng(42).normal(size=(64,64)).astype(np.float32))
        before=s.m.dense(source,lambda *a,**k:None)
        s.configure_grid([16,16,32])
        after=s.m.dense(source,lambda *a,**k:None)
        self.assertEqual(before,after)

    def test_configurable_pooling_covers_every_value(self):
        values=np.arange(17*31*65,dtype=np.float32).reshape(17,31,65)-20
        s.configure_grid([7,9,11])
        actual,counts=s.d.pooled(values)
        self.assertEqual(actual.shape,(7,9,11))
        self.assertEqual(counts.sum(),values.size)
        np.testing.assert_allclose((actual*counts).sum(),np.abs(values).sum(dtype=np.float64),rtol=2e-6)

    def test_run_and_reuse(self):
        first,status,manifest=self.run_request()
        self.assertEqual(status['reused'],0)
        self.assertEqual(len(manifest['blocks']),2)
        original_hashes=[t['data_sha256'] for t in manifest['tensors']]
        _,status,second=self.run_request()
        self.assertEqual(status['reused'],2)
        self.assertEqual(original_hashes,[t['data_sha256'] for t in second['tensors']])
        self.assertTrue((first / 'progress.jsonl').exists())

    def test_cancel_then_new_task_reuses_completed(self):
        self.run_request({'blocks':[self.request['blocks'][0]]})
        job=s.create_job(self.request,self.store)
        (job / 'cancel').touch()
        s.run_job(job,self.store)
        self.assertEqual(s.read_json(job / 'status.json')['state'],'cancelled')
        _,status,_=self.run_request()
        self.assertEqual(status['reused'],1)

    def test_completed_job_is_immutable(self):
        job,_,_=self.run_request()
        before=[s.d.sha(job / name) for name in ('manifest.json','status.json')]
        with self.assertRaises(FileExistsError):
            s.run_job(job,self.store)
        self.assertEqual(before,[s.d.sha(job / name) for name in ('manifest.json','status.json')])

    def test_changed_grid_has_distinct_signature(self):
        _,_,first=self.run_request({'blocks':[self.request['blocks'][0]]})
        changed={'blocks':[{'id':'A','grid':[2,2,2]}]}
        _,status,other=self.run_request(changed)
        self.assertNotEqual(first['signature'],other['signature'])
        self.assertEqual(status['reused'],0)
        path=self.store / other['tensors'][0]['url'].split('/files/',1)[1]
        self.assertEqual(s.read_json(path)['parts'][0]['grid'],[2,2,2])

    def test_source_bytes_change_even_same_mtime_never_reused(self):
        self.run_request({'blocks':[self.request['blocks'][0]]})
        original=self.gguf.stat()
        self.write_gguf(delta=.1)
        os.utime(self.gguf,ns=(original.st_atime_ns,original.st_mtime_ns))
        _,status,_=self.run_request({'blocks':[self.request['blocks'][0]]})
        self.assertEqual(status['reused'],0)

    def test_full_disables_svd_rowcol_and_diagnostics(self):
        source=Synthetic(np.random.default_rng(7).normal(size=(128,64)).astype(np.float32))
        with mock.patch.object(s.m,'spectral_matrix',side_effect=AssertionError('SVD不得运行')), \
             mock.patch.object(s.m,'stats',side_effect=AssertionError('额外统计不得运行')), \
             mock.patch.object(np,'outer',side_effect=AssertionError('行列外积不得运行')):
            result=s.processing.compute(source,'full',False,[16,16,32],lambda *a,**k:None)
        self.assertEqual(set(result['statistics']),{'mean_abs'})
        self.assertEqual(result['spectral']['method'],'not_computed')
        for part in result['parts']:
            for channel in ('feature','residual','rowcol','signed'):self.assertIsNone(part[channel])
        s.validate({**result,'shape':list(source.shape)})

    def test_rowcol_does_not_call_svd(self):
        source=Synthetic(np.arange(128*64,dtype=np.float32).reshape(128,64)-50)
        with mock.patch.object(s.m,'spectral_matrix',side_effect=AssertionError('SVD不得运行')):
            result=s.processing.compute(source,'rowcol',False,[16,16,32],lambda *a,**k:None)
        self.assertIsNotNone(result['parts'][0]['rowcol'])
        self.assertIsNone(result['parts'][0]['feature'])

    def test_diagnostics_only_when_enabled(self):
        source=Synthetic(np.linspace(-1,2,128,dtype=np.float32))
        off=s.processing.compute(source,'full',False,[16,16,32],lambda *a,**k:None)
        on=s.processing.compute(source,'full',True,[16,16,32],lambda *a,**k:None)
        self.assertNotIn('rms',off['statistics']);self.assertIn('rms',on['statistics'])
        self.assertIsNone(off['parts'][0]['signed']);self.assertIsNotNone(on['parts'][0]['signed'])

    def test_gguf_mode_never_applies_hf_restore(self):
        reader=s.GGUFReader(str(self.gguf),'r');tensor=next(t for t in reader.tensors if t.name=='a.weight')
        ref={'shape':[64],'qtype':'F32','restore':'minus_one'}
        raw=s.processing.Source(tensor,ref,'gguf')
        with mock.patch.object(s.d,'restore',side_effect=AssertionError('不得对齐HF')):
            actual=raw.decode()
        aligned=s.processing.Source(tensor,ref,'hf')
        np.testing.assert_array_equal(aligned.decode(),actual-1)
        self.assertEqual(raw.packed_sha256,aligned.packed_sha256)

    def test_optional_spectral_preserves_existing_dense_math(self):
        source=Synthetic(np.random.default_rng(7).normal(size=(64,64)).astype(np.float32))
        old=s.m.dense(source,lambda *a,**k:None)
        new=s.processing.compute(source,'feature',True,[16,16,32],lambda *a,**k:None)
        for a,b in zip(old['parts'],new['parts']):
            for c in ('full','signed','feature','residual','counts'):np.testing.assert_array_equal(a[c],b[c])
        self.assertIsNone(new['parts'][0]['rowcol'])
        self.assertEqual(new['spectral']['iterations'],12)

    def test_stream_direct_is_one_pass_without_svd(self):
        source=Synthetic(np.random.default_rng(3).normal(size=(512,128)).astype(np.float32))
        with mock.patch.object(np.linalg,'svd',side_effect=AssertionError('SVD不得运行')), \
             mock.patch.object(np.linalg,'qr',side_effect=AssertionError('QR不得运行')), \
             mock.patch.object(np,'einsum',side_effect=AssertionError('原矩阵RMS不得运行')):
            result=s.processing.stream_direct(source,'full',False,[8,8,16],lambda *a,**k:None)
        self.assertEqual(sum(b-a for a,b in source.visited),512)
        s.validate({**result,'shape':list(source.shape)})

    def test_optional_stream_spectral_matches_original_channels(self):
        source=Synthetic(np.random.default_rng(8).normal(size=(512,128)).astype(np.float32))
        with s.threadpool_limits(limits=4):
            old=s.m.streaming(source,lambda *a,**k:None)
            new=s.processing.stream_spectral(source,True,[16,16,32],lambda *a,**k:None)
        for c in ('full','signed','feature','residual','counts'):
            np.testing.assert_allclose(new['parts'][0][c],old['parts'][0][c],rtol=2e-6,atol=1e-8)
        self.assertIsNone(new['parts'][0]['rowcol'])

    def test_options_are_in_signature_and_spectral_pair_reuses(self):
        def plan(**opts):return s.make_plan({'blocks':[{**self.request['blocks'][0],**opts}]})['signature']
        base=plan()
        for opts in ({'source':'rowcol'},{'source':'feature'},{'convention':'hf'},{'diagnostics':True}):
            self.assertNotEqual(base,plan(**opts))
        self.assertEqual(plan(source='feature'),plan(source='residual'))
        with self.assertRaises(ValueError):plan(diagnostics='false')

    def test_completed_process_is_reaped_before_next_start(self):
        jobs=web.Jobs(self.store);jobs.job=s.create_job(self.request,self.store)
        s.atomic_json(jobs.job/'status.json',{'state':'complete'})
        old=mock.Mock();old.poll.return_value=None;jobs.process=old
        self.assertIsNone(jobs.active(),'已完成进程不能冒充活跃任务使恢复自动预览')
        with mock.patch.object(web.subprocess,'Popen',return_value=mock.Mock()):
            result=jobs.start(self.request)
        old.wait.assert_called_once_with(timeout=10)
        self.assertEqual(result['state'],'queued')

    def test_stream_rowcol_matches_direct_outer_pool(self):
        source=Synthetic(np.random.default_rng(9).normal(size=(512,128)).astype(np.float32))
        result=s.processing.stream_direct(source,'rowcol',False,[8,8,16],lambda *a,**k:None)
        w=source.values;r=np.sqrt(np.mean(w.astype(np.float64)**2,axis=1));c=np.sqrt(np.mean(w.astype(np.float64)**2,axis=0))
        outer=np.outer(r,c);outer*=np.abs(w).mean(dtype=np.float64)/outer.mean()
        rb,cb,count=s.processing.bins(source,[8,8,16])
        summed=np.add.reduceat(np.add.reduceat(outer,rb[:-1],axis=0),cb[:-1],axis=1)
        np.testing.assert_allclose(result['parts'][0]['rowcol'],(summed/count).ravel(),rtol=2e-6)

    def test_http_token_origin_and_path_guards(self):
        jobs=web.Jobs(self.store)
        calls=[]
        jobs.start=lambda req:calls.append(req) or {'id':'slice-1','state':'queued'}
        factory=lambda *a,**k:web.Handler(*a,bundle=self.folder,jobs=jobs,port=server.server_port,**k)
        server=web.ThreadingHTTPServer(('127.0.0.1',0),factory)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        def request(path,body=None,token=None,origin=None):
            headers={}
            if body is not None:headers['Content-Type']='application/json'
            if token:headers['X-Snowglass-Token']=token
            if origin:headers['Origin']=origin
            req=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
            with urlopen(req,timeout=5) as response:
                return response.status,json.load(response)
        try:
            _,cap=request('/api/slice1/capabilities')
            token=cap['token']
            with self.assertRaises(HTTPError) as missing:
                request('/api/slice1/start',self.request)
            self.assertEqual(missing.exception.code,403)
            with self.assertRaises(HTTPError) as hostile:
                request('/api/slice1/start',self.request,token,'http://example.com')
            self.assertEqual(hostile.exception.code,403)
            _,plan=request('/api/slice1/plan',self.request,token)
            self.assertEqual(plan['tensor_count'],2)
            code,_=request('/api/slice1/start',self.request,token)
            self.assertEqual(code,202)
            self.assertEqual(len(calls),1)
            with self.assertRaises(HTTPError) as escape:
                request('/api/slice1/files/../../data/gguf/secret/result.json')
            self.assertEqual(escape.exception.code,400)
        finally:
            server.shutdown();server.server_close();thread.join(2)


if __name__=='__main__':
    unittest.main(verbosity=2)

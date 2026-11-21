# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2,<3", "gguf==0.19.0", "threadpoolctl>=3,<4", "psutil>=6,<8"]
# ///
"""类型处理与流式路径的秒级合成测试，不使用真实大权重。"""
import json
import sys
import unittest
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import survey_data as d
import survey_math as m
from run_type_survey import json_scalar,validate


class ArraySource:
    def __init__(self,w):self.w=w;self.shape=w.shape;self.ref={}
    def rows(self,a,b):return self.w[a:b]
    def decode(self):return self.w.copy()


class TypeChecks(unittest.TestCase):
    def test_scope(self):
        plan=d.scope();self.assertEqual(len(plan['blocks']),65);self.assertEqual(len(plan['references']),124)
        self.assertTrue(plan['all_type_signatures_covered'])
    def test_restoration_and_pool(self):
        self.assertIn('通过',d.self_test())
    def test_numpy_json(self):
        self.assertEqual(json.loads(json.dumps({'big':np.bool_(True),'n':np.int64(7)},default=json_scalar)),{'big':True,'n':7})
    def test_zero_vector(self):
        result=m.dense(ArraySource(np.zeros(32,dtype=np.float32)),lambda *args,**kw:None)
        self.assertEqual(result['spectral']['method'],'direct')
        self.assertEqual(result['statistics']['mean_abs'],0)
        self.assertTrue(all(not any(p['feature']) for p in result['parts']))
    def test_constant_no_fabricated_texture(self):
        result=m.dense(ArraySource(np.ones(128,dtype=np.float32)),lambda *args,**kw:None)
        self.assertTrue(all(set(p['feature'])=={1.0} for p in result['parts']))
    def test_streaming_operator(self):
        row=np.linspace(.1,1,512,dtype=np.float32)
        col=np.linspace(-1,1,128,dtype=np.float32)
        w=np.outer(row,col)
        with threadpool_limits(limits=2):
            result=m.streaming(ArraySource(w),lambda *args,**kw:None)
        p=result['parts'][0]
        expected=np.abs(w).reshape(256,2,32,4).mean(axis=(1,3),dtype=np.float64).reshape(16,16,32)
        np.testing.assert_allclose(np.asarray(p['full']).reshape(16,16,32),expected,rtol=1e-6)
        np.testing.assert_allclose(p['feature'],p['full'],rtol=5e-5,atol=1e-6)
        self.assertEqual(result['spectral']['retained'],1)
        result['shape']=list(w.shape);validate(result)
    def test_gdn_segments_coverage(self):
        w=np.ones((8192,16),dtype=np.float32)
        ref={'fold':{'basis':'segments','segments':[
            {'name':'q','rows':[0,2048],'factors':[16,128,16]},
            {'name':'k','rows':[2048,4096],'factors':[16,128,16]},
            {'name':'v','rows':[4096,8192],'factors':[32,128,16]}]}}
        parts=d.pack_parts(w,ref)
        self.assertEqual(sum(sum(p['counts']) for p in parts),w.size)
        self.assertEqual([p['name'] for p in parts],['q','k','v'])


if __name__=='__main__':unittest.main(verbosity=2)

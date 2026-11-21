"""全类型探路的解码、还原、分段与池化；方法见 docs/type_survey.md。"""
from pathlib import Path
import hashlib
import json
import math

import numpy as np
from gguf.quants import dequantize, GGML_QUANT_SIZES

ROOT = Path(__file__).resolve().parent.parent
TOPO = ROOT / 'prototype/data/qwen35_9b.topo.json'
FILES = {'text': ROOT/'data/gguf/Qwen3.5-9B-Q4_K_M.gguf', 'vision': ROOT/'data/gguf/mmproj-BF16.gguf'}
LAYERS = {'full': [3,15,31], 'gdn': [0,16,30], 'vision': [0,13,26]}


def scope():
    doc = json.loads(TOPO.read_text(encoding='utf-8'))
    blocks=[]
    for b in doc['blocks']:
        if b.get('layer') in LAYERS['full']+LAYERS['gdn'] or b.get('vlayer') in LAYERS['vision'] or ('layer' not in b and 'vlayer' not in b):
            blocks.append(b)
    refs={}
    for b in blocks:
        for t in b['tensors']:
            key=t['file']+':'+t['gguf']
            assert key not in refs
            refs[key]=t
    assert len(blocks)==65 and len(refs)==124,(len(blocks),len(refs))
    signatures=lambda ref:(ref['file'],ref['gguf'].split('.',2)[-1] if ref['file']=='text' and ref['gguf'].startswith('blk.') else ref['gguf'].split('.',3)[-1] if ref['gguf'].startswith('v.blk.') else ref['gguf'])
    allrefs=[t for b in doc['blocks'] for t in b['tensors']]
    assert {signatures(t) for t in allrefs}=={signatures(t) for t in refs.values()},'张量类型未全覆盖'
    return {'layers':LAYERS,'blocks':blocks,'references':refs,'geometry_only':doc['geometry_only'],
            'topology_id':doc['topology_id'],'topology_sha256':sha(TOPO),
            'total_source_tensors':len(allrefs),'all_type_signatures_covered':True,
            'quantization_variants_not_selected':sorted({(*signatures(t),t['qtype']) for t in allrefs}-{(*signatures(t),t['qtype']) for t in refs.values()})}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk:=f.read(4*1024*1024): h.update(chunk)
    return h.hexdigest()


def restore(w, rule):
    if not rule: return w
    if rule=='minus_one': return w-1
    permutation=np.argsort([(j%16)*2+j//16 for j in range(32)])
    if rule=='log_neg_then_vhead_perm':
        if not np.all(w<0): raise ValueError('ssm_a 非负，不能还原 A_log')
        return np.log(-w)[permutation]
    if rule=='vhead_perm': return w[permutation]
    if rule=='vhead_perm_rows': return w[permutation]
    if rule=='vhead_perm_rows_x128': return w.reshape(32,128,-1)[permutation].reshape(w.shape)
    if rule=='vhead_perm_cols_x128': return w.reshape(w.shape[0],32,128)[:,permutation].reshape(w.shape)
    if rule=='vhead_perm_rows_x128_v_segment':
        w=w.copy();w[4096:8192]=w[4096:8192].reshape(32,128,-1)[permutation].reshape(4096,-1)
        return w
    raise ValueError('未知还原规则 '+rule)


class TensorSource:
    def __init__(self,tensor,ref):
        self.tensor,self.ref=tensor,ref
        self.shape=tuple(reversed(tensor.shape.tolist()))
        assert self.shape==tuple(ref['shape']),(tensor.name,self.shape,ref['shape'])
        assert tensor.tensor_type.name==ref['qtype']
        self.packed_sha256=hashlib.sha256(memoryview(tensor.data).cast('B')).hexdigest()
    def decode(self):
        w=np.ascontiguousarray(dequantize(self.tensor.data,self.tensor.tensor_type).reshape(self.shape),dtype=np.float32)
        w=restore(w,self.ref.get('restore'))
        if not np.isfinite(w).all(): raise ValueError('非有限解码值')
        return w
    def rows(self,start,end):
        if len(self.shape)!=2 or self.ref.get('restore'): raise ValueError('流式路径仅供无需还原的二维大矩阵')
        rows,cols=self.shape
        if not 0<=start<end<=rows: raise ValueError('行范围无效')
        block,bytes_=GGML_QUANT_SIZES[self.tensor.tensor_type]
        assert cols%block==0
        stride=cols//block*bytes_
        raw=self.tensor.data.view(np.uint8).reshape(rows,stride)[start:end]
        return np.ascontiguousarray(dequantize(raw,self.tensor.tensor_type).reshape(end-start,cols),dtype=np.float32)


def factor(n):
    # 几何折叠，选接近 1:2 的因子；没有语义聚类或排序。
    goal=max(1,int(math.sqrt(n/2)))
    return max(i for i in range(1,goal+1) if n%i==0)


def split_parts(w,ref):
    fold=ref.get('fold',{})
    if fold.get('basis')=='segments':
        parts=[]
        for s in fold['segments']:
            f=s['factors']; parts.append((s['name'],w[s['rows'][0]:s['rows'][1]].reshape(f),{'basis':'segments','rows':s['rows'],'factors':f}))
        return parts
    if fold.get('basis')=='structure':
        f=fold['factors']; data=w.T if fold.get('axis')=='cols' else w
        return [('main',data.reshape(f),fold)]
    if w.ndim==1:
        f=factor(w.size);b=factor(w.size//f)
        return [('main',w.reshape(f,b,w.size//f//b),{'basis':'sequential_vector','factors':[f,b,w.size//f//b]})]
    matrix=w.reshape(w.shape[0],-1)
    if matrix.shape[0]<matrix.shape[1]: matrix=matrix.T;axis='cols'
    else: axis='rows'
    f=factor(matrix.shape[0])
    data=matrix.reshape(f,matrix.shape[0]//f,matrix.shape[1])
    return [('main',data,{'basis':'geometric','axis':axis,'factors':list(data.shape),'original_shape':list(w.shape)})]


def pooled(part, absolute=True):
    dims=tuple(min(n,k) for n,k in zip(part.shape,(16,16,32)))
    bounds=[np.linspace(0,n,g+1,dtype=np.int64) for n,g in zip(part.shape,dims)]
    a=np.abs(part) if absolute else part
    for axis,edges in enumerate(bounds): a=np.add.reduceat(a,edges[:-1],axis=axis,dtype=np.float64)
    counts=np.diff(bounds[0])[:,None,None]*np.diff(bounds[1])[None,:,None]*np.diff(bounds[2])[None,None,:]
    assert int(counts.sum())==part.size and counts.min()>0
    values=(a/counts).astype(np.float32)
    expected=np.abs(part).sum(dtype=np.float64) if absolute else part.sum(dtype=np.float64)
    np.testing.assert_allclose(np.sum(values.astype(np.float64)*counts),expected,rtol=2e-6,atol=1e-5)
    return values,counts


def pack_parts(w,ref):
    result=[]
    for name,data,fold in split_parts(w,ref):
        values,counts=pooled(data)
        signed,_=pooled(data,False)
        result.append({'name':name,'grid':list(values.shape),'fold':fold,'counts':counts.ravel().tolist(),
                       'full':values.ravel().tolist(),'signed':signed.ravel().tolist()})
    return result


def assign_channel(parts,w,ref,key):
    split=split_parts(w,ref)
    assert len(split)==len(parts)
    for result,(name,data,_) in zip(parts,split):
        values,_=pooled(data)
        assert result['name']==name and result['grid']==list(values.shape)
        result[key]=values.ravel().tolist()


def self_test():
    for shape in ((3,5,7),(1,1,32),(17,31,65)):
        w=np.arange(np.prod(shape),dtype=np.float32).reshape(shape)-10
        v,count=pooled(w)
        assert count.sum()==w.size
        np.testing.assert_allclose(np.sum(v*count),np.abs(w).sum(),rtol=1e-6)
    p=np.array([(j%16)*2+j//16 for j in range(32)])
    hf=np.arange(32,dtype=np.float32)
    np.testing.assert_array_equal(restore(hf[p],'vhead_perm'),hf)
    np.testing.assert_allclose(restore(-np.exp(hf[p]/32),'log_neg_then_vhead_perm'),hf/32,atol=1e-6)
    for rule,shape in [('vhead_perm_rows_x128',(4096,4)),('vhead_perm_cols_x128',(4,4096)),('vhead_perm_rows_x128_v_segment',(8192,4))]:
        original=np.arange(np.prod(shape),dtype=np.float32).reshape(shape)
        if rule.endswith('v_segment'):
            gg=original.copy();gg[4096:]=original[4096:].reshape(32,128,-1)[p].reshape(4096,-1)
        elif 'cols' in rule: gg=original.reshape(4,32,128)[:,p].reshape(shape)
        else: gg=original.reshape(32,128,-1)[p].reshape(shape)
        np.testing.assert_array_equal(restore(gg,rule),original)
    for shape in ((32,),(128,),(4304,),(1152,3,16,16),(4096,12288)):
        w=np.ones(shape,dtype=np.float32)
        for _,part,_ in split_parts(w,{}):
            v,_=pooled(part);np.testing.assert_array_equal(v,np.ones_like(v))
    return '还原逆置换、奇数分箱均值、常数及各形状折叠通过'

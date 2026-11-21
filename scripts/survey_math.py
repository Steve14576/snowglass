"""按类型计算；大矩阵全行覆盖、分块解码，不把局部样本冒充整张。"""
import time
import numpy as np
from survey_data import pack_parts,assign_channel,factor,pooled

SEED=20261121


def stats(w):
    return {'mean_abs':float(np.abs(w).mean(dtype=np.float64)),
            'rms':float(np.sqrt(np.einsum('i,i->',w.ravel(),w.ravel(),dtype=np.float64)/w.size)),
            'minimum':float(w.min()),'maximum':float(w.max()),'zero_fraction':float(np.mean(w==0))}


def snapshot(w,q,rank):
    b=q.T@w
    ub,s,vt=np.linalg.svd(b.astype(np.float64),full_matrices=False)
    return (q@ub[:,:rank]).astype(np.float32),s[:rank],vt[:rank].astype(np.float32)


def spectral_matrix(w,ref,parts,info,tick):
    rank=min(256,min(w.shape)); width=min(rank+16,min(w.shape))
    threshold=info['rms']*sum(np.sqrt(w.shape))
    omega=np.random.default_rng(SEED).standard_normal((w.shape[1],width),dtype=np.float32)
    q,_=np.linalg.qr(w@omega)
    snapshots={}
    for iteration in range(1,13):
        z,_=np.linalg.qr(w.T@q);q,_=np.linalg.qr(w@z)
        tick('谱迭代',iteration=iteration,rank=rank)
        if iteration in (8,12):
            u,s,vt=snapshot(w,q,rank)
            mask=s>threshold
            reconstructed=(u[:,mask]*s[mask].astype(np.float32))@vt[mask]
            pooled_values=[]
            from survey_data import split_parts
            for _,part,_ in split_parts(reconstructed,ref): pooled_values.extend(pooled(part)[0].ravel())
            snapshots[iteration]={'k':int(mask.sum()),'values':np.asarray(pooled_values),'s':s.copy()}
            if iteration==12:
                assign_channel(parts,reconstructed,ref,'feature')
                residual=w-reconstructed
                assign_channel(parts,residual,ref,'residual')
                error=float(np.max(np.abs((residual+reconstructed)-w)))
            del reconstructed
    final=snapshots[12];early=snapshots[8]
    return {'method':'spectral','rank_limit':rank,'iterations':12,'retained':final['k'],
            'rank_capped':final['k']==rank and rank<min(w.shape),
            'threshold':threshold,'energy_fraction':float(np.sum(final['s'][:final['k']]**2)/(info['rms']**2*w.size)) if info['rms'] else 0,
            'pooled_iteration_change':float(np.linalg.norm(final['values']-early['values'])/max(np.linalg.norm(final['values']),1e-30)),
            'retained_power8':early['k'],'reconstruction_max_error':error,
            'singular_values':final['s'].tolist(),'threshold_counts':{str(v):int((final['s']>v*threshold).sum()) for v in (.8,1,1.2)}}


def dense(source,tick):
    w=source.decode();tick('解码与约定还原完成')
    info=stats(w);parts=pack_parts(w,source.ref)
    valid=w.ndim==2 and min(w.shape)>=64 and info['rms']>0
    if valid:
        spectral=spectral_matrix(w,source.ref,parts,info,tick)
    else:
        for p in parts:p['feature']=p['full'].copy();p['residual']=None
        spectral={'method':'direct','reason':'零数组或一维／窄矩阵／高维核：不硬套谱分解','retained':None,'rank_capped':False,'pooled_iteration_change':None}
    if w.ndim==2:
        row=np.sqrt(np.einsum('ij,ij->i',w,w,dtype=np.float64)/w.shape[1])
        col=np.sqrt(np.einsum('ij,ij->j',w,w,dtype=np.float64)/w.shape[0])
        outer=np.outer(row,col).astype(np.float32)
        if outer.mean(dtype=np.float64):outer*=info['mean_abs']/outer.mean(dtype=np.float64)
        assign_channel(parts,outer,source.ref,'rowcol')
    else:
        for p in parts:p['rowcol']=None
    assert sum(sum(p['counts']) for p in parts)==w.size
    return {'statistics':info,'spectral':spectral,'parts':parts}


def stream_reduce(source,frames,tick):
    """帧函数返回 full/signed/feature/residual；按连续行组平均再几何折叠。"""
    m,n=source.shape; nr,nc=256,32
    rb=np.linspace(0,m,nr+1,dtype=int);cb=np.linspace(0,n,nc+1,dtype=int)
    sums={key:np.zeros((nr,nc),dtype=np.float64) for key in ('full','signed','feature','residual','rowcol')}
    counts=np.diff(rb)[:,None]*np.diff(cb)[None,:]
    for i in range(nr):
        a,b=int(rb[i]),int(rb[i+1]);w=source.rows(a,b)
        data=frames(w,a,b)
        for key,values in data.items():
            summed=values.sum(axis=0,dtype=np.float64)
            sums[key][i]=np.add.reduceat(summed,cb[:-1])
        if i%32==0:tick('大矩阵池化',row=b,total=m)
    assert counts.sum()==m*n
    shape=(16,16,32)
    return [{'name':'main','grid':list(shape),'fold':{'basis':'stream_row_bins','row_groups':256,'row_group_shape':[16,16],
            'column_groups':32,'note':'连续词表行分箱后折叠，无 token 聚类；是几何展示'},
            'counts':counts.reshape(shape).ravel().tolist(),
            **{k:(v/counts).astype(np.float32).reshape(shape).ravel().tolist() for k,v in sums.items()}}]


def streaming(source,tick):
    """96方向、4次右侧子空间迭代。全覆盖但精度低于普通矩阵，明确标注。"""
    m,n=source.shape;rank=96;width=rank+16;chunk=2048
    z,_=np.linalg.qr(np.random.default_rng(SEED).standard_normal((n,width),dtype=np.float32))
    row2=np.zeros(m,dtype=np.float64);col2=np.zeros(n,dtype=np.float64)
    abs_sum=0.;minimum=float('inf');maximum=-float('inf');zeros=0
    for iteration in range(4):
        accumulation=np.zeros((n,width),dtype=np.float64)
        for start in range(0,m,chunk):
            end=min(m,start+chunk);w=source.rows(start,end)
            accumulation+=w.T@(w@z)
            if iteration==0:
                row2[start:end]=np.einsum('ij,ij->i',w,w,dtype=np.float64)
                col2+=np.einsum('ij,ij->j',w,w,dtype=np.float64)
                abs_sum+=float(np.abs(w).sum(dtype=np.float64))
                minimum=min(minimum,float(w.min()));maximum=max(maximum,float(w.max()));zeros+=int(np.count_nonzero(w==0))
            if start%(chunk*8)==0:tick('大矩阵分块子空间迭代',iteration=iteration+1,row=end,total=m)
        z,_=np.linalg.qr(accumulation.astype(np.float32))
    mean_abs=abs_sum/(m*n);rms=float(np.sqrt(row2.sum()/(m*n)));threshold=rms*(np.sqrt(m)+np.sqrt(n))
    y=np.empty((m,width),dtype=np.float32)
    for start in range(0,m,chunk):
        end=min(m,start+chunk);y[start:end]=source.rows(start,end)@z
        if start%(chunk*8)==0:tick('大矩阵左侧投影',row=end,total=m)
    q,_=np.linalg.qr(y);del y
    b=np.zeros((width,n),dtype=np.float64)
    for start in range(0,m,chunk):
        end=min(m,start+chunk);b+=q[start:end].T@source.rows(start,end)
        if start%(chunk*8)==0:tick('大矩阵小谱矩阵',row=end,total=m)
    ub,s,vt=np.linalg.svd(b,full_matrices=False)
    u=(q@ub[:,:rank]).astype(np.float32);s=s[:rank];vt=vt[:rank].astype(np.float32);del q,b
    keep=s>threshold;left=u[:,keep]*s[keep].astype(np.float32);right=vt[keep]
    rows=np.sqrt(row2/n);cols=np.sqrt(col2/m);outer_mean=float(rows.mean()*cols.mean())
    def frames(w,a,b):
        reconstructed=left[a:b]@right
        return {'full':np.abs(w),'signed':w,'feature':np.abs(reconstructed),'residual':np.abs(w-reconstructed),
                'rowcol':(rows[a:b,None]*cols[None,:]*(mean_abs/outer_mean if outer_mean else 0)).astype(np.float32)}
    parts=stream_reduce(source,frames,tick)
    weighted=sum(v*c for v,c in zip(parts[0]['full'],parts[0]['counts']))/(m*n)
    np.testing.assert_allclose(weighted,mean_abs,rtol=1e-6)
    return {'parts':parts,'statistics':{'mean_abs':mean_abs,'rms':rms,'minimum':minimum,'maximum':maximum,'zero_fraction':zeros/(m*n)},
            'spectral':{'method':'stream_spectral','rank_limit':rank,'iterations':4,'retained':int(keep.sum()),
                        'rank_capped':bool(keep[-1]),'threshold':threshold,'energy_fraction':float(np.sum(s[keep]**2)/row2.sum()),
                        'pooled_iteration_change':None,'convergence_note':'全矩阵覆盖；本轮仅一档流式精度，未作额外迭代收敛对照',
                        'singular_values':s.tolist(),'threshold_counts':{str(v):int((s>v*threshold).sum()) for v in (.8,1,1.2)}}}

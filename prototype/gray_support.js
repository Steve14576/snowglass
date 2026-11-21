/* 幅度选取与显示灰度分开；六邻接仅描述几何，不改变掩膜。 */
(() => {
  'use strict';
  function jaccard(a,b) {
    let union=0,intersection=0;
    for(let i=0;i<a.length;i++){if(a[i]||b[i])union++;if(a[i]&&b[i])intersection++;}
    return union ? intersection/union : null;
  }
  function describe(mask,dims) {
    const [nx,ny,nz]=dims,yz=ny*nz,visited=new Uint8Array(mask.length);
    const axisCounts=dims.map(n=>Array(n).fill(0)),groups=[];
    let retained=0;
    for(let i=0;i<mask.length;i++)if(mask[i]){
      const x=Math.floor(i/yz),y=Math.floor(i%yz/nz),z=i%nz;
      retained++;axisCounts[0][x]++;axisCounts[1][y]++;axisCounts[2][z]++;
    }
    for(let first=0;first<mask.length;first++){
      if(!mask[first]||visited[first])continue;
      const stack=[first],lo=[nx,ny,nz],hi=[0,0,0];let cells=0;visited[first]=1;
      while(stack.length){
        const i=stack.pop(),x=Math.floor(i/yz),y=Math.floor(i%yz/nz),z=i%nz;
        cells++;[x,y,z].forEach((v,a)=>{lo[a]=Math.min(lo[a],v);hi[a]=Math.max(hi[a],v);});
        const next=[];
        if(x)next.push(i-yz);if(x+1<nx)next.push(i+yz);
        if(y)next.push(i-nz);if(y+1<ny)next.push(i+nz);
        if(z)next.push(i-1);if(z+1<nz)next.push(i+1);
        for(const j of next)if(mask[j]&&!visited[j]){visited[j]=1;stack.push(j);}
      }
      groups.push({cells,bounds:[lo,hi]});
    }
    groups.sort((a,b)=>b.cells-a.cells);
    return {retained,axisCounts,componentCount:groups.length,largest:groups[0]||null,
      largestFraction:retained?groups[0].cells/retained:null};
  }
  function calculate(values,reference,dims,cutoff,gain,gamma) {
    if(![reference,cutoff,gain,gamma].every(Number.isFinite)||reference<=0||cutoff<0||gain<=0||gamma<=0)
      throw new Error('无效的区域筛选或显影参数');
    const normalized=Array.from(values,v=>v/reference);
    const mask=normalized.map(v=>Number(v>cutoff));
    const gray=normalized.map(v=>Math.pow(Math.min(1,Math.max(0,gain*v)),gamma));
    const arrays=[gray,mask,gray.map((v,i)=>mask[i]?v:0)];
    const info=describe(mask,dims);
    const lower=normalized.map(v=>Number(v>Math.max(0,cutoff-.01)));
    const upper=normalized.map(v=>Number(v>cutoff+.01));
    return {arrays,mask,normalized,info,range:[Math.min(...normalized),Math.max(...normalized)],
      neighbor:{lowerCount:lower.reduce((a,b)=>a+b,0),upperCount:upper.reduce((a,b)=>a+b,0),
        lowerJaccard:jaccard(mask,lower),upperJaccard:jaccard(mask,upper)}};
  }
  function summary(container,result,dims,cutoff) {
    const {info,neighbor,range}=result,n=result.mask.length;
    const pct=v=>v===null?'无定义':(v*100).toFixed(1)+'%';
    const empty=info.retained===0?'当前门槛没有选中任何格子；这不等于该张量没有信息。':'';
    container.innerHTML=`<strong>入选 ${info.retained} / ${n}，留空 ${pct(1-info.retained/n)}</strong> · 归一谱幅度范围 ${range[0].toFixed(4)}–${range[1].toFixed(4)}<br>`+
      `六邻接 ${info.componentCount} 个连通块；最大块占入选格 ${pct(info.largestFraction)}。连通不等于片状，也不表示语义聚类。<br>`+
      `门槛 −0.01：${neighbor.lowerCount} 格，重合 ${pct(neighbor.lowerJaccard)}；+0.01：${neighbor.upperCount} 格，重合 ${pct(neighbor.upperJaccard)}。`+
      `<p class="support-note">${empty||'门槛只在原统计上选位置；曝光与幂次只改保留区域内灰度。没有平滑、补面或自动保留百分比。'}</p>`;
    const profiles=document.createElement('div');profiles.className='profiles';
    info.axisCounts.forEach((counts,axis)=>{
      const figure=document.createElement('figure');figure.className='support-profile';
      const capacity=n/dims[axis],step=240/counts.length;
      const bars=counts.map((v,i)=>`<rect x="${i*step+.5}" y="${70-v/capacity*64}" width="${Math.max(1,step-1)}" height="${v/capacity*64}"/>`).join('');
      figure.innerHTML=`<figcaption>${'xyz'[axis]} 方向 · 每层入选率（满高＝100%）</figcaption>`+
        `<svg viewBox="0 0 240 76" role="img" aria-label="${'xyz'[axis]}方向各层入选数：${counts.join(',')}"><path d="M0 70H240"/>${bars}</svg>`+
        `<div class="counts">从第 0 层起：${counts.join(' / ')}</div>`;
      profiles.appendChild(figure);
    });
    container.appendChild(profiles);
  }
  window.GraySupport={calculate,describe,jaccard,summary};
})();

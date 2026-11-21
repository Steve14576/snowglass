/* 基于旧类型页重新建立的独立对照，只读取此目录的副本数据。 */
(async()=>{
  'use strict';
  const $=id=>document.getElementById(id),cache=new Map();
  const controls=['part','channel','mode','window','black','white','gamma','oldgain','size','axis','slice','slab'];
  const defaults={part:'all',channel:'full',mode:'opaque',window:'range',black:0,white:1,gamma:1,oldgain:2,size:.45,axis:1,slice:.5,slab:false};
  let manifest,block,loaded=[],pieces=[],scenes,state,request=0,queued=false;
  function settings(){return Object.fromEntries(controls.map(id=>[id,id==='slab'?$(id).checked:$(id).value]));}
  function apply(values){Object.entries(values).forEach(([id,v])=>{if(id==='slab')$(id).checked=v;else $(id).value=v;});return draw();}
  async function read(path){const response=await fetch(path,{cache:'no-store'});if(!response.ok)throw Error(`${response.status} ${path}`);return response.json();}
  function family(b){if(b.id==='mtp'||(!('layer'in b)&&!b.id.startsWith('V')))return'end';
    if(b.id.startsWith('V'))return'vision';return manifest.layers.full.includes(b.layer)?'full':'gdn';}
  function list(){
    $('blocks').textContent='';const query=$('find').value.toLowerCase(),filter=$('family').value;
    const items=manifest.blocks.concat(manifest.geometry_only).filter(b=>(filter==='all'||family(b)===filter)&&(b.id+' '+b.label).toLowerCase().includes(query));
    items.forEach(b=>{const button=document.createElement('button');button.className='block-button';button.dataset.block=b.id;
      button.setAttribute('aria-pressed',String(block?.id===b.id));button.append(document.createTextNode(b.id+' · '+b.label));
      const small=document.createElement('small');small.textContent=`${b.tensors?.length||0} 个独立张量`;button.append(small);
      button.onclick=()=>select(b.id);$('blocks').append(button);});
    $('catalog-count').textContent=`${items.length} 项 / 65 组＋1 缺权重项`;
  }
  async function select(id){
    const token=++request;block=manifest.blocks.concat(manifest.geometry_only).find(b=>b.id===id);
    if(!block)throw Error('功能组不存在');list();$('block-title').textContent=block.id+' · '+block.label;
    $('status').textContent='正在读取独立副本……';
    try{
      const values=await Promise.all((block.tensors||[]).map(async ref=>{
        const key=ref.file+':'+ref.gguf,index=manifest.tensors.find(t=>t.key===key);
        if(!index)throw Error('缺少张量 '+key);
        if(!cache.has(key))cache.set(key,await read('data/'+index.data_file));return cache.get(key);
      }));
      if(token!==request)return;loaded=values;pieces=[];
      values.forEach(t=>t.parts.forEach(p=>pieces.push({...p,id:t.key+':'+p.name,tensor:t})));
      $('part').textContent='';$('part').add(new Option('完整功能组（各子区共用本张量窗口）','all'));
      pieces.forEach((p,i)=>$('part').add(new Option(`${i+1} · ${p.tensor.name} / ${p.name}`,p.id)));
      $('part').value='all';draw();
    }catch(error){if(token===request){$('status').textContent='载入失败：'+error.message;console.error(error);}}
  }
  function slice(canvas,values,dims,axis,relative){
    const others=[0,1,2].filter(v=>v!==axis),width=dims[others[1]],height=dims[others[0]],level=Math.round(relative*(dims[axis]-1));
    canvas.width=width;canvas.height=height;const ctx=canvas.getContext('2d'),img=ctx.createImageData(width,height);
    for(let y=0;y<height;y++)for(let x=0;x<width;x++){
      const xyz=[0,0,0];xyz[axis]=level;xyz[others[0]]=height-1-y;xyz[others[1]]=x;
      const value=values[(xyz[0]*dims[1]+xyz[1])*dims[2]+xyz[2]],i=(y*width+x)*4;
      img.data[i]=img.data[i+1]=img.data[i+2]=Math.round(value*255);img.data[i+3]=255;
    }ctx.putImageData(img,0,0);
  }
  function draw(){
    if(!manifest||!block)return false;const s=settings(),visible=pieces.filter(p=>s.part==='all'||s.part===p.id);
    const render=[],stats=Array.from({length:3},()=>({cells:0,black:0,white:0,sum:0})),warnings=[];
    try{visible.forEach(p=>{
      const result=ContrastMath.arrays(p,p.tensor,s.channel,s);
      render.push({id:p.id,grid:p.grid,...result,tensor:p.tensor});
      result.arrays.forEach((a,i)=>a.forEach(v=>{if(!Number.isFinite(v))throw Error('非有限灰度');stats[i].cells++;stats[i].sum+=v;if(v===0)stats[i].black++;if(v===1)stats[i].white++;}));
      if(result.used!==s.channel)warnings.push(p.tensor.name+'：该通道不适用，直接幅度对照');
      if(p.tensor.spectral.method==='direct'&&s.channel==='feature')warnings.push(p.tensor.name+'：未作 SVD，特征是直接幅度');
      if(p.tensor.spectral.rank_capped)warnings.push(p.tensor.name+'：既有谱截断限制未变');
      if(result.window.constant)warnings.push(p.tensor.name+'：恒定通道，不人为制造纹理');
    });}catch(error){$('status').textContent=error.message+'；仍显示上一次有效结果。';return false;}
    $('pieces').textContent='';render.forEach((p,i)=>{
      const li=document.createElement('li'),head=document.createElement('div');
      head.textContent=`${p.tensor.name} / ${p.id.split(':').at(-1)} · ${p.used} · ${p.tensor.quantization} · ${p.grid.join('×')} 格`;
      const span=document.createElement('div');span.className='range';const fmt=v=>Number(v).toPrecision(6),w=p.window,r=p.tensor.reference_white;
      span.textContent=`源窗口 [${fmt(w.low)}, ${fmt(w.high)}]，旧归一范围 [${r?fmt(w.low/r):'0'}, ${r?fmt(w.high/r):'0'}] → 0–1；`+
        `相对旧曝光1放大 ${p.amplification===null?'不适用':p.amplification.toFixed(2)+'×'}；右列 [${fmt(p.manual[0])}, ${fmt(p.manual[1])}]`;
      li.append(head,span);$('pieces').append(li);
    });
    document.querySelectorAll('.card').forEach((card,column)=>{
      const region=card.querySelector('.slices');region.textContent='';
      render.forEach((p,i)=>{const figure=document.createElement('figure');figure.className='survey-slice';
        const title=document.createElement('figcaption');title.textContent=`分区 ${i+1} · ${'xyz'[+s.axis]} 单层`;
        const canvas=document.createElement('canvas');canvas.setAttribute('aria-label',`${column+1}列${title.textContent}`);
        figure.append(title,canvas);region.append(figure);slice(canvas,p.arrays[column],p.grid,+s.axis,+s.slice);});
      const t=stats[column];card.querySelector('.survey-card-stats').textContent=t.cells?
        `${t.cells} 格全部保留 · 显示黑 ${(100*t.black/t.cells).toFixed(2)}% / 白 ${(100*t.white/t.cells).toFixed(2)}% · 平均灰度 ${(t.sum/t.cells).toFixed(3)}`:
        'MTP 没有权重：不补任何数值纹理。';
    });
    if(scenes&&render.length)scenes.update(render,{size:+s.size,mode:s.mode,axis:+s.axis,slice:+s.slice,slab:s.slab});
    else if(scenes){scenes.views.forEach(v=>v.scene.children.slice().forEach(o=>{v.scene.remove(o);o.geometry?.dispose();o.material?.dispose();}));scenes.base.render();}
    ['black','white','gamma','oldgain','size','slice'].forEach(id=>$(id+'-out').textContent=(+s[id]).toFixed(2));
    $('block-source').textContent=`副本 20261122-033209-256746 · ${loaded.length}/${block.tensors?.length||0} 张量 · ${pieces.length} 子区 · 不修改原数据，不筛点位`;
    $('status').textContent=[...new Set(warnings)].join('；')||'当前通道按真实跨度展开；黑白只是相对数值，全部格子仍保留。';
    $('manifest-info').textContent=JSON.stringify({source_run:manifest.source_run,mapping:manifest.mapping,settings:s,
      tensors:loaded.map(t=>({key:t.key,original_sha256:t.original_data_sha256,windows:t.windows,spectral:t.spectral})),
      source_hashes:manifest.source_hashes},null,2);
    state={block:block.id,settings:s,pieces:render,statistics:stats,warnings};return true;
  }
  function schedule(){if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;draw();});}
  try{
    manifest=await read('data/manifest.json');if(manifest.schema!=='snowglass.contrast-survey.v1')throw Error('副本格式错误');
    $('family').oninput=$('find').oninput=list;controls.forEach(id=>$(id).oninput=schedule);
    $('reset').onclick=()=>apply(defaults);$('camera').onclick=()=>scenes?.fit();
    $('save').onclick=()=>{const obj={schema:'snowglass.contrast-view.v1',source_run:manifest.source_run,block:block.id,settings:state.settings,
      pieces:state.pieces.map(p=>({id:p.id,channel:p.used,grid:p.grid,window:p.manual,gray:p.arrays[2]}))};
      const url=URL.createObjectURL(new Blob([JSON.stringify(obj)],{type:'application/json'})),a=document.createElement('a');
      a.href=url;a.download=`contrast_${Date.now()}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
    window.contrastTest={select,apply,get state(){return state;},get views(){return scenes?.views;},manifest,cache,math:ContrastMath};
    await select(new URLSearchParams(location.search).get('block')||'L16.down');
    try{scenes=await TypeSurveyScene.create([...document.querySelectorAll('.viewport')]);draw();}
    catch(error){$('status').textContent='二维统计已展开，三维不可用：'+error.message;console.error(error);}
  }catch(error){$('status').textContent='加载失败：'+error.message;console.error(error);}
})();

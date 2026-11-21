/* 类型观察页只读独立运行目录，不写原编辑器 localStorage。 */
(async()=>{
  'use strict';
  const $=id=>document.getElementById(id),query=new URLSearchParams(location.search);
  const run=query.get('run'),cache=new Map(),controls=['part','channel','mode','gain','gamma','cutoff','size','axis','slice','slab'];
  let manifest,scenes,block,loaded=[],pieces=[],sequence=0,state,scheduled=false;
  function config(){return Object.fromEntries(controls.map(id=>[id,id==='slab'?$(id).checked:$(id).value]));}
  function apply(values){Object.entries(values).forEach(([id,v])=>{if(id==='slab')$(id).checked=v;else $(id).value=v;});draw();}
  async function json(path){const response=await fetch(path,{cache:'no-store'});if(!response.ok)throw new Error(`${response.status} ${path}`);return response.json();}
  function family(b){if(b.id==='mtp'||(!('layer'in b)&&!b.id.startsWith('V')))return'end';
    if(b.id.startsWith('V'))return'vision';return manifest.layers.full.includes(b.layer)?'full':'gdn';}
  function list(){
    $('blocks').textContent='';const search=$('find').value.toLowerCase(),filter=$('family').value;
    const items=manifest.blocks.concat(manifest.geometry_only).filter(b=>(filter==='all'||family(b)===filter)&&
      (b.id+' '+b.label).toLowerCase().includes(search));
    for(const b of items){const button=document.createElement('button');button.className='block-button';
      button.setAttribute('aria-pressed',String(block?.id===b.id));button.dataset.block=b.id;
      button.append(document.createTextNode(b.id+' · '+b.label));
      const small=document.createElement('small');small.textContent=b.tensors?`${b.tensors.length} 个张量`:'无权重 · 只保留空框身份';button.append(small);
      button.onclick=()=>select(b.id);$('blocks').append(button);}
    $('catalog-count').textContent=`当前 ${items.length} 项；总计 ${manifest.blocks.length} 功能组＋${manifest.geometry_only.length} 空框`;
  }
  async function data(ref){const key=ref.file+':'+ref.gguf;
    if(!cache.has(key)){
      const index=manifest.tensors.find(t=>t.key===key);if(!index)throw new Error('缺少已完成张量 '+key);
      cache.set(key,await json(`data/type_surveys/${run}/${index.data_file}`));
    }return cache.get(key);}
  async function select(id){
    const token=++sequence;block=manifest.blocks.concat(manifest.geometry_only).find(b=>b.id===id);
    if(!block)throw new Error('功能组不存在');list();$('block-title').textContent=block.id+' · '+block.label;
    $('status').textContent='正在载入功能组的全部独立张量……';
    try{
      const values=await Promise.all((block.tensors||[]).map(data));if(token!==sequence)return;
      loaded=values;pieces=[];
      values.forEach(t=>t.parts.forEach(p=>pieces.push({...p,id:t.key+':'+p.name,tensor:t})));
      $('part').textContent='';$('part').add(new Option('完整功能组（分区展示）','all'));
      pieces.forEach((p,i)=>$('part').add(new Option(`${i+1} · ${p.tensor.name} / ${p.name}`,p.id)));
      $('part').value='all';draw();
    }catch(e){if(token===sequence){loaded=[];pieces=[];draw();$('status').textContent='功能组未完整载入：'+e.message;}}
  }
  function sliced(canvas,a,dims,axis,relative){
    const other=[0,1,2].filter(v=>v!==axis),w=dims[other[1]],h=dims[other[0]],level=Math.round(relative*(dims[axis]-1));
    canvas.width=w;canvas.height=h;const ctx=canvas.getContext('2d'),img=ctx.createImageData(w,h);
    for(let r=0;r<h;r++)for(let c=0;c<w;c++){
      const xyz=[0,0,0];xyz[axis]=level;xyz[other[0]]=h-r-1;xyz[other[1]]=c;
      const v=a[(xyz[0]*dims[1]+xyz[1])*dims[2]+xyz[2]],i=(r*w+c)*4;
      img.data[i]=img.data[i+1]=img.data[i+2]=Math.round(v*255);img.data[i+3]=255;
    }ctx.putImageData(img,0,0);
  }
  function draw(){
    if(!manifest||!block)return;const s=config(),view=pieces.filter(p=>s.part==='all'||s.part===p.id);
    const render=[];const statistics=Array.from({length:3},()=>({cells:0,positive:0,saturated:0,sum:0}));
    $('pieces').textContent='';let caveats=[];
    view.forEach((p,i)=>{
      const t=p.tensor,r=t.reference_white;let channel=s.channel;
      if(!p[channel]){channel='full';caveats.push(t.name+'：所选通道不适用，使用直接幅度');}
      if(t.spectral.method==='direct'&&s.channel==='feature')caveats.push(t.name+'：不作谱分解，特征就是直接幅度');
      if(t.spectral.rank_capped)caveats.push(t.name+'：谱方向达到上限，结果截断');
      if(t.spectral.pooled_iteration_change===null&&t.spectral.method!=='direct')caveats.push(t.name+'：流式 96 方向／4 次，未作额外收敛核验');
      const full=p.full.map(v=>r>0?v/r:0),x=p[channel].map(v=>r>0?v/r:0),mask=x.map(v=>v>+s.cutoff);
      const mapping=v=>Math.pow(Math.min(1,Math.max(0,+s.gain*v)),+s.gamma);
      const arrays=[full.map(mapping),x.map(mapping),x.map((v,j)=>mask[j]?mapping(v):0)];
      arrays.forEach((a,col)=>a.forEach(v=>{statistics[col].cells++;statistics[col].sum+=v;if(v>0)statistics[col].positive++;if(v>=1)statistics[col].saturated++;}));
      render.push({id:p.id,grid:p.grid,arrays,mask,raw:x});
      const li=document.createElement('li');li.textContent=`${t.name} / ${p.name} · ${t.quantization} · ${t.shape.join('×')} → ${p.grid.join('×')} 格 · `+
        `${channel==='feature'&&t.spectral.method!=='direct'?'谱模式':channel==='rowcol'?'行列强度':'直接幅度'} · 入选 ${mask.filter(Boolean).length}/${x.length}`+
        ` · 每格 ${Math.min(...p.counts)}–${Math.max(...p.counts)} 个原始值`+(r===0?' · 全零，未人为增亮':'');
      $('pieces').append(li);
    });
    document.querySelectorAll('.card').forEach((card,col)=>{
      const target=card.querySelector('.slices');target.textContent='';
      render.forEach((p,i)=>{const fig=document.createElement('figure');fig.className='survey-slice';
        const caption=document.createElement('figcaption');caption.textContent=`分区 ${i+1} · ${'xyz'[+s.axis]} 单层切面`;
        const canvas=document.createElement('canvas');canvas.setAttribute('aria-label',caption.textContent);
        fig.append(caption,canvas);target.append(fig);sliced(canvas,p.arrays[col],p.grid,+s.axis,+s.slice);});
      const t=statistics[col];card.querySelector('.survey-card-stats').textContent=t.cells?
        `正灰度 ${t.positive} / ${t.cells} · 留空 ${(100*(1-t.positive/t.cells)).toFixed(1)}% · 平均灰度 ${(t.sum/t.cells).toFixed(3)} · 饱和 ${(100*t.saturated/t.cells).toFixed(1)}%`:
        '当前没有真实权重数据；不填模拟雪花。';
    });
    if(scenes&&render.length)scenes.update(render,{size:+s.size,mode:s.mode,axis:+s.axis,slice:+s.slice,slab:s.slab});
    else if(scenes)scenes.base.views.forEach(v=>{v.scene.children.slice().forEach(o=>{v.scene.remove(o);o.geometry?.dispose();o.material?.dispose();});scenes.base.render();});
    ['cutoff','gain','gamma','size','slice'].forEach(id=>$(id+'-out').textContent=(+s[id]).toFixed(id==='cutoff'?3:2));
    $('block-source').textContent=block.tensors?`${loaded.length} / ${block.tensors.length} 独立张量，${pieces.length} 子区。数字来源：${run}；只读原统计，分区是观察排布，不是最终模型布局。`:'MTP 权重未收录，保留身份与空框约定，没有真实雪花可评估。';
    $('status').textContent=Array.from(new Set(caveats)).join('；')||'真实统计已加载。门槛是观察参数，不是模型重要性判据。';
    $('manifest-info').textContent=JSON.stringify({run,layers:manifest.layers,completed:manifest.tensors.length,failures:manifest.failures,
      tensors:loaded.map(t=>({key:t.key,restore:t.restore,packed_sha256:t.packed_sha256,spectral:t.spectral,statistics:t.statistics,
        reference_white:t.reference_white,folds:t.parts.map(p=>p.fold)})),settings:s},null,2);
    state={block: block.id,settings:s,pieces:render,statistics,caveats};
  }
  function schedule(){if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;draw();});}
  try{
    if(!run||!/^run-\d{8}-\d{6}-\d{6}$/.test(run))throw new Error('需要指定已完成的运行目录 ?run=run-时间戳');
    manifest=await json(`data/type_surveys/${run}/manifest.json`);
    if(manifest.schema!=='snowglass.type-survey.v1')throw new Error('不是本页的结果格式');
    $('family').oninput=$('find').oninput=list;controls.forEach(id=>$(id).oninput=schedule);
    $('reset').onclick=()=>apply({channel:'feature',mode:'opaque',gain:2,gamma:1,cutoff:.25,size:.45,axis:1,slice:.5,slab:false,part:'all'});
    $('camera').onclick=()=>scenes?.fit();
    $('save').onclick=()=>{const obj={schema:'snowglass.type-survey-view.v1',run,block:block.id,settings:config(),
      pieces:state.pieces.map(p=>({id:p.id,grid:p.grid,indices:p.mask.flatMap((v,i)=>v?[i]:[]),gray:p.arrays[2].filter((v,i)=>p.mask[i])}))};
      const url=URL.createObjectURL(new Blob([JSON.stringify(obj,null,2)],{type:'application/json'})),a=document.createElement('a');
      a.href=url;a.download=`type_survey_view_${Date.now()}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
    window.typeSurveyTest={select,apply,draw,get state(){return state;},get views(){return scenes?.views;},get cache(){return cache;},manifest};
    await select(query.get('block')||'L03.mix1');
    try{scenes=await window.TypeSurveyScene.create(Array.from(document.querySelectorAll('.viewport')));draw();}
    catch(e){$('status').textContent='二维统计可看，三维不可用：'+e.message;}
  }catch(e){$('status').textContent='未能加载：'+e.message;console.error(e);}
})();

/* 读取确定的灰度统计；本页不写主编辑器的 localStorage。 */
(async () => {
  'use strict';
  const $ = id => document.getElementById(id);
  const cards = Array.from(document.querySelectorAll('.card'));
  const ids = ['tensor', 'resolution', 'render-mode', 'gain', 'gamma', 'threshold', 'residue', 'size', 'axis', 'slice', 'slab', 'cutoff'];
  const query = new URLSearchParams(location.search), supportStudy = query.get('study') === 'support';
  const defaults = {tensor:'attention', resolution:'fine', 'render-mode':'additive', gain:1, gamma:1, threshold:0, residue:.15, size:.45, axis:0, slice:8, slab:false, cutoff:.25};
  if (supportStudy) Object.assign(defaults, {gain:2, axis:1, 'render-mode':'opaque'});
  const run = query.get('run') || 'run-20261121-211150-652530';
  let scenes, samples = {}, manifest, queued = false, current;
  function settings() {
    return Object.fromEntries(ids.map(id => [id, id === 'slab' ? $(id).checked : $(id).value]));
  }
  function mapping(v, reference, gain, threshold, gamma) {
    return Math.pow(Math.max(0, Math.min(1, (gain * v / reference - threshold) / (1 - threshold))), gamma);
  }
  function downsample(a, dims) {
    const d = dims.map(v => v / 2), out = new Float64Array(d[0] * d[1] * d[2]);
    for (let x=0;x<dims[0];x++) for (let y=0;y<dims[1];y++) for (let z=0;z<dims[2];z++)
      out[(Math.floor(x/2)*d[1]+Math.floor(y/2))*d[2]+Math.floor(z/2)] += a[(x*dims[1]+y)*dims[2]+z] / 8;
    return out;
  }
  function slice(canvas, values, dims, axis, level) {
    const other = [0,1,2].filter(i => i !== axis), width = dims[other[1]], height = dims[other[0]];
    canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext('2d'), image = ctx.createImageData(width, height);
    for (let row=0;row<height;row++) for (let col=0;col<width;col++) {
      const xyz=[0,0,0]; xyz[axis]=level; xyz[other[0]]=height-row-1; xyz[other[1]]=col;
      const g = values[(xyz[0]*dims[1]+xyz[1])*dims[2]+xyz[2]], p=(row*width+col)*4;
      image.data[p]=image.data[p+1]=image.data[p+2]=Math.round(g*255); image.data[p+3]=255;
    }
    ctx.putImageData(image,0,0);
  }
  function update() {
    const s = settings(), sample = samples[s.tensor];
    if (!sample) return;
    const dims = s.resolution === 'fine' ? sample.grid : sample.grid.map(v=>v/2);
    const axis=+s.axis;
    $('slice').max = dims[axis]-1; $('slice').value = Math.min(+s.slice, dims[axis]-1); s.slice=$('slice').value;
    ['gain','gamma','threshold','residue','size','slice','cutoff'].forEach(id=>$(id+'-value').textContent=id==='slice'?s[id]:(+s[id]).toFixed(id==='cutoff'?3:2));
    const channels = ['full','spectral','residual'].map(name => s.resolution==='fine' ? sample.channels[name] : downsample(sample.channels[name],sample.grid));
    let arrays, support = null;
    if (supportStudy) {
      support = window.GraySupport.calculate(channels[1],sample.reference_white,dims,+s.cutoff,+s.gain,+s.gamma);
      arrays = support.arrays;
      window.GraySupport.summary($('support-summary'),support,dims,+s.cutoff);
    } else {
      const raw = [channels[0], channels[1], Array.from(channels[1],(v,i)=>v+(+s.residue)*channels[2][i])];
      arrays = raw.map(a=>Array.from(a,v=>mapping(v,sample.reference_white,+s.gain,+s.threshold,+s.gamma)));
    }
    const statistics = arrays.map(a=>({cells:a.length, positive:a.filter(v=>v>0).length,
      saturated:a.filter(v=>v>=1).length, mean:a.reduce((x,y)=>x+y,0)/a.length}));
    cards.forEach((card,i)=>{
      slice(card.querySelector('.slice'),arrays[i],dims,axis,+s.slice);
      const t=statistics[i];
      card.querySelector('.stats').innerHTML=`正灰度 <strong>${t.positive} / ${t.cells}</strong>　空格 ${(100*(1-t.positive/t.cells)).toFixed(1)}%<br>`+
        (supportStudy && i===1 ? '白色只表示入选位置，不是最终灰度。' :
        `平均灰度 ${t.mean.toFixed(3)}　饱和 ${(100*t.saturated/t.cells).toFixed(1)}%`+
        (supportStudy&&i===2?`<br>入选格平均灰度 ${t.positive?(t.mean*t.cells/t.positive).toFixed(3):'—'}（未减门槛）`:''));
    });
    scenes?.update(arrays,dims,{size:+s.size,mode:s['render-mode'],slab:s.slab,axis,slice:+s.slice});
    $('source').textContent=`${sample.tensor} · ${sample.quantization} · ${sample.shape.join(' × ')} → ${dims.join(' × ')} 格 · 每格 ${sample.weights_per_cell*(s.resolution==='coarse'?8:1)} 个权重 · 共用参考白值 ${sample.reference_white.toPrecision(5)}`;
    $('runinfo').textContent=JSON.stringify({run,method:manifest.method,tensor:sample.tensor,
      packed_tensor_sha256:sample.packed_tensor_sha256,reference_white:sample.reference_white,
      retained:sample.retained,rank_capped:sample.rank_capped,energy_fraction:sample.retained_energy_fraction,
      convergence:sample.convergence,threshold_sensitivity:sample.threshold_sensitivity,settings:s,
      study:supportStudy?'support':'original',selection:support?{criterion:'spectral/reference_white > cutoff',range:support.range,info:support.info,neighbor:support.neighbor}:null},null,2);
    current={settings:s,dims,statistics,arrays,support};
    const pct=(100*sample.convergence.spectral_pool_relative_l2_change).toFixed(2);
    $('status').textContent=`已加载真实统计。保留 ${sample.retained} 个谱方向；幂迭代加深后的池化变化 ${pct}%。${sample.rank_capped?'注意：达到求解上限，仅为截断结果。':'当前参照下未碰到方向上限，但不是全谱精确解。'} 三维只是观察，不是加工仿真。`;
  }
  function schedule() {
    if (queued) return; queued=true;
    requestAnimationFrame(()=>{queued=false;update();});
  }
  function set(values) {
    Object.entries(values).forEach(([id,value])=>{if(id==='slab')$(id).checked=value;else $(id).value=value;});
    update();
  }
  async function json(path) {
    const response=await fetch(path,{cache:'no-store'});
    if(!response.ok)throw new Error(`${response.status}：${response.url}`);
    return response.json();
  }
  try {
    if(!/^run-\d{8}-\d{6}-\d{6}$/.test(run))throw new Error('运行目录格式无效');
    const base=`data/gray_samples/${run}/`;
    manifest=await json(base+'manifest.json');
    if(manifest.schema!=='snowglass.gray-samples.v1'||manifest.status!=='complete')throw new Error('本次实验尚未完整生成');
    const values=await Promise.all(['attention','mlp'].map(key=>json(base+key+'.json')));
    values.forEach(v=>{
      const n=v.grid.reduce((a,b)=>a*b,1);
      if(!Number.isFinite(v.reference_white)||v.reference_white<=0)throw new Error('灰度参考值无效');
      ['full','spectral','residual'].forEach(name=>{
        if(v.channels[name].length!==n||!v.channels[name].every(x=>Number.isFinite(x)&&x>=0))throw new Error('统计数组无效');
      });
      samples[v.key]=v;
    });
    document.querySelectorAll('[data-original]').forEach(el=>el.hidden=supportStudy);
    document.querySelectorAll('[data-support]').forEach(el=>el.hidden=!supportStudy);
    $('study-switch').href=`?run=${encodeURIComponent(run)}${supportStudy?'':'&study=support'}`;
    $('study-switch').textContent=supportStudy?'返回原三版小样':'打开区域选取对照';
    if(supportStudy){
      document.title='区域选取与连续灰度 · snowglass';
      $('study-title').textContent='先选位置，再显示它的灰度';
      $('study-intro').textContent='同一份真实谱统计：左边看全体，中间只看入选位置，右边保留这些位置原有的连续灰度。';
      $('mode-hint').textContent='区域门槛决定哪些格子留下；曝光与幂次不会改变入选位置。没有扣掉门槛、没有随机删点或平滑补面。默认不透明检查形状，也可切透明叠加。';
      const names=['未筛选谱体','入选位置（诊断）','选区内连续灰度'];
      const descriptions=['同一谱幅度的完整空间分布，不筛位置。','白＝入选，黑＝不显示；只用于看空间形状。','同一批入选格，保留原统计并统一显影，不减门槛。'];
      cards.forEach((card,i)=>{
        card.querySelector('h2').textContent=`0${i+1} / ${names[i]}`;
        card.querySelector('.card-heading p').textContent=descriptions[i];
        card.querySelector('.viewport').setAttribute('aria-label',names[i]+'三维视图');
        card.querySelector('.slice').setAttribute('aria-label',names[i]+'二维切面');
      });
    }
    ids.forEach(id=>$(id).addEventListener('input',schedule));
    set(defaults);
    $('reset').onclick=()=>set(defaults);
    $('reveal').onclick=()=>set({gain:3,gamma:.7,threshold:0});
    $('camera').onclick=()=>scenes?.resetCamera();
    $('export').onclick=()=>{
      const data={schema:supportStudy?'snowglass.gray-support-view.v1':'snowglass.gray-sample-view.v1',run,settings:settings(),source:manifest.source,
        sample_hashes:values.map(v=>({key:v.key,sha256:v.packed_tensor_sha256}))};
      if(supportStudy)data.selection={criterion:'spectral/reference_white > cutoff',dimensions:current.dims,
        indices:current.support.mask.flatMap((v,i)=>v?[i]:[]),gray:current.arrays[2].filter((v,i)=>current.support.mask[i])};
      const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
      a.href=url;a.download=`gray_sample_view_${Date.now()}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    // 暴露只限此页的检查入口，不接触主编辑器工程。
    window.graySampleTest={mapping,downsample,set,supportStudy,get state(){return current;},get views(){return scenes?.views;},samples,manifest};
    update();
    try {scenes=await window.GrayScenes.create(cards.map(c=>c.querySelector('.viewport')));update();}
    catch(error){$('status').textContent=`二维统计已加载；三维不可用：${error.message}`;console.error(error);}
  } catch(error) {
    $('status').textContent=`小样未能加载：${error.message}。本页地址：${location.href}`;
    ids.forEach(id=>$(id).disabled=true);
    document.querySelectorAll('button').forEach(b=>b.disabled=true);
    console.error(error);
  }
})();

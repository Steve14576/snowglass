/* 独立展示控制。复用主模块而不加载app.js；不写localStorage和用户工程。 */
(async() => {
  'use strict';
  const $=id=>document.getElementById(id),IO=RenderLabIO;let source,state,view,busy=true,lastReport=null;
  const message=(text,error=false)=>{$('status').textContent=text;$('status').classList.toggle('lab-error',error);};
  const progress=(done,total,text)=>{
    $('lab-loading').hidden=false;$('loading-text').textContent=text;const bar=$('loading-progress');
    if(total){bar.max=total;bar.value=done;}else bar.removeAttribute('value');message(text);
  };
  function controls(value){busy=value;document.querySelectorAll('button,select,input').forEach(el=>el.disabled=value);}
  function config(){return {ratio:$('ratio-b').value,filter:$('filter-b').value,sceneRatio:$('scene-ratio').value,comparison:$('comparison').value};}
  function evidence(){
    if(!view)return;const e=view.evidence(),split=config().comparison==='layered',a=RenderLabView.ratio('cap125'),b=RenderLabView.ratio(config().ratio);
    const same=split?b===Math.min(b,RenderLabView.ratio(config().sceneRatio)):a===b&&config().filter==='linear';
    $('profile-a').textContent=split?'A · 整场景高清 [1]':'A · 主文件画质 [1]';
    $('profile-b').textContent=split?'B · 雪花适度＋文字高清 [2]':'B · 对照画质 [2]';
    $('scene-ratio-row').hidden=!split;$('ratio-label').textContent=split?'最终画布像素比（A/B共用）':'B像素比';$('filter-label').textContent=split?'文字过滤（A/B共用）':'B文字过滤';
    $('profile-description').textContent=e.profile.toUpperCase()+'档 · '+(e.applied?.pipeline==='layered'?'雪花／结构 '+e.applied.sceneRatio+'，文字 '+e.ratio:'整场景 '+e.ratio)+' · '+RenderLabView.filters[e.applied?.filter||'linear'];
    $('render-summary').textContent=`设备像素比 ${e.deviceRatio} · CSS视口 ${e.css.map(Math.round).join('×')} · 内部画布 ${e.buffer.join('×')} · 抗锯齿 ${e.context.antialias?'开':'关'} · 单个WebGL视口`+(same?(split?' · 两档采样密度相同，分层收益需看短测':' · 两档设置相同；高分辨率比较可选固定1.75'):'')+(e.applied?.warning?' · '+e.applied.warning:'');
    $('render-summary').classList.toggle('lab-warning',same||!!e.applied?.warning);
    $('sample-summary').textContent=`文字 ${e.enabled}/${e.labels} 个启用 · ${e.textureCount} 张共享贴图 · 最长边 ${e.largestTexture}px / 显卡上限 ${e.maxTexture}px`+
      (e.minimumGlyphCssPixels!==null?` · 最小字形投影 ${e.minimumGlyphCssPixels.toFixed(1)} CSSpx`:' · 没有标签：请读取或载入含新版标签的主工程');
    $('sample-summary').classList.toggle('lab-warning',!e.enabled);
    const l=e.layered;
    $('pipeline-summary').textContent=e.applied?.pipeline==='layered'?`单上下文3次绘制 · 雪花／结构缓冲 ${l.sceneBuffer.join('×')} · ${l.samples}×抗锯齿采样 · 最终文字 ${e.buffer.join('×')} · 深度最近邻传递 · 边缘与透明混合有近似差异`:
      `整场景一次绘制 · ${e.buffer.join('×')} · 未抽减雪花`;
    if(l.residentBuffer)$('pipeline-summary').textContent+=` · 预热离屏缓冲占用估算 ${(l.residentBytesEstimate/1048576).toFixed(1)}MB（不含实例／默认画布／驱动）`;
    $('profile-a').classList.toggle('active',e.profile==='a');$('profile-b').classList.toggle('active',e.profile==='b');
    $('profile-a').setAttribute('aria-pressed',String(e.profile==='a'));$('profile-b').setAttribute('aria-pressed',String(e.profile==='b'));
  }
  function selectProfile(profile){if(!view)return;view.apply(profile,config());evidence();}
  function describe(result){
    const total=state.model.topo.blocks.length,matched=result.results.filter(r=>state.data.fresh(r.id,state.model)).length;
    const visible=result.results.filter(r=>state.model.resolve(r.id,'visible').value),count=visible.reduce((sum,r)=>sum+r.count,0);
    const warnings=[...state.warnings,...result.failures],labels=[...state.model.nodes.values()].filter(n=>n.type==='label').length;
    $('source-summary').textContent=`${state.name} · ${state.tasks.length?('已恢复任务 '+state.tasks.join('、')):'没有切片任务引用'} · 已载入 ${result.results.length}/${total} 块 · ${matched} 块匹配当前设置`+
      (warnings.length?' · '+warnings.length+' 项未载入，见状态提示':'');
    $('source-summary').classList.toggle('lab-warning',warnings.length>0||matched<result.results.length||!state.doc);
    $('source-summary').title=warnings.join('\n');
    $('view-caption').textContent=`${count.toLocaleString()} 候选格 · ${view.scene.renderedSnow.toLocaleString()} 实际小块 · ${result.results.length} 块已载入 · ${labels} 个文字标签`+
      (matched<result.results.length?' · 旧约定／网格统计明确保留，不冒充当前设置':'')+' · 未计算块不补模拟';
    return warnings;
  }
  function notice(){
    const el=$('lab-notice');if(state?.doc){el.hidden=true;el.textContent='';return;}
    el.hidden=false;el.textContent='';
    const strong=document.createElement('strong');strong.textContent='当前地址没有读到主工程，因此没有你的文字标签。';
    const span=document.createElement('span');
    span.textContent='雪花来自'+(state?.autoTask?'最近完成的一级切片任务 '+state.autoTask:'主文件内的代表缓存')+'（'+(state?.tasks.length||0)+' 个任务'+(state?.autoNote?'；'+state.autoNote:'')+'）。主页面若在另一个地址打开，点“切换地址读取”；也可载入主页面保存的工程文件。';
    el.append(strong,document.createTextNode(' '),span);
  }
  async function renderState(next,restoreCamera){
    const result=await source.evaluate(next,$('scope').value,progress);
    progress(0,0,'构建与主文件相同的雪花实例；数量不抽减…');await IO.pause();
    state=next;state.results=result.results;
    if(!view){view=new RenderLabView.View($('view'),state,hover);view.scene.orbit.addEventListener('change',()=>{if(!busy)evidence();});
      view.scene.renderer.domElement.addEventListener('webglcontextlost',()=>message('WebGL上下文丢失；停止对照，请保存主工程后关闭此页。',true));
    }else view.attach(state);
    view.draw(result.results);if(restoreCamera)view.restoreCamera();selectProfile(view.profile);
    const warnings=describe(result);lastReport=null;notice();
    $('benchmark-summary').textContent='短测需点击执行；仅比较同场景实际绘制完成耗时，不推断完整编辑器帧率。';
    message(warnings.length?'载入完成但有缺项：'+warnings.slice(0,3).join('；'):'只读展示已就绪。1／2切换画质；主工程和原统计均未修改。');
  }
  async function load(doc,name){
    if(busy)return;controls(true);
    try{const next=await source.open(doc,name,progress);await renderState(next,true);}
    catch(e){message('工程未载入，保留当前展示：'+e.message,true);}
    finally{$('lab-loading').hidden=true;controls(false);evidence();}
  }
  function hover(id,event){
    const box=$('hover-card');if(!id||busy){box.hidden=true;return;}const n=state.model.nodes.get(id),rect=$('view').getBoundingClientRect();
    box.textContent=n.type==='label'?n.data.text+'\n来源：'+n.data.members.join('、'):n.name+' · '+n.id;
    box.style.left=Math.max(8,Math.min(event.clientX-rect.left+14,rect.width-320))+'px';box.style.top=Math.max(8,event.clientY-rect.top+14)+'px';box.hidden=false;
  }
  function preset(){
    const mode=$('comparison').value;if(mode!=='custom'){
      $('ratio-b').value=mode==='layered'?'cap2':mode==='filter'?'cap125':'cap175';$('filter-b').value=['layered','resolution'].includes(mode)?'linear':'anisotropic';
      if(mode==='layered')$('scene-ratio').value='cap125';
    }
    lastReport=null;$('benchmark-summary').textContent='比较项目已改变，需要重新短测。';if(!busy)selectProfile(view.profile);
  }
  function bind(){
    $('profile-a').onclick=()=>selectProfile('a');$('profile-b').onclick=()=>selectProfile('b');$('comparison').onchange=preset;
    for(const id of ['ratio-b','filter-b','scene-ratio'])$(id).onchange=()=>{if($('comparison').value!=='layered')$('comparison').value='custom';lastReport=null;selectProfile(view.profile);$('benchmark-summary').textContent='画质设置已改变，先前短测不再用于当前对照。';};
    $('read-project').onclick=()=>{
      try{const saved=IO.stored();if(!saved){message('这个地址下没有主工程自动保存。请点“切换地址读取”，或载入主页面保存的工程文件；此页不自动生成标签。',true);return;}load(saved.doc,saved.name);}
      catch(e){message('主工程自动保存读取失败：'+e.message,true);}
    };
    $('switch-host').onclick=()=>{const url=new URL(location.href);url.hostname=location.hostname==='localhost'?'127.0.0.1':'localhost';location.href=url.toString();};
    $('project-file').onchange=async event=>{
      const file=event.target.files[0];if(!file)return;
      try{if(file.size>24*1024*1024)throw Error('工程文件超过24MB；请使用工程JSON，而不是大型灰度映射文件');await load(JSON.parse(await file.text()),'工程文件：'+file.name);}
      catch(e){message('文件未载入：'+e.message,true);}finally{event.target.value='';}
    };
    $('source-camera').onclick=()=>{view.restoreCamera();evidence();};$('front').onclick=()=>{view.scene.fit(['work'],true);evidence();};$('fit').onclick=()=>{view.scene.fit(['work']);evidence();};
    $('scope').onchange=async()=>{
      controls(true);try{await renderState(state,false);}catch(e){message('范围载入失败：'+e.message,true);}finally{$('lab-loading').hidden=true;controls(false);evidence();}
    };
    $('benchmark').onclick=async()=>{
      if(view.scene.renderedSnow>100000&&!confirm('将测同一场景的A/B各5次绘制，含GPU完成等待。全量雪花可能需要数十秒；不会改主工程或重切权重。现在开始？'))return;
      controls(true);
      try{lastReport=await view.benchmark(config(),progress);const {a,b}=lastReport.profiles;
        $('benchmark-summary').textContent=`同场景5次中位数：A ${a.median.toFixed(2)}ms（${a.pipeline==='layered'?'分层':'整场'}），B ${b.median.toFixed(2)}ms（${b.pipeline==='layered'?'分层':'整场'}） · 绘制＋GPU完成等待 · 不含实例构建／权重计算，不是完整编辑器FPS`;message('短测完成，取景、文字、灰度与实例数量保持。');
      }catch(e){message('短测停止：'+e.message,true);}finally{$('lab-loading').hidden=true;controls(false);evidence();}
    };
    document.addEventListener('keydown',event=>{if(busy||event.ctrlKey||event.metaKey||event.altKey||event.target instanceof Element&&event.target.closest('input,select,textarea,button'))return;if(event.key==='1'||event.key==='2'){event.preventDefault();selectProfile(event.key==='1'?'a':'b');}});
    new ResizeObserver(()=>{if(!busy)evidence();}).observe($('view'));
  }
  try{
    controls(true);if(location.protocol==='file:')throw Error('请经本机服务打开 http://127.0.0.1:8128/render_lab/，不能双击文件。');
    const query=new URLSearchParams(location.search),wanted=query.get('scope');if(['all','selected','none'].includes(wanted))$('scope').value=wanted;
    const comparison=query.get('comparison');if(['layered','resolution','filter','combined','custom'].includes(comparison))$('comparison').value=comparison;
    preset();
    const [topo,manifest,provenance]=await Promise.all([IO.json('data/topology.json'),IO.json('data/manifest.json'),IO.json('provenance.json')]);
    await IO.libraries(message);source=new IO.Source(topo,manifest,provenance);let initial=null;
    try{initial=IO.stored();}catch(e){message('自动保存无效，先展示原缓存：'+e.message,true);}
    let next,restoreWarning='';
    try{next=await source.open(initial?.doc||null,initial?.name||'未读取到主工程（雪花取自最近完成的一级切片任务）',progress);}
    catch(e){restoreWarning='主工程未恢复：'+e.message+'；请载入兼容工程文件。';next=await source.open(null,'主工程不兼容；仅展示原有代表缓存',progress);}
    await renderState(next,true);bind();if(restoreWarning)message(restoreWarning,true);
    window.renderLab={source,get state(){return state;},get view(){return view;},get busy(){return busy;},get lastReport(){return lastReport;},load,selectProfile,evidence:()=>view.evidence()};
  }catch(e){message('展示页初始化失败：'+e.message,true);$('source-summary').textContent='未完成载入；没有生成任何替代数据。';}
  finally{$('lab-loading').hidden=true;controls(!view);evidence();}
})();

/* 独立UX启动与联动。旧工程键、旧缓存和服务不修改。 */
(async()=>{
  'use strict';
  const $=id=>document.getElementById(id),storageKey='snowglass.editor-ux.20261122-055413-124110.v3-zup',legacyStorageKey='snowglass.editor-ux.20261122-055413-124110.v2';
  const kindName={global:'全局配置',root:'模型根',tower:'塔',layer:'层',group:'操作组',block:'权重功能块',ghost:'幽灵毛坯',reference:'参照集合',project:'工程',annotationRoot:'标注',labelGroup:'标签组',label:'独立标签'};
  const message=text=>$('status').textContent=text;
  function bootFail(title,body,hint,cmd){
    const box=$('boot-error');if(!box)return;
    $('boot-title').textContent=title;$('boot-body').textContent=body;$('boot-hint').textContent=hint;
    const pre=$('boot-cmd');pre.textContent=cmd||'';pre.hidden=!cmd;
    box.hidden=false;document.body.classList.add('boot-failed');
  }
  // 文件协议下浏览器不会让页面 fetch 同目录数据，提前拦下而不是伪装成“统计缺失”。
  if(location.protocol==='file:'){
    message('未启动：当前以文件方式打开，无法读取统计。');
    bootFail('这个页面要用本地服务打开，不能双击文件',
      '当前地址是 file:// 开头。浏览器把同目录的拓扑和 124 份张量统计当成跨源请求拦掉，所以你看到空白和一串 403。数据文件都在，代码也没坏。',
      '换成下面这条本机地址即可；服务没开时先在项目根执行框里的命令。',
      'http://127.0.0.1:8128/\n\nuv run --offline --script scripts/serve_editor.py');
    return;
  }
  async function json(path){const r=await fetch(path,{cache:'no-store'});if(!r.ok)throw Error(path+' HTTP '+r.status);return r.json();}
  async function libraries(){
    for(const path of ['build/three.min.js','examples/js/controls/OrbitControls.js','examples/js/controls/TransformControls.js']){
      let loaded=false;for(const base of ['https://cdn.jsdelivr.net/npm/three@0.128.0/','https://unpkg.com/three@0.128.0/']){
        try{message('加载三维依赖：'+path);await new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=base+path;
                    const timer=setTimeout(()=>{s.remove();reject(Error('三维依赖加载超时'));},10000);
                    s.onload=()=>{clearTimeout(timer);resolve();};s.onerror=()=>{clearTimeout(timer);s.remove();reject(Error('三维依赖请求失败'));};document.head.append(s);
                  });loaded=true;break;}catch(e){/* 只重试本项备用CDN，不让整页无限等待。 */}
      }if(!loaded)throw Error('三维依赖不可用：'+path);
    }
  }
  function download(doc,name){const u=URL.createObjectURL(new Blob([JSON.stringify(doc,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
  function stamp(){return new Date().toISOString().replace(/[-:.]/g,'');}
  function confirmAction(title,text){const d=$('confirm-dialog');$('confirm-title').textContent=title;$('confirm-body').textContent=text;d.returnValue='';return new Promise(resolve=>{d.addEventListener('close',()=>resolve(d.returnValue==='ok'),{once:true});d.showModal();});}
  try{
    const [topo,manifest,provenance]=await Promise.all([json('data/topology.json'),json('data/manifest.json'),json('provenance.json')]);await libraries();
    const model=new UXModel.Model(topo,provenance),data=new UXData.Data(manifest);let selected=['L16.down'],preview=['L16.down'],results=[],serial=0,saveTimer,inspector,tree,scene,dataTimer=null,structPending=false,viewMode='prepare',previewLoading=false,previewResults=[],slicing=null,bootDoc=null;
    const previewLoad={loading:false,done:0,total:0,budget:false,failures:[]};
    const observed=()=>selected.length===1&&selected[0]==='global'?preview:selected;
    const snapshot=()=>({...model.snapshot(),slice:slicing?.snapshot(),view:{selected:selected.slice(),preview:preview.slice(),isolate:scene.isolate,exposure:scene.exposure,camera:scene.camera.position.toArray(),target:scene.orbit.target.toArray(),open:[...tree.open]}});
    const safe=fn=>{try{return fn();}catch(e){message(e.message);}};
    async function refreshData(){
      const token=++serial,isPreview=viewMode==='preview',current=()=>token===serial&&isPreview===(viewMode==='preview');
      const sourceIds=isPreview?[...data.groups.keys()]:model.leaves(observed());
      const priority=new Set(model.leaves(observed())),distances=new Map(sourceIds.filter(id=>model.nodes.get(id)?.type==='block').map(id=>[id,model.bounds([id]).getCenter(new THREE.Vector3()).distanceToSquared(scene.camera.position)]));
      const ordered=[...distances.keys()].sort((a,b)=>Number(priority.has(b))-Number(priority.has(a))||distances.get(a)-distances.get(b)),ids=isPreview?ordered:ordered.slice(0,8);
      const loaded=[],queue=ids.slice();let cells=0;
      if(isPreview){Object.assign(previewLoad,{loading:true,done:0,total:ids.length,budget:false,failures:[]});scene.progressive.begin(ids);renderViewState();}
      try{
        await Promise.all(Array.from({length:Math.min(3,ids.length)},async()=>{
          while(queue.length&&current()&&(!isPreview||!previewLoad.budget)){
            if(isPreview&&!await scene.progressive.waitActive(current))break;const id=queue.shift();if(!id)break;
            try{
              const result=await data.evaluate(id,model,{isCurrent:current});if(!current())return;
              if(isPreview&&cells+result.count>scene.progressive.status().limits.loadedCells){previewLoad.budget=true;break;}
              cells+=result.count;loaded.push(result);
              if(isPreview){results=loaded.slice();previewResults=results;scene.progressive.offer(result);previewLoad.done=loaded.length;renderViewState();}
            }catch(e){if(e.name==='AbortError')return;if(!isPreview)throw e;previewLoad.failures.push(id+'：'+e.message);}
          }
        }));
        if(!current())return;results=loaded;previewResults=isPreview?loaded:[];
        if(isPreview){previewLoad.loading=false;scene.progressive.finish();}else scene.drawSnow([]);
        const chosen=new Set(model.leaves(observed()));inspector.results(results.filter(r=>chosen.has(r.id)));renderViewState();slicing?.render();renderReport();
        const coverage=slicing?.summary(),count=results.reduce((n,r)=>n+r.count,0);
        $('view-caption').textContent=`${isPreview?'预览：真实缓存，分批绘制。':'准备：不显示雪花。'}${results.length} 个功能块 · ${count} 候选格 · ${coverage?coverage.total-coverage.ready:0} 块待切片；旧统计不匹配会标明，不填模拟。`;
        if(previewLoad.failures.length)message('部分统计未载入：'+previewLoad.failures.slice(0,2).join('；'));
      }catch(e){if(current()){previewLoad.loading=false;if(isPreview)scene.progressive.finish();message(e.message+'；没有重新计算权重。');}}
    }
    function renderReport(){
      if($('report').hidden)return;const report=UXChecks.run(model),root=$('report');root.textContent='';
      const heading=document.createElement('h3');heading.textContent='后验报告 · 只提示，不阻挠';root.append(heading);
      const line=(text,tone)=>{const p=document.createElement('p');p.textContent=text;if(tone)p.className=tone;root.append(p);};
      const size=model.bounds(['work']).getSize(new THREE.Vector3());line('模型世界包围盒：'+size.toArray().map(v=>v.toFixed(3)).join(' × ')+' mm');
      line('进入作品功能块：'+report.solids+'；仿射盒重叠：'+report.overlaps.length+' 对',report.overlaps.length?'danger':null);
      for(const g of report.ghosts)line(g.name+(g.primary?'（主参照）':'')+'：'+g.outside.length+'块出界'+(g.invalid?'，内预留区域为空':'')+(g.approx?'，圆柱内偏移保守近似':''),g.outside.length?'danger':g.invalid?'warn':null);
      for(const r of results.slice(0,8)){if(!r.pieces.length)continue;const m=model.world(r.id),side=model.resolve(r.id,'snowSize').value;
        const spacing=r.pieces.flatMap(p=>p.grid.map((n,i)=>new THREE.Vector3().setFromMatrixColumn(m,i).length()*p.region.size[i]/n)),tight=Math.min(...spacing)<side;
        line(r.id+'：'+r.count+'候选格，'+r.positive+'正灰度格，'+r.masked+'显式筛除；轴向最小间距 '+Math.min(...spacing).toFixed(5)+' mm'+(tight?'，小于雪花边长，存在干涉风险':''),tight?'warn':null);
      }
      if(results.length>8)line(`其余 ${results.length-8} 块只在预览中绘制，不逐块列出。`);
      model.layoutWarnings.forEach(text=>line(text,'warn'));line('轴向间距不是全部跨块近邻检查。没有厂家灰阶标定，不据点距宣称可加工；爆点数、工时、灰度容量未核实。','warn');
    }
    function refresh(transient=false){
      selected=selected.filter(id=>model.nodes.has(id));preview=preview.filter(id=>model.nodes.has(id));scene.observation=observed();scene.select(selected);renderIdentity();
      if(transient){
        inspector.updateTransform();inspector.curveUI?.redraw();
        if(!structPending){structPending=true;requestAnimationFrame(()=>{structPending=false;scene.structure();scene.render();});}
        clearTimeout(dataTimer);dataTimer=setTimeout(()=>refreshData(),viewMode==='preview'?260:50);
        return;
      }
      {const curveState=inspector.curveUI?{index:inspector.curveUI.index,handles:inspector.curveUI.handles}:null;inspector.ids=selected;inspector.render();if(curveState&&inspector.curveUI){Object.assign(inspector.curveUI,curveState);inspector.curveUI.redraw();}tree.selected=selected;tree.render();
        clearTimeout(saveTimer);saveTimer=setTimeout(()=>{try{localStorage.setItem(storageKey,JSON.stringify(snapshot()));}catch(e){message('自动保存失败，请保存工程文件');}},400);}
      scene.structure();refreshData();renderReport();$('undo').disabled=!model.history.length;$('redo').disabled=!model.future.length;
    }
    const previewIds=()=>[...data.groups.keys()].filter(id=>model.nodes.get(id)?.type==='block');
    function renderViewState(){
      $('view-prepare').setAttribute('aria-selected',String(viewMode==='prepare'));
      $('view-preview').setAttribute('aria-selected',String(viewMode==='preview'));
      const badge=$('preview-state');
      if(viewMode==='preview'&&previewResults.length){badge.hidden=false;badge.textContent=`${previewResults.length} 块 · ${previewResults.reduce((n,r)=>n+r.count,0)} 候选格`;}
      else badge.hidden=true;
      const state=scene?.progressive?.status();$('preview-render').hidden=viewMode!=='preview';
      if(state&&viewMode==='preview'){
        const phase=state.mode==='overview'?'始终轻量':previewLoad.budget||state.budget?'显示资源上限'
          :state.interacting?(state.mode==='always'?'转动中仍画完整':'拖动概览'):state.settled?'细节已完成':'正在分批细化';
        $('preview-render-text').textContent=phase+' · 统计 '+previewLoad.done+'/'+previewLoad.total+' 块 · 细节 '+state.ready+'/'+state.pieces+' 分区';
        $('preview-render').title=previewLoad.budget?'当前显示工作集达到上限；其余统计仍保存在磁盘。选择焦点后重新进入预览可优先载入。':'概览来自真实格子，粒度只影响显示；统计结果和加工输出不变。';
        $('preview-detail').value=state.mode;
      }
      slicing?.render();
    }
    function showProgress(done,total,text){$('progress').hidden=false;$('progress-text').textContent=text;$('progress-fill').style.width=(total?Math.round(done/total*100):0)+'%';}
    function hideProgress(){$('progress').hidden=true;}
    async function enterPreview(){
      viewMode='preview';previewLoading=true;scene.isolate=false;$('isolate-view').classList.remove('active');$('isolate-view').setAttribute('aria-checked','false');
      scene.observation=previewIds();scene.structure();hideProgress();renderViewState();
      message('预览已进入；读取现成统计并分批显示，仍可转动、暂停或返回准备。');
      try{await refreshData();}finally{previewLoading=false;}
    }
    function exitPreview(){
      ++serial;viewMode='prepare';previewLoading=false;previewLoad.loading=false;previewResults=[];scene.progressive.clear();hideProgress();renderViewState();
      data.prune(model.leaves(observed()));message('准备：结构编辑；切片结果保留，不显示雪花。');refreshData();
    }
    async function setView(mode){
      if(mode==='prepare'){if(viewMode!=='prepare')exitPreview();return;}
      if(viewMode!=='preview')await enterPreview();
    }
    function renderIdentity(){
      const el=$('identity');el.textContent='';
      if(!selected.length){el.hidden=true;return;}
      el.hidden=false;const row=text=>{const p=document.createElement('p');p.className='id-row';p.textContent=text;el.append(p);};
      const h=document.createElement('h3');
      if(selected.length>1){
        h.textContent=`已选 ${selected.length} 个对象`;el.append(h);
        row(selected.slice(0,8).join('、')+(selected.length>8?' …':''));return;
      }
      const n=model.nodes.get(selected[0]);h.textContent=n.name+' · '+n.id;el.append(h);
      const kind=document.createElement('p');kind.className='id-kind';kind.textContent=kindName[n.type]||n.type;el.append(kind);
      if(UXAnnotationState.is(n)){UXAnnotationUI.identity(model,n).forEach(row);}
      else if(n.type==='block'){
        const src=topo.blocks.find(b=>b.id===n.sourceId)||(topo.geometry_only||[]).find(b=>b.id===n.sourceId);
        if(src){
          row(`源层 ${src.layer!=null?'L'+src.layer:src.vlayer!=null?'V'+src.vlayer:'—'} · 槽位 ${src.slot||'—'} · ${(src.tensors||[]).length} 个张量`);
          for(const t of src.tensors||[]){
            const box=document.createElement('div');box.className='id-tensor';
            box.textContent=`${t.gguf}\n${t.shape.join('×')} · ${t.qtype||'—'}${t.restore?' · 可选HF对齐规则：'+t.restore:''}`;el.append(box);
          }
        }else row('没有源张量（空框或权重未收录）');
        const real=data.groups.has(n.sourceId),fresh=slicing?.fresh(n.sourceId)??real,st=document.createElement('p');
        st.className='id-state'+(fresh?'':' muted');st.textContent=fresh?'统计状态：已有匹配真实缓存':real?'统计状态：来源／约定／网格待生成；当前保留旧结果':'统计状态：未计算／权重未收录';el.append(st);
        const size=model.bounds([n.id]).getSize(new THREE.Vector3());
        row('包络 '+size.toArray().map(v=>v.toFixed(3)).join(' × ')+' mm');
        row('当前选定约定：'+(model.resolve(n.id,'sourceConvention').value==='gguf'?'GGUF文件原值':'HF数值约定')+'；额外诊断 '+(model.resolve(n.id,'extraDiagnostics').value?'启用':'关闭'));
      }else if(n.type==='ghost'){
        const d=n.data;row(`形状 ${d.shape==='box'?'长方体':'圆柱'} · 向内预留 ${d.margin} mm${model.primaryGhost===n.id?' · 主参照':''}`);
      }else if(n.type==='group'){
        row(`操作组 · 成员 ${model.descendants(n.id).length} 个节点 · 覆盖 ${Object.keys(n.overrides).length} 项`);
      }else if(n.type==='global'){
        row('全局配置对象 · 没有空间变换');
      }else if(n.type==='layer'||n.type==='tower'){
        row(`包含 ${model.descendants(n.id).length} 个节点`);
      }
    }
    function select(ids,mode='replace'){
      ids=ids.filter(id=>model.nodes.has(id));
      if(mode==='toggle'){const set=new Set(selected);ids.forEach(id=>set.has(id)?set.delete(id):set.add(id));selected=[...set];if(ids.length)tree.anchor=ids[ids.length-1];}
      else if(mode==='range'){const last=ids[ids.length-1],scope=tree.rangeTo(last);selected=scope.filter(id=>model.nodes.has(id));tree.anchor=tree.anchor||last;}
      else{selected=ids;tree.anchor=ids[ids.length-1]||null;}
      renderIdentity();
      if(selected.length===1&&selected[0]==='global'){
        if(!model.leaves(preview).some(id=>model.nodes.get(id).type==='block'))preview=[...model.nodes.values()].filter(n=>n.type==='block'&&data.groups.has(n.id)).slice(0,1).map(n=>n.id);
      }else preview=selected.slice();
      tree.selection(selected);inspector.selection(selected);scene.observation=observed();scene.select(selected);scene.structure();refreshData();renderReport();
    }
    async function reparent(ids,parent){
      try{ids=model.roots(ids);const changes=ids.flatMap(id=>model.changes(id,parent).map(k=>model.nodes.get(id).name+'：'+k+' 将按新上级继承'));
        if(changes.length&&!await confirmAction('迁组会改变继承值',changes.join('\n')))return;
        model.commit(()=>ids.forEach(id=>model.move(id,parent)),true);select(ids);message('已迁组：保持世界变换，未覆盖项继承新上级');
      }catch(e){message(e.message);}
    }
    function hover(id,event){const card=$('hover-card');if(!id){card.hidden=true;return;}const n=model.nodes.get(id),source=topo.blocks.find(b=>b.id===n.sourceId);card.textContent=n.name+' · '+n.id+'\n'+(source?.tensors||[]).map(t=>t.gguf+' '+t.shape.join('×')).join('\n');
      const r=$('view').getBoundingClientRect();card.style.left=Math.max(8,Math.min(event.clientX-r.left+15,r.width-370))+'px';card.style.top=Math.max(8,Math.min(event.clientY-r.top+15,r.height-100))+'px';card.hidden=false;}
    tree=new UXTree(model,data,select,reparent);inspector=new UXInspector(model,message,{select:ids=>{tree.reveal=true;select(ids);},confirm:confirmAction,message,saveAnnotations});
    scene=new UXScene($('view'),model,(ids,mode)=>{tree.reveal=true;select(ids,mode);},hover,()=>inspector.updateTransform());
    scene.renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));scene.pixelLayers=new UXPixelLayers(scene);scene.progressive=new UXProgressiveSnow(scene,()=>renderViewState());scene.resize();
    $('preview-detail').onchange=()=>{scene.progressive.setMode($('preview-detail').value);renderViewState();};
    window.addEventListener('pagehide',()=>{scene.pixelLayers.dispose();data.reader?.close();},{once:true});model.listeners.push(refresh);
    async function group(){try{const ids=model.roots(selected),parents=ids.map(id=>model.ancestors(id));if(!ids.length)throw Error('先多选或框选对象');
      const parent=parents[0].find(p=>parents.every(a=>a.includes(p))),changes=ids.flatMap(id=>model.changes(id,parent));
      if(changes.length&&!await confirmAction('打组将改变部分继承参数','成员移动到共同上级下的新组，以下参数的继承来源将变化：\n'+[...new Set(changes)].join('、')+'\n世界变换保留；不会复制整套参数。'))return;
      const id=model.group(ids);select([id]);tree.open.add(id);tree.render();message('新组无局部覆盖；只改动／固定的项才覆盖');}catch(e){message(e.message);}}
    async function ungroup(keep){const id=selected.length===1?selected[0]:null,g=model.nodes.get(id);if(!['group','labelGroup'].includes(g?.type)){message('先选一个操作组或标签组');return;}
      const children=model.children(id).map(n=>n.id),keys=Object.keys(g.overrides);
      if(keys.length&&!await confirmAction(keep?'解组并保留组局部设置':'解组后继续继承',keep?'仅将组实际覆盖的适用项下放为成员本地值，不盖过成员已有覆盖：\n'+keys.join('、'):'组的这些局部覆盖随组撤销，成员未覆盖项改为继承上级：\n'+keys.join('、')))return;
      safe(()=>model.ungroup(id,keep));select(children);message(keep?'已解组，明确保留了相关局部覆盖':'已解组，未覆盖项继续继承');}
    $('group').onclick=group;$('ungroup').onclick=()=>ungroup(false);$('ungroup-keep').onclick=()=>ungroup(true);
    $('remove').onclick=async()=>{const ids=model.roots(selected);if(!ids.length)return;if(await confirmAction('从当前工程删除所选及其内容',ids.map(id=>model.nodes.get(id).name).join('\n')+'\n可撤销；不删除权重或缓存。删除源块会解除相关标注跟随，并保留最后位置。'))safe(()=>{model.removeMany(ids);select([]);});};
    $('new-box').onclick=()=>safe(()=>select([model.newGhost('box')]));$('new-cylinder').onclick=()=>safe(()=>select([model.newGhost('cylinder')]));
    $('undo').onclick=()=>safe(()=>model.undo());$('redo').onclick=()=>safe(()=>model.redo());
    $('select-all').onclick=()=>select([...model.nodes.values()].filter(n=>n.type==='block').map(n=>n.id));$('select-none').onclick=()=>select([]);
    $('select-layer').onclick=()=>select(topo.blocks.filter(b=>b.layer===+$('layer-number').value&&!b.id.startsWith('V')&&model.nodes.has(b.id)).map(b=>b.id));
    $('select-column').onclick=()=>select(topo.blocks.filter(b=>model.nodes.has(b.id)&&($('slot').value==='vision'?b.id.startsWith('V'):!b.id.startsWith('V')&&b.slot===$('slot').value)).map(b=>b.id));
    const mode=value=>{scene.setMode(value);document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===value));};document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>mode(b.dataset.mode));
    const boxButton=$('box-select'),syncBox=()=>{boxButton.classList.toggle('active',scene.boxMode);boxButton.setAttribute('aria-pressed',String(scene.boxMode));};
    boxButton.onclick=()=>{scene.boxMode=!scene.boxMode;syncBox();};
    $('view-prepare').onclick=()=>setView('prepare');
    $('view-preview').onclick=()=>setView('preview');
    // 视图菜单与两个弹层：同一时间只开一个，点外部或 Esc 关闭。
    const pops=['view-menu-list','observe-pop','keys-pop'],popButtons=['view-menu-button','observe-button','keys-button'];
    const closePop=()=>{pops.forEach(id=>{const el=$(id);if(el)el.hidden=true;});popButtons.forEach(id=>$(id).setAttribute('aria-expanded','false'));};
    const togglePop=(button,pop)=>{const open=!$(pop).hidden;closePop();if(!open){$(pop).hidden=false;$(button).setAttribute('aria-expanded','true');}};
    $('view-menu-button').onclick=e=>{e.stopPropagation();togglePop('view-menu-button','view-menu-list');};
    $('observe-button').onclick=e=>{e.stopPropagation();togglePop('observe-button','observe-pop');};
    $('keys-button').onclick=e=>{e.stopPropagation();togglePop('keys-button','keys-pop');};
    document.addEventListener('pointerdown',e=>{if(!e.target.closest('.view-tools'))closePop();});
    const isolation=value=>{scene.isolate=value;const b=$('isolate-view');b.classList.toggle('active',value);b.setAttribute('aria-checked',String(value));scene.structure();scene.render();refreshData();};
    $('isolate-view').onclick=()=>{isolation(!scene.isolate);closePop();};
    $('fit-all').onclick=()=>{isolation(false);scene.fit(['work']);closePop();};
    $('fit-selected').onclick=()=>{scene.fit(observed());closePop();};
    $('front-view').onclick=()=>{scene.fit(observed().length?observed():['work'],true);closePop();};
    $('exposure').oninput=()=>{scene.exposure=+$('exposure').value;$('exposure-out').textContent=scene.exposure.toFixed(2);refreshData();};
    $('report-toggle').onclick=()=>{$('report').hidden=!$('report').hidden;renderReport();};$('focus-toggle').onclick=()=>{document.body.classList.toggle('focus');scene.resize();};
    $('save-project').onclick=()=>download(snapshot(),'snowglass_ux_'+stamp()+'.json');$('open-project').onclick=()=>$('project-file').click();
    // 工程里保存的是当时的观察方向与距离；焦点一律归到世界原点，避免旧工程带着偏高的中心把模型推出画面。
    function restoreCamera(doc){
      const camera=doc.view?.camera,target=doc.view?.target;if(!Array.isArray(camera)||camera.length!==3||!Array.isArray(target))return;
      const savedTarget=new THREE.Vector3().fromArray(target);if(![...camera,...target].every(Number.isFinite))return;
      scene.orbit.target.set(0,0,0);scene.camera.position.fromArray(camera).sub(savedTarget);scene.orbit.update();scene.render();
    }
    $('project-file').onchange=async()=>{try{const doc=UXCoordinates.prepare(JSON.parse(await $('project-file').files[0].text()));model.load(doc);restoreCamera(doc);
        if(Array.isArray(doc.view?.open))tree.open=new Set(doc.view.open);preview=(doc.view?.preview||['L16.down']).filter(id=>model.nodes.has(id));scene.isolate=doc.view?.isolate??false;scene.exposure=doc.view?.exposure??1;$('exposure').value=scene.exposure;$('exposure-out').textContent=scene.exposure.toFixed(2);$('isolate-view').classList.toggle('active',scene.isolate);$('isolate-view').setAttribute('aria-checked',String(scene.isolate));
        await slicing.restore(doc);select((doc.view?.selected||['work']).filter(id=>model.nodes.has(id)));message('新版工程已恢复，继承关系、覆盖与切片引用保留');}catch(e){message('打开失败：'+e.message);}finally{$('project-file').value='';}};
    function saveAnnotations(ids){try{const frozen=new UXModel.Model(topo,provenance);frozen.restore(model.snapshot());const annotations=frozen.annotations(ids);if(!annotations.length)throw Error('所选范围没有独立标注');download({kind:'snowglass.annotations.v1',coordinateSystem:UXCoordinates.SYSTEM,localGeometryBasis:'glyph-xy-plane',created_at:new Date().toISOString(),annotations,project:frozen.snapshot(),glyph_geometry:'未接入厂家可加工轮廓；这里只保存固定文字定义'},'annotations_'+stamp()+'.json');message('独立标注定义已保存，未生成厂家加工字形');}catch(e){message(e.message);}}
    $('save-mapping').onclick=async()=>{if(!selected.length){message('先选择有真实统计或标注的对象');return;}const button=$('save-mapping');button.disabled=true;
      try{const frozen=new UXModel.Model(topo,provenance);frozen.restore(model.snapshot());const scope=selected.length===1&&selected[0]==='global'?['work']:selected.slice();const doc=await data.mapping(scope,frozen);if(!doc.results.some(r=>r.pieces.length)&&!doc.annotations.length)throw Error('所选范围没有真实统计或标注，不输出空白冒充成功');doc.project=frozen.snapshot();download(doc,'gray_mapping_'+stamp()+'.json');message('灰度映射已保存为新文件；未生成厂家加工文件');}
      catch(e){message(e.message);}finally{button.disabled=false;refreshData();}};
    // 侧栏宽度与树／属性高度：各拖各的，不互相挤掉。
    const root=document.documentElement,resizer=$('sidebar-resizer'),treeSplit=$('tree-splitter');
    const clamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
    const dragResize=(handle,onMove,axis)=>{
      handle.addEventListener('pointerdown',e=>{e.preventDefault();handle.setPointerCapture(e.pointerId);handle.dataset.drag='1';handle.dataset.start=String(axis==='x'?e.clientX:e.clientY);
        handle.dataset.base=axis==='x'?String(parseFloat(getComputedStyle(root).getPropertyValue('--sidebar-width'))||380):String(document.querySelector('.tree-panel').clientHeight);});
      handle.addEventListener('pointermove',e=>{if(handle.dataset.drag!=='1')return;onMove(Number(handle.dataset.base),axis==='x'?e.clientX:e.clientY,Number(handle.dataset.start));});
      const stop=()=>{handle.dataset.drag='0';};handle.addEventListener('pointerup',stop);handle.addEventListener('pointercancel',stop);
      handle.addEventListener('keydown',e=>{const sign=e.key==='ArrowRight'||e.key==='ArrowDown'?1:e.key==='ArrowLeft'||e.key==='ArrowUp'?-1:0;if(!sign)return;e.preventDefault();
        if(axis==='x'){const base=parseFloat(getComputedStyle(root).getPropertyValue('--sidebar-width'))||380;root.style.setProperty('--sidebar-width',clamp(base+sign*20,200,innerWidth-300)+'px');}
        else{const base=document.querySelector('.tree-panel').clientHeight;root.style.setProperty('--tree-height',clamp(base+sign*20,120,$('sidebar').clientHeight-180)+'px');}
        scene.resize();});
    };
    dragResize(resizer,(base,now,start)=>{
      root.style.setProperty('--sidebar-width',clamp(base+(now-start),200,innerWidth-300)+'px');scene.resize();
    },'x');
    dragResize(treeSplit,(base,now,start)=>{
      root.style.setProperty('--tree-height',clamp(base+(now-start),120,$('sidebar').clientHeight-180)+'px');
    },'y');
    document.addEventListener('keydown',e=>{
      const typing=!!(e.target instanceof Element&&e.target.closest('input,select,textarea'));
      if($('confirm-dialog').open)return;
      const key=e.key.toLowerCase();
      if(e.ctrlKey&&key==='z'){e.preventDefault();e.shiftKey?model.redo():model.undo();return;}
      if(e.ctrlKey&&key==='y'){e.preventDefault();model.redo();return;}
      if(e.ctrlKey&&key==='g'){e.preventDefault();group();return;}
      if(key==='escape'){closePop();return;}
      if(typing)return;
      if(e.ctrlKey&&key==='a'){e.preventDefault();select([...model.nodes.values()].filter(n=>n.type==='block').map(n=>n.id));return;}
      if(!e.ctrlKey&&!e.altKey){
        if({w:'translate',e:'rotate',r:'scale',q:'off'}[key])mode({w:'translate',e:'rotate',r:'scale',q:'off'}[key]);
        if(key==='b')boxButton.click();
        if(key==='f')$('focus-toggle').click();
        if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();$('remove').click();}
      }
    });
    try{const stored=localStorage.getItem(storageKey)||localStorage.getItem(legacyStorageKey);if(stored){const doc=UXCoordinates.prepare(JSON.parse(stored));bootDoc=doc;model.validate(doc);model.restore(doc);selected=(doc.view?.selected||selected).filter(id=>model.nodes.has(id));preview=(doc.view?.preview||preview).filter(id=>model.nodes.has(id));scene.isolate=doc.view?.isolate??false;scene.exposure=doc.view?.exposure??1;$('exposure').value=scene.exposure;$('exposure-out').textContent=scene.exposure.toFixed(2);const iso=$('isolate-view');iso.classList.toggle('active',scene.isolate);iso.setAttribute('aria-checked',String(scene.isolate));}}catch(e){message('自动保存不兼容，保留文件并用新工程启动：'+e.message);}
    slicing=new UXSlicing(model,data,{selected:()=>selected,view:()=>viewMode,message,confirm:confirmAction,progress:showProgress,hideProgress,
      dataChanged:async(autoPreview)=>{++serial;scene.progressive.clear();inspector.render();tree.render();renderIdentity();
        clearTimeout(saveTimer);saveTimer=setTimeout(()=>localStorage.setItem(storageKey,JSON.stringify(snapshot())),400);
        if(!autoPreview)await refreshData();},preview:async()=>{await enterPreview();}});
    window.uxEditor={model,data,scene,tree,inspector,slicing,select,get selected(){return selected;},get results(){return results;},get viewMode(){return viewMode;},get previewStatus(){return {...scene.progressive.status(),load:{...previewLoad}};},refreshData,refresh,group,ungroup,reparent,getProject:snapshot,renderIdentity,
      loadProject:async doc=>{doc=UXCoordinates.prepare(doc);model.load(doc);await slicing.restore(doc);restoreCamera(doc);select(['work']);},mapping:ids=>data.mapping(ids.length===1&&ids[0]==='global'?['work']:ids,model),saveAnnotations,storageKey};
    await slicing.initialize(bootDoc);
    $('coverage').textContent='已有统计可预览 · 一级切片须显式确认';renderViewState();select(selected);mode('translate');scene.fit(['work']);if(bootDoc){restoreCamera(bootDoc);try{localStorage.setItem(storageKey,JSON.stringify(snapshot()));}catch(e){message('新坐标自动保存失败，请保存工程文件：'+e.message);}}
  }catch(e){
    message('启动失败：'+e.message);console.error(e);
    bootFail('启动失败',e.message,
      '先确认地址是 http://127.0.0.1:8128/ 而不是 file://，再看状态栏和浏览器网络面板里的具体请求。',
      'http://127.0.0.1:8128/');
  }
})();

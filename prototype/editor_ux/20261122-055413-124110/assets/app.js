/* 独立UX启动与联动。旧工程键、旧缓存和服务不修改。 */
(async()=>{
  'use strict';
  const $=id=>document.getElementById(id),storageKey='snowglass.editor-ux.20261122-055413-124110.v2';
  const kindName={global:'全局配置',root:'模型根',tower:'塔',layer:'层',group:'操作组',block:'权重功能块',ghost:'幽灵毛坯',reference:'参照集合',project:'工程'};
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
      'http://127.0.0.1:8128/\n\nuv run --no-project python -m http.server 8128 --bind 127.0.0.1 --directory prototype/editor_ux/20261122-055413-124110');
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
    const model=new UXModel.Model(topo,provenance),data=new UXData.Data(manifest);let selected=['L16.down'],preview=['L16.down'],results=[],serial=0,saveTimer,inspector,tree,scene,dataTimer=null,structPending=false;
    const observed=()=>selected.length===1&&selected[0]==='global'?preview:selected;
    const snapshot=()=>({...model.snapshot(),view:{selected:selected.slice(),preview:preview.slice(),isolate:scene.isolate,exposure:scene.exposure,camera:scene.camera.position.toArray(),target:scene.orbit.target.toArray(),open:[...tree.open]}});
    const safe=fn=>{try{return fn();}catch(e){message(e.message);}};
    async function refreshData(){
      const token=++serial,ids=model.leaves(observed()).filter(id=>model.nodes.get(id).type==='block');
      try{const values=await Promise.all(ids.map(id=>data.evaluate(id,model)));if(token!==serial)return;results=values;scene.drawSnow(values);inspector.results(values);
        const count=values.reduce((n,r)=>n+r.count,0),missing=values.filter(r=>!r.pieces.length).length;
        const reference=selected.length===1&&selected[0]==='global'?`编辑全局；参考预览 ${preview.join('、')}，曲线来源 ${ids[0]?model.nodes.get(model.resolve(ids[0],'curve').source).name:'无'}。`:'当前对象预览。';
        $('view-caption').textContent=`${reference}${ids.length} 个功能块 · ${count} 个真实候选格 · ${missing} 个未计算／缺权重块。${scene.isolate?'结构隔离仅影响屏幕，':'全景结构可能遮挡纹理，'}不补模拟。`;renderReport();
      }catch(e){if(token===serial){
        const same=ids.length===results.length&&ids.every(id=>results.some(r=>r.id===id));if(!same){results=[];scene.drawSnow([]);}
        $('view-caption').textContent=same?'当前窗口／缓存无效，保留上一有效灰度预览；当前设置尚未应用。':'所选统计无法载入，未填充任何替代纹理。';
        message(e.message+'；没有重新计算权重。');
      }}
    }
    function renderReport(){
      if($('report').hidden)return;const report=UXChecks.run(model),root=$('report');root.textContent='';
      const heading=document.createElement('h3');heading.textContent='后验报告 · 只提示，不阻挠';root.append(heading);
      const line=(text,tone)=>{const p=document.createElement('p');p.textContent=text;if(tone)p.className=tone;root.append(p);};
      const size=model.bounds(['work']).getSize(new THREE.Vector3());line('模型世界包围盒：'+size.toArray().map(v=>v.toFixed(3)).join(' × ')+' mm');
      line('进入作品功能块：'+report.solids+'；仿射盒重叠：'+report.overlaps.length+' 对',report.overlaps.length?'danger':null);
      for(const g of report.ghosts)line(g.name+(g.primary?'（主参照）':'')+'：'+g.outside.length+'块出界'+(g.invalid?'，内预留区域为空':'')+(g.approx?'，圆柱内偏移保守近似':''),g.outside.length?'danger':g.invalid?'warn':null);
      for(const r of results){if(!r.pieces.length)continue;const m=model.world(r.id),side=model.resolve(r.id,'snowSize').value;
        const spacing=r.pieces.flatMap(p=>p.grid.map((n,i)=>new THREE.Vector3().setFromMatrixColumn(m,i).length()*p.region.size[i]/n)),tight=Math.min(...spacing)<side;
        line(r.id+'：'+r.count+'候选格，'+r.positive+'正灰度格，'+r.masked+'显式筛除；轴向最小间距 '+Math.min(...spacing).toFixed(5)+' mm'+(tight?'，小于雪花边长，存在干涉风险':''),tight?'warn':null);
      }
      model.layoutWarnings.forEach(text=>line(text,'warn'));line('轴向间距不是全部跨块近邻检查。没有厂家灰阶标定，不据点距宣称可加工；爆点数、工时、灰度容量未核实。','warn');
    }
    function refresh(transient=false){
      selected=selected.filter(id=>model.nodes.has(id));preview=preview.filter(id=>model.nodes.has(id));scene.observation=observed();scene.select(selected);renderIdentity();
      if(transient){
        inspector.updateTransform();inspector.curveUI?.redraw();
        if(!structPending){structPending=true;requestAnimationFrame(()=>{structPending=false;scene.structure();scene.render();});}
        clearTimeout(dataTimer);dataTimer=setTimeout(()=>refreshData(),50);
        return;
      }
      {const curveState=inspector.curveUI?{index:inspector.curveUI.index,handles:inspector.curveUI.handles}:null;inspector.ids=selected;inspector.render();if(curveState&&inspector.curveUI){Object.assign(inspector.curveUI,curveState);inspector.curveUI.redraw();}tree.selected=selected;tree.render();
        clearTimeout(saveTimer);saveTimer=setTimeout(()=>{try{localStorage.setItem(storageKey,JSON.stringify(snapshot()));}catch(e){message('自动保存失败，请保存工程文件');}},400);}
      scene.structure();refreshData();renderReport();$('undo').disabled=!model.history.length;$('redo').disabled=!model.future.length;
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
      if(n.type==='block'){
        const src=topo.blocks.find(b=>b.id===n.sourceId)||(topo.geometry_only||[]).find(b=>b.id===n.sourceId);
        if(src){
          row(`源层 ${src.layer!=null?'L'+src.layer:src.vlayer!=null?'V'+src.vlayer:'—'} · 槽位 ${src.slot||'—'} · ${(src.tensors||[]).length} 个张量`);
          for(const t of src.tensors||[]){
            const box=document.createElement('div');box.className='id-tensor';
            box.textContent=`${t.gguf}\n${t.shape.join('×')} · ${t.qtype||'—'}${t.restore?' · 已按HF约定还原':''}`;el.append(box);
          }
        }else row('没有源张量（空框或权重未收录）');
        const real=data.groups.has(n.sourceId),st=document.createElement('p');
        st.className='id-state'+(real?'':' muted');st.textContent=real?'统计状态：已有真实缓存':'统计状态：未计算／权重未收录';el.append(st);
        const size=model.bounds([n.id]).getSize(new THREE.Vector3());
        row('包络 '+size.toArray().map(v=>v.toFixed(3)).join(' × ')+' mm');
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
    tree=new UXTree(model,data,select,reparent);inspector=new UXInspector(model,message);
    scene=new UXScene($('view'),model,(ids,mode)=>{tree.reveal=true;select(ids,mode);},hover,()=>inspector.updateTransform());model.listeners.push(refresh);
    async function group(){try{const ids=model.roots(selected),parents=ids.map(id=>model.ancestors(id));if(!ids.length)throw Error('先多选或框选对象');
      const parent=parents[0].find(p=>parents.every(a=>a.includes(p))),changes=ids.flatMap(id=>model.changes(id,parent));
      if(changes.length&&!await confirmAction('打组将改变部分继承参数','成员移动到共同上级下的新组，以下参数的继承来源将变化：\n'+[...new Set(changes)].join('、')+'\n世界变换保留；不会复制整套参数。'))return;
      const id=model.group(ids);select([id]);tree.open.add(id);tree.render();message('新组无局部覆盖；只改动／固定的项才覆盖');}catch(e){message(e.message);}}
    async function ungroup(keep){const id=selected.length===1?selected[0]:null,g=model.nodes.get(id);if(g?.type!=='group'){message('先选一个操作组');return;}
      const children=model.children(id).map(n=>n.id),keys=Object.keys(g.overrides);
      if(keys.length&&!await confirmAction(keep?'解组并保留组局部设置':'解组后继续继承',keep?'仅将组实际覆盖的适用项下放为成员本地值，不盖过成员已有覆盖：\n'+keys.join('、'):'组的这些局部覆盖随组撤销，成员未覆盖项改为继承上级：\n'+keys.join('、')))return;
      safe(()=>model.ungroup(id,keep));select(children);message(keep?'已解组，明确保留了相关局部覆盖':'已解组，未覆盖项继续继承');}
    $('group').onclick=group;$('ungroup').onclick=()=>ungroup(false);$('ungroup-keep').onclick=()=>ungroup(true);
    $('remove').onclick=async()=>{const ids=model.roots(selected);if(!ids.length)return;if(await confirmAction('从当前工程删除所选及其内容',ids.map(id=>model.nodes.get(id).name).join('\n')+'\n此操作可撤销，不删除权重或缓存文件。'))safe(()=>{model.commit(()=>{for(const id of ids){if(['project','global','work','text','vision','refs'].includes(id))throw Error('不能删除系统根');for(const key of [id,...model.descendants(id)])model.nodes.delete(key);}if(!model.nodes.has(model.primaryGhost))model.primaryGhost=[...model.nodes.values()].find(n=>n.type==='ghost')?.id||null;});select([]);});};
    $('new-box').onclick=()=>safe(()=>select([model.newGhost('box')]));$('new-cylinder').onclick=()=>safe(()=>select([model.newGhost('cylinder')]));
    $('undo').onclick=()=>safe(()=>model.undo());$('redo').onclick=()=>safe(()=>model.redo());
    $('select-all').onclick=()=>select([...model.nodes.values()].filter(n=>n.type==='block').map(n=>n.id));$('select-none').onclick=()=>select([]);
    $('select-layer').onclick=()=>select(topo.blocks.filter(b=>b.layer===+$('layer-number').value&&!b.id.startsWith('V')&&model.nodes.has(b.id)).map(b=>b.id));
    $('select-column').onclick=()=>select(topo.blocks.filter(b=>model.nodes.has(b.id)&&($('slot').value==='vision'?b.id.startsWith('V'):!b.id.startsWith('V')&&b.slot===$('slot').value)).map(b=>b.id));
    const mode=value=>{scene.setMode(value);document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===value));};document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>mode(b.dataset.mode));
    const boxButton=$('box-select'),syncBox=()=>{boxButton.classList.toggle('active',scene.boxMode);boxButton.setAttribute('aria-pressed',String(scene.boxMode));};
    boxButton.onclick=()=>{scene.boxMode=!scene.boxMode;syncBox();};
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
    $('exposure').oninput=()=>{scene.exposure=+$('exposure').value;$('exposure-out').textContent=scene.exposure.toFixed(2);scene.drawSnow(results);};
    for(const [id,text] of [['slice-1','首批未接入真实统计与网格重算；统计生成设置改变后才需要这一步。'],['slice-2','首批未接入厂家加工导出；不会把灰度映射冒充可加工文件。']])
      $(id).addEventListener('pointerdown',()=>message(text));
    $('report-toggle').onclick=()=>{$('report').hidden=!$('report').hidden;renderReport();};$('focus-toggle').onclick=()=>{document.body.classList.toggle('focus');scene.resize();};
    $('save-project').onclick=()=>download(snapshot(),'snowglass_ux_'+stamp()+'.json');$('open-project').onclick=()=>$('project-file').click();
    $('project-file').onchange=async()=>{try{const doc=JSON.parse(await $('project-file').files[0].text());model.load(doc);if(doc.view?.camera&&doc.view.camera.length===3&&[...doc.view.camera,...doc.view.target].every(Number.isFinite)){scene.camera.position.fromArray(doc.view.camera);scene.orbit.target.fromArray(doc.view.target);scene.orbit.update();}
        if(Array.isArray(doc.view?.open))tree.open=new Set(doc.view.open);preview=(doc.view?.preview||['L16.down']).filter(id=>model.nodes.has(id));scene.isolate=doc.view?.isolate??false;scene.exposure=doc.view?.exposure??1;$('exposure').value=scene.exposure;$('exposure-out').textContent=scene.exposure.toFixed(2);$('isolate-view').classList.toggle('active',scene.isolate);$('isolate-view').setAttribute('aria-checked',String(scene.isolate));
        select((doc.view?.selected||['work']).filter(id=>model.nodes.has(id)));message('新版工程已恢复，继承关系与覆盖项保留');}catch(e){message('打开失败：'+e.message);}finally{$('project-file').value='';}};
    $('save-mapping').onclick=async()=>{if(!selected.length){message('先选择有真实统计的块或组');return;}const button=$('save-mapping');button.disabled=true;
      try{const frozen=new UXModel.Model(topo,provenance);frozen.restore(model.snapshot());const scope=selected.length===1&&selected[0]==='global'?['work']:selected.slice();const doc=await data.mapping(scope,frozen);if(!doc.results.some(r=>r.pieces.length))throw Error('所选范围没有真实统计，不输出空白冒充成功');doc.project=frozen.snapshot();download(doc,'gray_mapping_'+stamp()+'.json');message('灰度映射已保存为新文件；未生成厂家加工文件');}
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
    try{const stored=localStorage.getItem(storageKey);if(stored){const doc=JSON.parse(stored);model.validate(doc);model.restore(doc);selected=(doc.view?.selected||selected).filter(id=>model.nodes.has(id));preview=(doc.view?.preview||preview).filter(id=>model.nodes.has(id));scene.isolate=doc.view?.isolate??false;scene.exposure=doc.view?.exposure??1;$('exposure').value=scene.exposure;$('exposure-out').textContent=scene.exposure.toFixed(2);const iso=$('isolate-view');iso.classList.toggle('active',scene.isolate);iso.setAttribute('aria-checked',String(scene.isolate));}}catch(e){message('自动保存不兼容，保留文件并用新工程启动：'+e.message);}
    window.uxEditor={model,data,scene,tree,inspector,select,get selected(){return selected;},get results(){return results;},refreshData,refresh,group,ungroup,reparent,getProject:snapshot,renderIdentity,
      loadProject:doc=>{model.load(doc);select(['work']);},mapping:ids=>data.mapping(ids.length===1&&ids[0]==='global'?['work']:ids,model),storageKey};
    $('coverage').textContent='65组 / 124张量已有统计 · 不跑新权重';select(selected);mode('translate');scene.fit(selected);message('独立新版已就绪：未计算块留结构，不填模拟纹理。');
  }catch(e){
    message('启动失败：'+e.message);console.error(e);
    bootFail('启动失败',e.message,
      '先确认地址是 http://127.0.0.1:8128/ 而不是 file://，再看状态栏和浏览器网络面板里的具体请求。',
      'http://127.0.0.1:8128/');
  }
})();

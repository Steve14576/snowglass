/* 独立UX启动与联动。旧工程键、旧缓存和服务不修改。 */
(async()=>{
  'use strict';
  const $=id=>document.getElementById(id),storageKey='snowglass.editor-ux.20261122-055413-124110';
  const message=text=>$('status').textContent=text;
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
    const model=new UXModel.Model(topo,provenance),data=new UXData.Data(manifest);let selected=['L16.down'],preview=['L16.down'],results=[],serial=0,saveTimer,inspector,tree,scene;
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
      const line=text=>{const p=document.createElement('p');p.textContent=text;root.append(p);};
      const size=model.bounds(['work']).getSize(new THREE.Vector3());line('模型世界包围盒：'+size.toArray().map(v=>v.toFixed(3)).join(' × ')+' mm');
      line('进入作品功能块：'+report.solids+'；仿射盒重叠：'+report.overlaps.length+' 对');
      for(const g of report.ghosts)line(g.name+(g.primary?'（主参照）':'')+'：'+g.outside.length+'块出界'+(g.invalid?'，内预留区域为空':'')+(g.approx?'，圆柱内偏移保守近似':''));
      for(const r of results){if(!r.pieces.length)continue;const m=model.world(r.id),side=model.resolve(r.id,'snowSize').value;
        const spacing=r.pieces.flatMap(p=>p.grid.map((n,i)=>new THREE.Vector3().setFromMatrixColumn(m,i).length()*p.region.size[i]/n));
        line(r.id+'：'+r.count+'候选格，'+r.positive+'正灰度格，'+r.masked+'显式筛除；轴向最小间距 '+Math.min(...spacing).toFixed(5)+' mm'+(Math.min(...spacing)<side?'，小于雪花边长，存在干涉风险':''));
      }
      model.layoutWarnings.forEach(line);line('轴向间距不是全部跨块近邻检查。没有厂家灰阶标定，不据点距宣称可加工；爆点数、工时、灰度容量未核实。');
    }
    function refresh(transient=false){
      selected=selected.filter(id=>model.nodes.has(id));preview=preview.filter(id=>model.nodes.has(id));scene.observation=observed();scene.select(selected);
      if(transient){inspector.updateTransform();inspector.curveUI?.redraw();}
      else{const curveState=inspector.curveUI?{index:inspector.curveUI.index,handles:inspector.curveUI.handles}:null;inspector.ids=selected;inspector.render();if(curveState&&inspector.curveUI){Object.assign(inspector.curveUI,curveState);inspector.curveUI.redraw();}tree.selected=selected;tree.render();
        clearTimeout(saveTimer);saveTimer=setTimeout(()=>{try{localStorage.setItem(storageKey,JSON.stringify(snapshot()));}catch(e){message('自动保存失败，请保存工程文件');}},400);}
      scene.structure();refreshData();renderReport();$('undo').disabled=!model.history.length;$('redo').disabled=!model.future.length;
    }
    function select(ids,add=false){
      if(add){const set=new Set(selected);ids.forEach(id=>set.has(id)?set.delete(id):set.add(id));selected=[...set];}else selected=ids.filter(id=>model.nodes.has(id));
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
    scene=new UXScene($('view'),model,select,hover,()=>inspector.updateTransform());model.listeners.push(refresh);
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
    $('box-select').onclick=()=>{scene.boxMode=!scene.boxMode;$('box-select').classList.toggle('active',scene.boxMode);};
    const isolation=value=>{scene.isolate=value;$('isolate-view').classList.toggle('active',value);scene.structure();scene.render();refreshData();};
    $('isolate-view').onclick=()=>isolation(!scene.isolate);
    $('fit-all').onclick=()=>{isolation(false);scene.fit(['work']);};$('fit-selected').onclick=()=>scene.fit(observed());$('front-view').onclick=()=>scene.fit(observed().length?observed():['work'],true);
    $('exposure').oninput=()=>{scene.exposure=+$('exposure').value;$('exposure-out').textContent=scene.exposure.toFixed(2);scene.drawSnow(results);};
    $('report-toggle').onclick=()=>{$('report').hidden=!$('report').hidden;renderReport();};$('focus-toggle').onclick=()=>{document.body.classList.toggle('focus');scene.resize();};
    $('save-project').onclick=()=>download(snapshot(),'snowglass_ux_'+stamp()+'.json');$('open-project').onclick=()=>$('project-file').click();
    $('project-file').onchange=async()=>{try{const doc=JSON.parse(await $('project-file').files[0].text());model.load(doc);if(doc.view?.camera&&doc.view.camera.length===3&&[...doc.view.camera,...doc.view.target].every(Number.isFinite)){scene.camera.position.fromArray(doc.view.camera);scene.orbit.target.fromArray(doc.view.target);scene.orbit.update();}
        if(Array.isArray(doc.view?.open))tree.open=new Set(doc.view.open);preview=(doc.view?.preview||['L16.down']).filter(id=>model.nodes.has(id));scene.isolate=doc.view?.isolate??true;scene.exposure=doc.view?.exposure??1;$('exposure').value=scene.exposure;$('exposure-out').textContent=scene.exposure.toFixed(2);$('isolate-view').classList.toggle('active',scene.isolate);
        select((doc.view?.selected||['work']).filter(id=>model.nodes.has(id)));message('新版工程已恢复，继承关系与覆盖项保留');}catch(e){message('打开失败：'+e.message);}finally{$('project-file').value='';}};
    $('save-mapping').onclick=async()=>{if(!selected.length){message('先选择有真实统计的块或组');return;}const button=$('save-mapping');button.disabled=true;
      try{const frozen=new UXModel.Model(topo,provenance);frozen.restore(model.snapshot());const scope=selected.length===1&&selected[0]==='global'?['work']:selected.slice();const doc=await data.mapping(scope,frozen);if(!doc.results.some(r=>r.pieces.length))throw Error('所选范围没有真实统计，不输出空白冒充成功');doc.project=frozen.snapshot();download(doc,'gray_mapping_'+stamp()+'.json');message('灰度映射已保存为新文件；未生成厂家加工文件');}
      catch(e){message(e.message);}finally{button.disabled=false;refreshData();}};
    const splitter=$('splitter');let start=null;splitter.onpointerdown=e=>{start={y:e.clientY,height:document.querySelector('.tree-panel').clientHeight};splitter.setPointerCapture(e.pointerId);};
    splitter.onpointermove=e=>{if(!start)return;document.documentElement.style.setProperty('--tree-height',Math.max(140,Math.min($('sidebar').clientHeight-220,start.height+e.clientY-start.y))+'px');};splitter.onpointerup=()=>start=null;
    splitter.onkeydown=e=>{if(['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const h=document.querySelector('.tree-panel').clientHeight;document.documentElement.style.setProperty('--tree-height',Math.max(140,Math.min($('sidebar').clientHeight-220,h+(e.key==='ArrowDown'?20:-20)))+'px');}};
    document.addEventListener('keydown',e=>{if(e.target.closest('input,select,textarea')||$('confirm-dialog').open)return;const key=e.key.toLowerCase();
      if(e.ctrlKey&&key==='z'){e.preventDefault();e.shiftKey?model.redo():model.undo();return;}if(e.ctrlKey&&key==='g'){e.preventDefault();group();return;}
      if(!e.ctrlKey){if({w:'translate',e:'rotate',r:'scale',q:'off'}[key])mode({w:'translate',e:'rotate',r:'scale',q:'off'}[key]);if(key==='b')$('box-select').click();if(key==='f')$('focus-toggle').click();}
    });
    try{const stored=localStorage.getItem(storageKey);if(stored){const doc=JSON.parse(stored);model.validate(doc);model.restore(doc);selected=(doc.view?.selected||selected).filter(id=>model.nodes.has(id));preview=(doc.view?.preview||preview).filter(id=>model.nodes.has(id));scene.isolate=doc.view?.isolate??true;scene.exposure=doc.view?.exposure??1;$('exposure').value=scene.exposure;$('exposure-out').textContent=scene.exposure.toFixed(2);$('isolate-view').classList.toggle('active',scene.isolate);}}catch(e){message('自动保存不兼容，保留文件并用新工程启动：'+e.message);}
    window.uxEditor={model,data,scene,tree,inspector,select,get selected(){return selected;},get results(){return results;},refreshData,refresh,group,ungroup,reparent,getProject:snapshot,
      loadProject:doc=>{model.load(doc);select(['work']);},mapping:ids=>data.mapping(ids.length===1&&ids[0]==='global'?['work']:ids,model),storageKey};
    $('coverage').textContent='65组 / 124张量已有统计 · 不跑新权重';select(selected);mode('translate');scene.fit(selected);message('独立新版已就绪：未计算块留结构，不填模拟纹理。');
  }catch(e){message('启动失败：'+e.message);console.error(e);}
})();

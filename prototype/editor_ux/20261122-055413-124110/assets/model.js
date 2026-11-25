/* 单父操作树。只保存明确覆盖，不复制继承值；变换独立于权重统计。 */
(() => {
  'use strict';
  const clone=CurveMath.copy,I=()=>new THREE.Matrix4(),arr=m=>m.toArray(),matrix=a=>new THREE.Matrix4().fromArray(a);
  const GRID_DEFAULTS={gridX:16,gridY:16,gridZ:32};
  const LEGACY_DEFAULTS={...GRID_DEFAULTS,sourceConvention:'hf',extraDiagnostics:false};
  const DEFAULTS={...GRID_DEFAULTS,sourceConvention:'gguf',extraDiagnostics:false,channel:'full',windowMode:'range',black:0,white:1,curve:CurveMath.linear(),filter:false,cutoff:.25,
    frameT:.04,shellT:.02,frameGray:.18,shellGray:.024,snowSize:.012,gap:0,widthMode:'equal',visible:true,include:true,
    labelEnabled:true,labelFont:'Microsoft YaHei',labelSize:.7,squash:.55,depth:6.2,pitch:.08,dotUm:60,speed:4500};
  const LOCAL=Object.keys(DEFAULTS).filter(k=>!['squash','depth','pitch','dotUm','speed'].includes(k));
  function validParam(key,v){
    if(!Object.hasOwn(DEFAULTS,key))throw Error('未知参数 '+key);
    if(Object.hasOwn(GRID_DEFAULTS,key)&&(!Number.isInteger(v)||v<1||v>64))throw Error('统计网格须为1–64的整数');
    if(key==='curve')return CurveMath.validate(v);
    if(key==='labelFont'){if(typeof v!=='string'||!v.trim()||v.length>60)throw Error('字体名不能为空且不超过60字');return true;}
    if(typeof v!==typeof DEFAULTS[key]||(typeof v==='number'&&!Number.isFinite(v)))throw Error('参数类型无效');
    // 框／壳厚度允许 0：语义是“没有这个结构件”，与灰度0（几何仍在但不显影）不同。
    if(['frameT','shellT','frameGray','shellGray'].includes(key)&&v<0)throw Error('厚度与灰度不能为负；0 表示没有该结构件／不显影');
    if(['snowSize','labelSize','squash','depth','pitch','dotUm','speed'].includes(key)&&v<=0)throw Error('尺寸与精度必须为正');
    if(['frameGray','shellGray','cutoff'].includes(key)&&(v<0||v>1))throw Error('灰度／门槛范围是0–1');
    if(key==='sourceConvention'&&!['gguf','hf'].includes(v))throw Error('权重数值约定无效');
    if(key==='channel'&&!['full','feature','rowcol','residual'].includes(v))throw Error('统计通道无效');
    if(key==='windowMode'&&!['range','reference'].includes(v))throw Error('窗口模式无效');
    if(key==='widthMode'&&!['equal','params'].includes(v))throw Error('块宽模式无效');return true;
  }
  class Node {
    constructor(id,type,name,parent,sourceId=null){Object.assign(this,{id,type,name,parent,sourceId,local:arr(I()),overrides:{}});}
  }
  class Model {
    constructor(topo,provenance){this.topo=topo;this.provenance=provenance;this.nodes=new Map();this.history=[];this.future=[];this.seq=1;this.listeners=[];this.gesture=null;this.initialize();}
    initialize(){
      this.nodes.clear();const add=(...args)=>{const n=new Node(...args);this.nodes.set(n.id,n);return n;};
      add('project','project','snowglass 工程',null);add('global','global','全局','project').values=clone(DEFAULTS);
      add('work','root','作品／模型','project');add('text','tower','文本塔','work');add('vision','tower','视觉塔','work');add('refs','reference','幽灵毛坯','project');
      for(let i=0;i<this.topo.model.n_layers;i++)add('layer-'+i,'layer','L'+String(i).padStart(2,'0'),'text');
      for(let i=0;i<this.topo.model.vision_layers;i++)add('vlayer-'+i,'layer','V'+String(i).padStart(2,'0'),'vision');
      for(const b of this.topo.blocks){const parent=b.id.startsWith('V')?(Number.isInteger(b.vlayer)?'vlayer-'+b.vlayer:'vision'):(Number.isInteger(b.layer)?'layer-'+b.layer:'text');add(b.id,'block',b.label,parent,b.id);}
      add('mtp','block','MTP · 权重未收录','text','mtp');add('annotations','annotationRoot','标注','project');
      const g=add('ghost-1','ghost','参照毛坯 1','refs');g.data={shape:'box',dims:[25,80,25],radius:12.5,height:80,margin:2.5};this.primaryGhost=g.id;this.rebase();
    }
    rebase(){
      const p=this.nodes.get('global').values;this.bases=new Map();this.layoutWarnings=[];
      const layouts={equal:SnowLayout(this.topo,{squash:p.squash,depth:p.depth,widthMode:'equal'}),params:SnowLayout(this.topo,{squash:p.squash,depth:p.depth,widthMode:'params'})};
      const choice=new Map();
      for(const b of this.topo.blocks.filter(b=>['mixer','ffn'].includes(b.slot)&&!b.id.startsWith('V'))){
        const key=b.layer+':'+b.slot;if(choice.has(key))continue;
        const members=this.topo.blocks.filter(t=>t.layer===b.layer&&t.slot===b.slot&&!t.id.startsWith('V')&&this.nodes.has(t.id));
        const modes=new Set(members.map(t=>this.resolve(t.id,'widthMode').value));
        choice.set(key,modes.size===1?[...modes][0]:p.widthMode);if(modes.size>1)this.layoutWarnings.push(key+' 块宽覆盖不一致，使用全局模式');
      }
      for(const s of layouts.equal.solids){if(!this.nodes.has(s.id))continue;
        const mode=choice.get(s.block.layer+':'+s.block.slot)||p.widthMode;
        const picked=layouts[mode].solids.find(b=>b.id===s.id)||s,gap=this.resolve(s.id,'gap').value;
        const dims=picked.slot.geometrySize.map((v,i)=>Math.max(.0001,v-(i<2?gap:0)));
        if(picked.slot.geometrySize.slice(0,2).some(v=>v<=gap))this.layoutWarnings.push(s.id+' 间隙超过基础尺寸，仅保留数学最小厚度');
        this.bases.set(s.id,{...picked,dims,matrix:I().makeTranslation(...picked.slot.center).multiply(UXCoordinates.basis()).multiply(I().makeScale(...dims))});
      }
    }
    resolve(id,key){let n=this.nodes.get(id);while(n&&n.type!=='global'){if(Object.hasOwn(n.overrides,key))return {value:n.overrides[key],source:n.id,own:n.id===id};n=this.nodes.get(n.parent);}
      return {value:this.nodes.get('global').values[key],source:'global',own:id==='global'};}
    children(id){return [...this.nodes.values()].filter(n=>n.parent===id);}
    descendants(id){const out=[];for(const n of this.children(id)){out.push(n.id,...this.descendants(n.id));}return out;}
    roots(ids){const set=new Set(ids.filter(id=>this.nodes.has(id)));return [...set].filter(id=>{let n=this.nodes.get(id);while(n.parent){if(set.has(n.parent))return false;n=this.nodes.get(n.parent);}return true;});}
    chain(id){const n=this.nodes.get(id);if(!n||!n.parent)return I();if(UXAnnotationState.is(n))return UXAnnotationState.frame(this,id);return this.chain(n.parent).multiply(matrix(n.local));}
    world(id){const n=this.nodes.get(id);if(UXAnnotationState.is(n))return UXAnnotationState.world(this,id);const m=this.chain(id);if(n.type==='block')return m.multiply(this.bases.get(id).matrix);
      if(n.type==='ghost'){const d=n.data;return m.multiply(UXCoordinates.basis()).multiply(I().makeScale(...(d.shape==='box'?d.dims:[2*d.radius,d.height,2*d.radius])));}return m;}
    objectFrame(id){const w=this.world(id);return ['block','ghost','label'].includes(this.nodes.get(id).type)?w.multiply(UXCoordinates.inverse()):w;}
    geometryFrame(id){return this.chain(id).multiply(UXCoordinates.basis());}
    leaves(ids){return [...new Set(ids.flatMap(id=>[id,...this.descendants(id)]))].filter(id=>['block','ghost','label'].includes(this.nodes.get(id)?.type));}
    bounds(ids){const box=new THREE.Box3();for(const id of this.leaves(ids)){const m=this.world(id),zs=this.nodes.get(id).type==='label'?[0]:[-.5,.5];for(const x of [-.5,.5])for(const y of [-.5,.5])for(const z of zs)box.expandByPoint(new THREE.Vector3(x,y,z).applyMatrix4(m));}return box;}
    snapshot(){return {kind:'snowglass.editor-ux.v1',topology_sha256:this.provenance.topology_sha256,manifest_sha256:this.provenance.manifest_sha256,
      bundle:this.provenance.bundle,coordinateSystem:UXCoordinates.SYSTEM,localGeometryBasis:UXCoordinates.GEOMETRY,annotationPolicy:UXCoordinates.LABEL_POLICY,annotationVersion:1,seq:this.seq,primaryGhost:this.primaryGhost,nodes:clone([...this.nodes.values()])};}
    emit(transient=false){this.rebase();this.listeners.forEach(fn=>fn(transient));}
    restore(s){s=UXCoordinates.prepare(s);this.nodes=new Map(s.nodes.map(v=>[v.id,Object.assign(new Node(v.id,v.type,v.name,v.parent,v.sourceId),clone(v))]));
      // 旧工程没有网格字段时，沿用当时的固定统计网格；不更换已有统计来源。
      this.nodes.get('global').values={...LEGACY_DEFAULTS,...this.nodes.get('global').values};this.seq=s.seq;this.primaryGhost=s.primaryGhost;UXAnnotationState.ensureRoot(this);this.rebase();}
    commit(fn,preserveWorld=false){
      const before=this.snapshot(),worlds=preserveWorld?new Map(this.leaves(['work','refs','annotations']).map(id=>[id,UXAnnotationState.is(this.nodes.get(id))?this.chain(id):this.world(id)])):null;
      try{fn();
        if(preserveWorld){
          const parents=new Map(before.nodes.map(n=>[n.id,n.parent])),moved=new Set([...this.nodes.values()].filter(n=>parents.has(n.id)&&parents.get(n.id)!==n.parent).map(n=>n.id));this.rebase();
          for(const [id,oldWorld] of worlds){const n=this.nodes.get(id);if(!n||![id,...this.ancestors(id)].some(v=>moved.has(v)))continue;
            if(UXAnnotationState.is(n)){UXAnnotationState.setFrame(this,id,oldWorld);continue;}
            const base=n.type==='block'?this.bases.get(id).matrix:UXCoordinates.basis().multiply(I().makeScale(...(n.data.shape==='box'?n.data.dims:[2*n.data.radius,n.data.height,2*n.data.radius])));
            n.local=arr(this.chain(n.parent).invert().multiply(oldWorld).multiply(base.clone().invert()));
          }
        }
        if(JSON.stringify(before)!==JSON.stringify(this.snapshot())){this.history.push(before);if(this.history.length>100)this.history.shift();this.future=[];this.emit();}
      }catch(e){this.restore(before);throw e;}
    }
    beginGesture(){if(!this.gesture)this.gesture=this.snapshot();}
    updateGesture(fn){fn();this.emit(true);}
    endGesture(){if(!this.gesture)return;const before=this.gesture;this.gesture=null;if(JSON.stringify(before)!==JSON.stringify(this.snapshot())){this.history.push(before);if(this.history.length>100)this.history.shift();this.future=[];this.emit();}}
    undo(){if(!this.history.length)return;this.future.push(this.snapshot());this.restore(this.history.pop());this.emit();}
    redo(){if(!this.future.length)return;this.history.push(this.snapshot());this.restore(this.future.pop());this.emit();}
    put(id,key,v){validParam(key,v);const n=this.nodes.get(id);if(!n)throw Error('对象不存在');const changed=JSON.stringify(this.resolve(id,key).value)!==JSON.stringify(v);
      if(UXAnnotationState.is(n)&&!UXAnnotationState.STYLE.includes(key))throw Error('标注只接受字体、字号和启用状态；文字是自己的内容');
      if(key==='labelEnabled'&&n.type!=='global'&&!UXAnnotationState.is(n))throw Error('标签启用状态只属于独立标注，不属于源模型');
      if(Object.hasOwn(GRID_DEFAULTS,key)){const cells=Object.keys(GRID_DEFAULTS).reduce((a,k)=>a*(k===key?v:this.resolve(id,k).value),1);if(cells>65536)throw Error('当前每分区最多65536格（资源限制）');}
      if(key==='black'||key==='white'){const low=key==='black'?v:this.resolve(id,'black').value,high=key==='white'?v:this.resolve(id,'white').value;if(high<=low)throw Error('白端必须高于黑端');}
      if(n.type==='global'){n.values[key]=clone(v);if(changed)UXAnnotationState.fontChanged(this,id,key);return;}
      if(!LOCAL.includes(key)||['reference','ghost','project'].includes(n.type))throw Error('此对象不能覆盖该参数');n.overrides[key]=clone(v);if(changed)UXAnnotationState.fontChanged(this,id,key);}
    set(id,key,v){validParam(key,v);if(JSON.stringify(this.resolve(id,key).value)===JSON.stringify(v))return;this.commit(()=>this.put(id,key,v));}
    lock(id,key){this.commit(()=>this.put(id,key,clone(this.resolve(id,key).value)));}
    drop(id,key){if(id==='global')return;const before=JSON.stringify(this.resolve(id,key).value);delete this.nodes.get(id).overrides[key];if(before!==JSON.stringify(this.resolve(id,key).value))UXAnnotationState.fontChanged(this,id,key);}
    inherit(id,key){if(id==='global')return;this.commit(()=>this.drop(id,key));}
    rename(id,name){if(this.nodes.get(id).type==='label'){UXAnnotationState.text(this,id,String(name));return;}if(!['group','ghost','labelGroup'].includes(this.nodes.get(id).type))throw Error('只改操作组／毛坯／标签名，不改源张量身份');this.commit(()=>this.nodes.get(id).name=String(name).slice(0,120));}
    delta(ids,delta,operation=null){for(const id of this.roots(ids)){const n=this.nodes.get(id);if(['project','global','reference','annotationRoot'].includes(n.type))continue;
      if(UXAnnotationState.is(n)){UXAnnotationState.delta(this,id,delta,operation);continue;}
      const parent=this.chain(n.parent);n.local=arr(parent.clone().invert().multiply(delta).multiply(parent).multiply(matrix(n.local)));}}
    transform(ids,delta,operation=null){this.commit(()=>this.delta(ids,delta,operation));}
    /** 相对默认位置的参数化变换：偏移(mm)、旋转(弧度)、缩放倍数。 */
    localTRS(id){
      const m=matrix(this.nodes.get(id).local),t=new THREE.Vector3(),q=new THREE.Quaternion(),s=new THREE.Vector3();m.decompose(t,q,s);
      const e=new THREE.Euler().setFromQuaternion(q,'XYZ');return {t:t.toArray(),r:[e.x,e.y,e.z],s:s.toArray()};
    }
    setLocalTRS(id,trs){
      const n=this.nodes.get(id);if(!n)throw Error('对象不存在');
      if(['project','global','reference','annotationRoot'].includes(n.type))throw Error('此对象没有空间变换');
      const t=trs.t.slice(),r=trs.r.slice(),s=trs.s.slice();
      if([...t,...r,...s].some(v=>!Number.isFinite(v)))throw Error('变换数值无效');
      if(s.some(v=>Math.abs(v)<1e-6))throw Error('缩放不能为0');
      const m=new THREE.Matrix4().compose(new THREE.Vector3(...t),new THREE.Quaternion().setFromEuler(new THREE.Euler(...r,'XYZ')),new THREE.Vector3(...s));
      this.commit(()=>{if(UXAnnotationState.is(n)){const old=this.localTRS(id),linear=['r','s'].some(k=>trs[k].some((v,i)=>Math.abs(v-old[k][i])>1e-9));
        const shift=new THREE.Vector3(...trs.t.map((v,i)=>v-old.t[i])).applyMatrix3(new THREE.Matrix3().setFromMatrix4(UXAnnotationState.beforeLocal(this,id)));
        UXAnnotationState.setLocal(this,id,m,linear?'affine':'translate',shift);
      }else n.local=m.toArray();});
    }
    move(id,parent){
      const n=this.nodes.get(id),target=this.nodes.get(parent);if(!n)throw Error('对象不存在');
      if(UXAnnotationState.is(n)||UXAnnotationState.is(target))return UXAnnotationState.move(this,id,parent);
      if(['project','global','work','text','vision','refs'].includes(id)||!target||!['root','tower','layer','group','reference'].includes(target.type))throw Error('不能迁移到这个节点');
      if(id===parent||this.descendants(id).includes(parent))throw Error('不能形成循环对象树');
      const ghost=n.type==='ghost'||this.leaves([id]).some(v=>this.nodes.get(v).type==='ghost'),ref=parent==='refs'||this.ancestors(parent).includes('refs');
      if(ghost!==ref)throw Error('首批不把参照毛坯与模型混组');
      const old=this.chain(n.parent);n.local=arr(this.chain(parent).invert().multiply(old).multiply(matrix(n.local)));n.parent=parent;
    }
    ancestors(id){const out=[];let n=this.nodes.get(id);while(n?.parent){out.push(n.parent);n=this.nodes.get(n.parent);}return out;}
    changes(id,parent){const keys=(UXAnnotationState.is(this.nodes.get(id))?UXAnnotationState.STYLE:LOCAL).filter(k=>!Object.hasOwn(this.nodes.get(id).overrides,k));return keys.filter(k=>JSON.stringify(this.resolve(id,k).value)!==JSON.stringify(this.resolve(parent,k).value));}
    group(ids){if(ids.some(id=>UXAnnotationState.is(this.nodes.get(id))))return UXAnnotationState.group(this,ids);let result;this.commit(()=>{
      ids=this.roots(ids);if(!ids.length||ids.some(id=>['project','global','work','text','vision','refs'].includes(id)))throw Error('请选择块、层、操作组或毛坯');
      const chains=ids.map(id=>this.ancestors(id));const parent=chains[0].find(id=>chains.every(c=>c.includes(id)));
      if(!parent||parent==='project')throw Error('首批不跨作品与参照打组');
      const center=this.bounds(ids).getCenter(new THREE.Vector3()).applyMatrix4(this.chain(parent).invert());
      let id;do{id='group-'+this.seq++;}while(this.nodes.has(id));const n=new Node(id,'group','组 '+(this.seq-1),parent);n.local=arr(I().makeTranslation(...center.toArray()));this.nodes.set(id,n);
      ids.forEach(v=>this.move(v,id));result=id;
    },true);return result;}
    ungroup(id,keep=false){if(this.nodes.get(id)?.type==='labelGroup')return UXAnnotationState.ungroup(this,id,keep);this.commit(()=>{const g=this.nodes.get(id);if(g?.type!=='group')throw Error('先选一个操作组');
      for(const n of this.children(id)){if(keep)for(const [k,v] of Object.entries(g.overrides))if(!Object.hasOwn(n.overrides,k)&&n.type!=='ghost')n.overrides[k]=clone(v);this.move(n.id,g.parent);}
      this.nodes.delete(id);
    },true);}
    remove(id){UXAnnotationState.remove(this,[id]);}
    removeMany(ids){UXAnnotationState.remove(this,ids);}
    planLabels(id,options){return UXAnnotationMath.generate(this,id,options);}
    createLabels(plan,append=false){return UXAnnotationState.create(this,plan,append);}
    setLabelText(id,text){UXAnnotationState.text(this,id,text);}
    setLabelCenter(id,value){UXAnnotationState.setCenter(this,id,value);}
    setLabelAlignment(id,value){UXAnnotationState.setAlignment(this,id,value);}
    annotations(ids){return UXAnnotationState.exportLabels(this,ids);}
    newGhost(shape){let id;this.commit(()=>{id='ghost-'+Date.now().toString(36)+'-'+this.seq++;const n=new Node(id,'ghost','参照毛坯 '+this.seq,'refs');n.data={shape,dims:[25,40,25],radius:12.5,height:40,margin:2.5};this.nodes.set(id,n);if(!this.primaryGhost)this.primaryGhost=id;});return id;}
    ghostField(id,key,v){this.commit(()=>{const n=this.nodes.get(id);if(n.type!=='ghost'||!Number.isFinite(v)||(key==='margin'?v<0:v<=0))throw Error('毛坯尺寸须为正，预留可为零');
      if(typeof key==='number')n.data.dims[key]=v;else n.data[key]=v;});}
    load(doc){
      doc=UXCoordinates.prepare(doc);this.validate(doc);this.commit(()=>this.restore(doc));
    }
    validate(doc){
      doc=UXCoordinates.prepare(doc);
      if(doc?.kind!=='snowglass.editor-ux.v1')throw Error('仅打开新版工程；旧工程不静默迁移');
      if(doc.topology_sha256!==this.provenance.topology_sha256||doc.manifest_sha256!==this.provenance.manifest_sha256)throw Error('工程的拓扑或统计来源不匹配');
      if(!Array.isArray(doc.nodes)||doc.nodes.length>10000||!Number.isInteger(doc.seq)||doc.seq<1)throw Error('对象清单无效');
      const map=new Map(),sources=new Set(),kinds=['project','global','root','tower','reference','layer','group','block','ghost',...UXAnnotationState.TYPES];
      const allowed=['id','type','name','parent','sourceId','local','overrides','data','values'];
      for(const n of doc.nodes){if(!n||Object.keys(n).some(k=>!allowed.includes(k)))throw Error('对象含未知字段');
        if(typeof n.id!=='string'||map.has(n.id)||typeof n.name!=='string'||n.name.length>200||!kinds.includes(n.type))throw Error('对象身份无效');
        if(!Array.isArray(n.local)||n.local.length!==16||n.local.some(v=>!Number.isFinite(v))||Math.abs(matrix(n.local).determinant())<1e-12||Math.abs(n.local[3])+Math.abs(n.local[7])+Math.abs(n.local[11])>1e-8||Math.abs(n.local[15]-1)>1e-8)throw Error('变换矩阵无效');
        for(const [key,v] of Object.entries(n.overrides||{})){if(!LOCAL.includes(key)||['global','project','reference','ghost'].includes(n.type)||(key==='labelEnabled'&&!UXAnnotationState.is(n)))throw Error('非法局部参数');validParam(key,v);}
        if(n.type==='block'){if(n.id!==n.sourceId||(!this.topo.blocks.some(b=>b.id===n.sourceId)&&n.sourceId!=='mtp')||sources.has(n.sourceId))throw Error('源块身份不能重复或更换');sources.add(n.sourceId);}
        if(n.type==='ghost'){const d=n.data;if(!d||!['box','cylinder'].includes(d.shape)||!Array.isArray(d.dims)||d.dims.length!==3||[...d.dims,d.radius,d.height].some(v=>!Number.isFinite(v)||v<=0)||!Number.isFinite(d.margin)||d.margin<0)throw Error('毛坯属性无效');}
        map.set(n.id,n);
      }
      const roots={project:['project',null],global:['global','project'],work:['root','project'],text:['tower','work'],vision:['tower','work'],refs:['reference','project']};
      for(const [id,[type,parent]] of Object.entries(roots))if(map.get(id)?.type!==type||map.get(id).parent!==parent)throw Error('系统根身份或上级无效');
      if(Object.keys(map.get('global').values||{}).some(k=>!Object.hasOwn(DEFAULTS,k)))throw Error('未知全局配置');
      for(const key of Object.keys(DEFAULTS))validParam(key,map.get('global').values?.[key]===undefined?LEGACY_DEFAULTS[key]:map.get('global').values[key]);
      for(const n of map.values()){
        if(n.parent!==null&&!['project','root','tower','reference','layer','group','annotationRoot','labelGroup'].includes(map.get(n.parent)?.type))throw Error('上级不能是数据叶节点');
        let p=n,seen=new Set();while(p.parent!==null){if(seen.has(p.id)||!map.has(p.parent))throw Error('对象树循环或上级缺失');seen.add(p.id);p=map.get(p.parent);}if(p.id!=='project')throw Error('对象不属于工程');
      }
      if(doc.annotationVersion!==undefined&&doc.annotationVersion!==1)throw Error('标注版本不支持');
      UXAnnotationState.validate(this,map);
      if(doc.primaryGhost!==null&&map.get(doc.primaryGhost)?.type!=='ghost')throw Error('主参照无效');
      if(doc.view){for(const key of ['camera','target'])if(!Array.isArray(doc.view[key])||doc.view[key].length!==3||doc.view[key].some(v=>!Number.isFinite(v)))throw Error('相机记录无效');
        if(!Array.isArray(doc.view.selected)||doc.view.selected.some(id=>!map.has(id))||!Array.isArray(doc.view.open)||doc.view.open.some(id=>typeof id!=='string'))throw Error('选择／树状态无效');
        if(doc.view.preview!==undefined&&(!Array.isArray(doc.view.preview)||doc.view.preview.some(id=>!map.has(id))))throw Error('参考预览状态无效');
        if(doc.view.isolate!==undefined&&typeof doc.view.isolate!=='boolean')throw Error('隔离显示状态无效');
        if(doc.view.exposure!==undefined&&(!Number.isFinite(doc.view.exposure)||doc.view.exposure<=0))throw Error('屏幕曝光无效');
      }
      return true;
    }
  }
  window.UXModel={Model,Node,DEFAULTS,LOCAL,validParam};
})();

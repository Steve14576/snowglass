/* Z-up迁移专项：独立旧坐标矩阵基准、字形／网格局部不重排、旧工程不覆写。 */
(() => {
  'use strict';
  const T=THREE,C=UXCoordinates,assert=(ok,text)=>{if(!ok)throw Error(text);};
  const close=(a,b,text)=>assert(a.length===b.length&&a.every((v,i)=>Math.abs(v-b[i])<1e-7),text);
  const fresh=()=>new UXModel.Model(uxEditor.model.topo,uxEditor.model.provenance);
  const trs=(t,r,s=[1,1,1])=>new T.Matrix4().compose(new T.Vector3(...t),new T.Quaternion().setFromEuler(new T.Euler(...r,'XYZ')),new T.Vector3(...s));
  function fixture(){
    const m=fresh(),doc=m.snapshot(),nodes=new Map(doc.nodes.map(n=>[n.id,n])),bases=m.bases;
    delete doc.coordinateSystem;delete doc.localGeometryBasis;delete doc.annotationPolicy;
    const head=trs([1,2,3],[.2,-.1,.3],[1.1,.8,1.3]),layer=trs([.4,-.2,.8],[0,.1,0]),down=trs([-1,.5,2],[0,0,.05],[.9,1.1,1]),ghost=trs([2,-3,1],[.15,.2,.05],[1.2,.8,1.5]);
    nodes.get('lm_head').local=head.toArray();nodes.get('layer-16').local=layer.toArray();nodes.get('L16.down').local=down.toArray();nodes.get('ghost-1').local=ghost.toArray();
    nodes.get('global').values.labelDy=1.2;nodes.get('global').values.labelDz=-3;nodes.get('L16.down').overrides={labelDy:.4,gridY:9};
    const oldHead=head.clone().multiply(bases.get('lm_head').recipeMatrix),p=new T.Vector3(),q=new T.Quaternion();oldHead.decompose(p,q,new T.Vector3());
    const reference=new T.Matrix4().compose(p,q.normalize(),new T.Vector3(1,1,1)),gb=trs([-15,5,0],[0,0,.1]),gl=trs([.2,.3,.4],[.05,0,0]),lb=trs([0,1.5,0],[-Math.PI/2,0,0]),ll=trs([.2,-.1,.4],[0,.05,0]);
    const group=new UXModel.Node('label-group-old','labelGroup','旧标注组','annotations');group.local=gl.toArray();group.overrides={visible:true,labelFont:'Microsoft YaHei',labelSize:.7,labelOutput:true};
    group.data={base:gb.toArray(),follow:{sourceId:'lm_head',reference:reference.toArray()},recipe:{sourceId:'lm_head',axis:'x',mode:0,side:'-z',face:'+y',gap:1,tolerance:1e-6,scopeIds:['lm_head'],font:'Microsoft YaHei',height:.7}};
    const label=new UXModel.Node('label-old','label','旧文字坐标','label-group-old');label.local=ll.toArray();label.data={text:label.name,members:['lm_head'],base:lb.toArray()};
    doc.nodes.push(group,label);doc.seq=900;
    doc.view={camera:[25,18,55],target:[3,0,1],selected:['L16.down'],preview:['L16.down'],open:['project','annotations','label-group-old'],isolate:false,exposure:1};
    const metric=UXAnnotationMath.measure(label.data.text,group.overrides.labelFont),expected={
      lm_head:oldHead,
      'L16.down':layer.clone().multiply(down).multiply(bases.get('L16.down').recipeMatrix),
      'ghost-1':ghost.clone().multiply(new T.Matrix4().makeScale(...nodes.get('ghost-1').data.dims)),
      'label-old':gb.clone().multiply(gl).multiply(lb).multiply(ll).multiply(new T.Matrix4().makeScale(metric.width/metric.height*.7,.7,1))};
    return {doc,expected};
  }
  function run(){
    const cases=[],test=(name,fn)=>cases.push({name,result:fn()});
    test('default_axes_layout_and_numeric_transform',()=>{
      const m=fresh(),head=m.bounds(['lm_head']).getCenter(new T.Vector3()),tail=m.bounds(['embed']).getCenter(new T.Vector3()),vision=m.bounds(['vision']).getCenter(new T.Vector3());
      assert(head.z>tail.z&&vision.x>0,'默认塔不是Z向上／视觉塔不在右侧');assert(m.snapshot().coordinateSystem===C.SYSTEM,'工程没有坐标版本');
      const id='L16.down',before=m.bounds([id]).getCenter(new T.Vector3()),frame=m.objectFrame(id),q=new T.Quaternion();frame.decompose(new T.Vector3(),q,new T.Vector3());
      assert(q.angleTo(new T.Quaternion())<1e-7,'默认对象轴仍是原网格Y-up轴');
      m.setLocalTRS(id,{t:[0,1,2],r:[0,0,0],s:[1,1,1]});const after=m.bounds([id]).getCenter(new T.Vector3());close(after.clone().sub(before).toArray(),[0,1,2],'Y／Z数字没有实际作用于新世界轴');
      return {head:head.toArray(),tail:tail.toArray(),vision:vision.toArray(),world_size:m.bounds(['work']).getSize(new T.Vector3()).toArray()};
    });
    const f=fixture(),original=JSON.stringify(f.doc),m=fresh();
    test('legacy_nodes_labels_ghosts_and_sparse_offsets',()=>{
      const converted=C.prepare(f.doc);assert(JSON.stringify(f.doc)===original,'转换改写了旧文档');m.load(f.doc);
      for(const [id,old] of Object.entries(f.expected))close(m.world(id).toArray(),C.basis().multiply(old).toArray(),'旧对象视觉矩阵未保持 '+id);
      assert(C.OLD_LABEL_KEYS.every(k=>!Object.hasOwn(m.nodes.get('L16.down').overrides,k)&&!Object.hasOwn(m.nodes.get('global').values,k)),'旧标签字段仍在工程中');
      assert(m.nodes.get('label-old').data.text==='旧文字坐标'&&m.resolve('label-old','labelEnabled').value===true,'新标签内容或显示状态丢失');
      assert(m.resolve('L16.down','gridY').value===9&&m.resolve('global','gridZ').value===32,'迁移重排了源数据网格');
      const r=m.nodes.get('label-group-old').data.recipe;assert(r.axis==='x'&&r.mode===1&&r.side==='+y'&&r.face==='+z','旧标注模式或正负方向错译');
      close(converted.view.camera,[25,-55,18],'旧相机未转换');close(converted.view.target,[3,-1,0],'旧目标未转换');
      const saved=m.snapshot(),other=fresh();other.load(saved);assert(JSON.stringify(other.snapshot())===JSON.stringify(saved),'新坐标往返重复转换');
      const invalid=CurveMath.copy(saved);invalid.coordinateSystem='unknown';let rejected=false;try{other.load(invalid);}catch(e){rejected=true;}assert(rejected,'接受了未知坐标版本');
      return {matrix_preserved:true,old_label_fields_ignored:true,grid_unchanged:true,recipe:r,roundtrip:true};
    });
    test('legacy_screen_projection_with_grid_and_glyph_local_coordinates',()=>{
      const oldCamera=new T.PerspectiveCamera(42,uxEditor.scene.camera.aspect,.001,2000),newCamera=oldCamera.clone();oldCamera.position.fromArray(f.doc.view.camera);oldCamera.lookAt(new T.Vector3(...f.doc.view.target));oldCamera.updateMatrixWorld();
      newCamera.up.set(0,0,1);newCamera.position.fromArray(C.point(f.doc.view.camera));newCamera.lookAt(new T.Vector3(...C.point(f.doc.view.target)));newCamera.updateMatrixWorld();
      const piece=uxEditor.results.find(r=>r.id==='L16.down').pieces[0];let samples=0;
      for(const i of [0,1,31,piece.raw.length-1]){const local=UXData.position(piece,i),old=new T.Vector3(...local).applyMatrix4(f.expected['L16.down']).project(oldCamera),now=new T.Vector3(...local).applyMatrix4(m.world('L16.down')).project(newCamera);close(old.toArray(),now.toArray(),'源网格投影改变');samples++;}
      for(const local of [[0,0,0],[.4,-.3,0]]){const old=new T.Vector3(...local).applyMatrix4(f.expected['label-old']).project(oldCamera),now=new T.Vector3(...local).applyMatrix4(m.world('label-old')).project(newCamera);close(old.toArray(),now.toArray(),'文字平面重复旋转');samples++;}
      return {samples,pixel_projection_preserved:true};
    });
    test('legacy_follow_reference_and_ghost_inset',()=>{
      const label=m.world('label-old'),reference=UXAnnotationMath.pose(m,'lm_head');m.transform(['lm_head'],new T.Matrix4().makeTranslation(0,1,2));
      close(m.world('label-old').toArray(),UXAnnotationMath.pose(m,'lm_head').multiply(reference.invert()).multiply(label).toArray(),'旧跟随参考二次转换');
      const inset=UXChecks.inset(m,'ghost-1'),oldGhost=f.expected['ghost-1'].clone().multiply(new T.Matrix4().makeScale(1/25,1/80,1/25)).invert(),a=oldGhost.elements;
      const expected=[0,1,2].map((i)=>[25,80,25][i]-5*new T.Vector3(a[i],a[i+4],a[i+8]).length());close(inset.dims,expected,'毛坯安全内偏移改变');
      return {follow_preserved:true,inset_preserved:true};
    });
    return {cases,legacy:f.doc,expectedCamera:C.point(f.doc.view.camera),expectedTarget:C.point(f.doc.view.target)};
  }
  window.CoordinateTests={run};
})();

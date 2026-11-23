/* 标签组双中心专项。矩阵与中心在世界Z-up中比较；不请求权重。 */
(() => {
  'use strict';
  const T=THREE,S=UXAnnotationState,assert=(ok,text)=>{if(!ok)throw Error(text);};
  const close=(a,b,text)=>assert(a.length===b.length&&a.every((v,i)=>Math.abs(v-b[i])<1e-7),text);
  const fresh=()=>new UXModel.Model(uxEditor.model.topo,uxEditor.model.provenance),pos=m=>new T.Vector3().setFromMatrixPosition(m);
  function fixture(){const model=fresh(),group=model.createLabels(model.planLabels('L16.down',{axis:'z',mode:2}));return {model,group,labels:model.children(group).map(n=>n.id)};}
  function run(){
    const cases=[],test=(name,fn)=>cases.push({name,result:fn()});
    test('group_and_individual_rotation_centres',()=>{
      const a=fixture(),b=fresh();b.load(a.model.snapshot());b.setLabelCenter(a.group,'individual');
      const center=a.model.bounds([a.group]).getCenter(new T.Vector3()),delta=new T.Matrix4().makeTranslation(...center.toArray()).multiply(new T.Matrix4().makeRotationX(.4)).multiply(new T.Matrix4().makeTranslation(...center.clone().negate().toArray()));
      const old=a.labels.map(id=>a.model.world(id));a.model.transform([a.group],delta,'rotate');b.transform([a.group],delta,'rotate');let moved=false;
      a.labels.forEach((id,i)=>{const expected=delta.clone().multiply(old[i]);close(a.model.world(id).toArray(),expected.toArray(),'整组旋转错误');moved ||= pos(expected).distanceTo(pos(old[i]))>.01;
        expected.setPosition(pos(old[i]));close(b.world(id).toArray(),expected.toArray(),'各自旋转移动中心或旋转角错误');});
      assert(moved,'整组模式没有改变排布');const saved=b.snapshot();b.setLabelCenter(a.group,'group');assert(JSON.stringify(b.snapshot().nodes.map(n=>n.local))===JSON.stringify(saved.nodes.map(n=>n.local)),'切换模式跳变');
      return {group_moves:true,individual_centres_fixed:true,switch_no_jump:true};
    });
    test('individual_scale_all_axes_and_translation',()=>{
      for(const scale of [[2,1,1],[1,1,2],[-1,.75,2.25]]){
        const f=fixture(),m=f.model;m.setLabelCenter(f.group,'individual');const old=f.labels.map(id=>m.world(id)),center=m.bounds([f.group]).getCenter(new T.Vector3());
        const d=new T.Matrix4().makeTranslation(...center.toArray()).multiply(new T.Matrix4().makeScale(...scale)).multiply(new T.Matrix4().makeTranslation(...center.clone().negate().toArray()));
        m.transform([f.group],d,'scale');f.labels.forEach((id,i)=>close(m.world(id).toArray(),d.clone().multiply(old[i]).setPosition(pos(old[i])).toArray(),'各自缩放改变中心或尺寸错误'));m.validate(m.snapshot());
      }
      const a=fixture(),b=fresh();b.load(a.model.snapshot());b.setLabelCenter(a.group,'individual');const d=new T.Matrix4().makeTranslation(1,2,3);
      a.model.transform([a.group],d,'translate');b.transform([a.group],d,'translate');a.labels.forEach(id=>close(a.model.world(id).toArray(),b.world(id).toArray(),'平移被中心模式改变'));
      return {scale_axes:true,negative_nonuniform:true,translation_unchanged:true};
    });
    test('nested_sources_individual_transform_and_follow',()=>{
      const m=fresh(),a=m.createLabels(m.planLabels('embed')),b=m.createLabels(m.planLabels('lm_head')),la=m.children(a)[0].id,lb=m.children(b)[0].id;
      m.setLocalTRS('embed',{t:[1,0,0],r:[0,0,.3],s:[1,1,1]});m.setLocalTRS('lm_head',{t:[-1,0,0],r:[0,0,-.4],s:[1,1,1]});
      const parent=m.group([a,b]);m.setLabelCenter(parent,'individual');const old=[m.world(la),m.world(lb)],d=new T.Matrix4().makeRotationY(.25).multiply(new T.Matrix4().makeScale(1.2,.8,1.4));
      m.transform([parent],d,'scale');[la,lb].forEach((id,i)=>close(m.world(id).toArray(),d.clone().multiply(old[i]).setPosition(pos(old[i])).toArray(),'嵌套各自中心没有统一世界变换'));
      const before=m.world(la),other=m.world(lb).toArray(),reference=UXAnnotationMath.pose(m,'embed');m.transform(['embed'],new T.Matrix4().makeTranslation(2,1,0));
      close(m.world(la).toArray(),UXAnnotationMath.pose(m,'embed').multiply(reference.invert()).multiply(before).toArray(),'各自中心丢失源跟随');close(m.world(lb).toArray(),other,'一个来源带走另一标签');return {nested:true,source_refs_preserved:true};
    });
    test('numeric_rotate_scale_move_undo_and_save',()=>{
      const f=fixture(),m=f.model;m.setLabelCenter(f.group,'individual');const old=f.labels.map(id=>m.world(id)),before=m.snapshot();
      m.setLocalTRS(f.group,{t:[0,0,0],r:[.2,.1,0],s:[1,1,1.5]});f.labels.forEach((id,i)=>close(pos(m.world(id)).toArray(),pos(old[i]).toArray(),'数字旋缩移动了标签中心'));
      const after=m.snapshot();m.undo();assert(JSON.stringify(m.snapshot())===JSON.stringify(before),'旋缩撤销不完整');m.redo();assert(JSON.stringify(m.snapshot())===JSON.stringify(after),'旋缩重做不完整');
      const locations=f.labels.map(id=>pos(m.world(id))),trs=m.localTRS(f.group);trs.t=[1,2,3];m.setLocalTRS(f.group,trs);
      f.labels.forEach((id,i)=>close(pos(m.world(id)).toArray(),locations[i].clone().add(new T.Vector3(1,2,3)).toArray(),'数字平移没有统一作用'));
      const current=f.labels.map(id=>pos(m.world(id))),next=m.localTRS(f.group);next.t[0]+=1;next.r[0]+=.1;next.s[2]*=.8;m.setLocalTRS(f.group,next);
      f.labels.forEach((id,i)=>close(pos(m.world(id)).toArray(),current[i].clone().add(new T.Vector3(1,0,0)).toArray(),'同时旋缩和平移的显式位移错误'));
      const saved=m.snapshot(),restored=fresh();restored.load(saved);assert(S.centerMode(restored,f.group)==='individual','保存丢中心设置');f.labels.forEach(id=>close(restored.world(id).toArray(),m.world(id).toArray(),'保存丢子标签补偿'));
      const legacy=CurveMath.copy(saved);delete legacy.nodes.find(n=>n.id===f.group).data.transformCenter;restored.load(legacy);assert(S.centerMode(restored,f.group)==='group','旧工程默认不是整组');
      const invalid=CurveMath.copy(saved);invalid.nodes.find(n=>n.id===f.group).data.transformCenter='wrong';let rejected=false;try{restored.load(invalid);}catch(e){rejected=true;}assert(rejected,'接受了非法中心模式');
      return {numeric_centres_fixed:true,explicit_translation:true,undo_redo:true,save_restore:true,legacy_group:true};
    });
    return cases;
  }
  window.PivotTests={run};
})();

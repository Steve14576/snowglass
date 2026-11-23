/* 标注专项：合成几何、现有拓扑、变换与保存。无权重请求、不截图。 */
(() => {
  'use strict';
  const T=THREE,A=UXAnnotationMath,S=UXAnnotationState,results=[];
  const assert=(ok,text)=>{if(!ok)throw Error(text);},close=(a,b,text)=>assert(a.length===b.length&&a.every((v,i)=>Math.abs(v-b[i])<1e-7),text);
  const fresh=()=>new UXModel.Model(uxEditor.model.topo,uxEditor.model.provenance);
  const check=(name,fn)=>{const result=fn();results.push({name,result});};
  function synthetic(){
    const records=[];for(let x=0;x<3;x++)for(let y=0;y<4;y++)for(let z=0;z<2;z++)records.push({id:`b-${x}-${y}-${z}`,center:new T.Vector3(x*5,y*5,z*5)});
    const nodes=new Map(records.map(r=>[r.id,{id:r.id,type:'block',sourceId:r.id,name:'测试块'}])),byId=new Map(records.map(r=>[r.id,r]));
    const model={nodes,topo:{blocks:records.map(r=>({id:r.id,layer:r.center.z/5})),model:{layer_types:Array(4).fill('full_attention')}},
      world:id=>new T.Matrix4().makeTranslation(...byId.get(id).center.toArray()),resolve:(id,key)=>({value:{labelFont:'Microsoft YaHei',labelSize:.7,labelText:''}[key]}),
      bounds:ids=>{const box=new T.Box3();ids.forEach(id=>{const p=byId.get(id).center;box.expandByPoint(p.clone().addScalar(-.5));box.expandByPoint(p.clone().addScalar(.5));});return box;}};
    return {model,records};
  }
  function run(){
    results.length=0;
    check('nine_modes_exact_members_and_external_placement',()=>{
      const {model,records}=synthetic(),id='b-1-2-0',counts={x:3,y:4,z:2},cases=[];
      for(const axis of ['x','y','z'])for(let mode=0;mode<3;mode++){
        const p=A.generate(model,id,{axis,mode}),fixed=A.MODES[axis][mode].fixed,chosen=records.find(r=>r.id===id);
        const expected=records.filter(r=>!fixed||Math.abs(r.center[fixed]-chosen.center[fixed])<=A.EPS).map(r=>r.id).sort(),actual=p.labels.flatMap(l=>l.members).sort();
        assert(p.labels.length===counts[axis],'九模式数量错误');assert(new Set(actual).size===actual.length,'重复归属');close(actual.map(v=>expected.indexOf(v)),expected.map((v,i)=>i),'成员不一致');
        const box=model.bounds(records.map(r=>r.id));
        p.labels.forEach(l=>{const m=new T.Matrix4().fromArray(l.matrix),position=new T.Vector3().setFromMatrixPosition(m),normal=new T.Vector3(0,0,1).transformDirection(m.clone().multiply(UXCoordinates.basis()));
          close(normal.toArray(),axis==='z'?[0,-1,0]:[0,0,1],'默认固定朝向错误');
          const side=p.side[1],half=side==='x'?l.width/2:side===(p.face==='+z'?'y':'z')?l.height/2:0;
          assert(p.side[0]==='-'?position[side]+half<=box.min[side]-p.gap+1e-8:position[side]-half>=box.max[side]+p.gap-1e-8,'文字不是整矩形在塔外');
        });cases.push({axis,mode,labels:p.labels.length,members:actual.length});
      }return cases;
    });
    check('coordinate_tolerance_boundary',()=>{
      const records=[0,.5e-6,2e-6].map((x,i)=>({id:String(i),center:{x,y:0,z:0}}));
      const groups=A.aggregate(records,'x');assert(groups.length===2&&groups[0].members.length===2,'容差错误聚合');
      assert(A.aggregate(records,'x','x',0).flatMap(g=>g.members).length===2,'平面容差失效');return {tolerance:A.EPS};
    });
    check('real_topology_nine_modes_and_independent_ends',()=>{
      const m=fresh(),before=m.snapshot(),matrices=new Map(m.topo.blocks.map(b=>[b.id,m.world(b.id).toArray()]));
      const counts=[];for(const [id,expected] of [['L16.down',[8,1,32]],['V13.attn',[4,1,27]]])for(const axis of ['x','y','z'])for(let mode=0;mode<3;mode++){
        const p=m.planLabels(id,{axis,mode});assert(p.labels.length===expected[['x','y','z'].indexOf(axis)],'真实拓扑数量不符 '+id+axis+mode);counts.push(p.labels.length);
      }
      for(const [id,side] of [['embed','-z'],['lm_head','+z'],['final_norm','-x'],['V.patch','-z'],['V.merger','+z'],['mtp','+x']]){const p=m.planLabels(id);assert(p.labels.length===1&&p.side===side&&p.face==='-y','独立块默认错误 '+id);}
      assert(JSON.stringify(before)===JSON.stringify(m.snapshot()),'浏览计划改了工程');
      const parents=m.topo.blocks.map(b=>m.nodes.get(b.id).parent),plan=m.planLabels('L16.down',{axis:'z',mode:2}),group=m.createLabels(plan);
      assert(m.children(group).length===32&&m.nodes.get(group).parent==='annotations','没有独立节点');m.validate(m.snapshot());
      m.topo.blocks.forEach((b,i)=>{assert(m.nodes.get(b.id).parent===parents[i],'迁移了源块');close(m.world(b.id).toArray(),matrices.get(b.id),'生成移动源几何');});
      const p0=m.planLabels('L16.down',{axis:'x',mode:2});m.group(['L16.down','L16.up']);const p1=m.planLabels('L16.down',{axis:'x',mode:2});assert(p0.labels.length===p1.labels.length&&p1.scopeIds.length===256,'操作组改变了源塔范围');return {mode_counts:counts,initial_nodes:before.nodes.length,created:32};
    });
    check('follow_source_preserves_manual_edits_and_size',()=>{
      const m=fresh(),p=m.planLabels('lm_head'),group=m.createLabels(p),label=m.children(group)[0].id;
      m.transform([label],new T.Matrix4().makeTranslation(.2,.3,.4));m.transform([group],new T.Matrix4().makeTranslation(.5,.2,.1));
      const initial=m.world(label),ref=A.pose(m,'lm_head');m.setLocalTRS('lm_head',{t:[1,2,3],r:[0,0,.3],s:[1,1,1]});
      close(m.world(label).toArray(),A.pose(m,'lm_head').multiply(ref.invert()).multiply(initial).toArray(),'源跟随丢失手动调整');
      const size=[0,1].map(i=>new T.Vector3().setFromMatrixColumn(m.world(label),i).length());
      m.setLocalTRS('lm_head',{t:[1,2,3],r:[0,0,.3],s:[2,3,1]});close([0,1].map(i=>new T.Vector3().setFromMatrixColumn(m.world(label),i).length()),size,'源缩放缩了字');
      const w=m.world(label).toArray();m.remove('lm_head');close(m.world(label).toArray(),w,'删除源导致标签跳变');assert(m.nodes.get(group).data.follow.lostSource==='lm_head','未记录源缺失');m.validate(m.snapshot());
      m.undo();assert(m.nodes.get(group).data.follow.sourceId==='lm_head','撤销没有恢复绑定');close(m.world(label).toArray(),w,'恢复绑定位置改变');return {follow:true,source_scale_excluded:true,lost_source_preserved:true};
    });
    check('nested_groups_distinct_sources_and_sparse_styles',()=>{
      const m=fresh(),a=m.createLabels(m.planLabels('embed')),b=m.createLabels(m.planLabels('lm_head')),la=m.children(a)[0].id,lb=m.children(b)[0].id;
      const wa=m.world(la).toArray(),wb=m.world(lb).toArray(),parent=m.group([a,b]);close(m.world(la).toArray(),wa,'标签组迁移跳变');close(m.world(lb).toArray(),wb,'第二组跳变');
      m.transform([parent],new T.Matrix4().makeTranslation(2,3,4));const stable=m.world(lb).toArray(),old=m.world(la),ref=A.pose(m,'embed');
      m.transform(['embed'],new T.Matrix4().makeTranslation(1,0,0));close(m.world(lb).toArray(),stable,'一个源搬走另一个标签组');close(m.world(la).toArray(),A.pose(m,'embed').multiply(ref.invert()).multiply(old).toArray(),'再分组后绑定失效');
      m.inherit(a,'labelSize');m.inherit(b,'labelSize');m.set(parent,'labelSize',.9);assert(m.resolve(la,'labelSize').value===.9,'样式没继承');m.lock(la,'labelSize');m.set(parent,'labelSize',1.1);assert(m.resolve(la,'labelSize').value===.9&&m.resolve(lb,'labelSize').value===1.1,'逐属性覆盖失效');
      const text=m.nodes.get(la).data.text;m.rename(parent,'操作标签组');assert(m.nodes.get(la).data.text===text,'组名改了成员文字');
      const fa=m.chain(la).toArray();m.ungroup(a,true);close(m.chain(la).toArray(),fa,'解组文字位置改变');assert(S.effective(m,la).sourceId==='embed','解组丢跟随引用');m.validate(m.snapshot());return {independent_sources:true,ungroup_follow:true};
    });
    check('combined_parent_after_distinct_source_rotations',()=>{
      const m=fresh(),a=m.createLabels(m.planLabels('embed')),b=m.createLabels(m.planLabels('lm_head')),la=m.children(a)[0].id,lb=m.children(b)[0].id;
      m.setLocalTRS('embed',{t:[1,0,0],r:[0,0,.3],s:[1,1,1]});m.setLocalTRS('lm_head',{t:[-1,0,0],r:[0,0,-.4],s:[1,1,1]});
      const parent=m.group([a,b]),old=[m.chain(la),m.chain(lb)],d=new T.Matrix4().makeRotationZ(.2);d.setPosition(2,1,0);
      m.transform([parent],d);[la,lb].forEach((id,i)=>close(m.chain(id).toArray(),d.clone().multiply(old[i]).toArray(),'已旋转源的共同父级变换没有一致作用于子标签'));
      const frame=m.chain(parent),before=[m.chain(la),m.chain(lb)];m.setLocalTRS(parent,{t:[.5,.3,0],r:[0,0,.5],s:[1,1,1]});const delta=m.chain(parent).multiply(frame.invert());
      [la,lb].forEach((id,i)=>close(m.chain(id).toArray(),delta.clone().multiply(before[i]).toArray(),'父级数字变换与gumball语义不同'));
      return {distinct_rotated_sources:true,parent_numeric_and_gumball_consistent:true};
    });
    check('migration_export_and_invalid_annotations',()=>{
      const m=fresh(),legacy=m.snapshot();legacy.nodes=legacy.nodes.filter(n=>n.id!=='annotations');delete legacy.annotationVersion;m.load(legacy);assert(m.children('annotations').length===0,'旧工程未补空根');
      const group=m.createLabels(m.planLabels('lm_head')),label=m.children(group)[0].id,saved=m.snapshot(),other=fresh();other.load(saved);assert(JSON.stringify(other.snapshot())===JSON.stringify(saved),'新工程往返不一致');
      const n=other.annotations([group])[0];assert(n.text&&n.follow.sourceId==='lm_head'&&n.matrix_mm.length===16,'导出字段缺失');close(n.front_world,[0,-1,0],'导出方向错误');other.set(label,'labelOutput',false);assert(other.annotations([group])[0].output===false,'输出开关失效');
      for(const modify of [d=>d.nodes.find(n=>n.id===group).parent=label,d=>d.nodes.find(n=>n.id===group).data.follow.sourceId=label,d=>d.nodes.find(n=>n.id===label).data.members=['fake-source'],d=>d.nodes.find(n=>n.id==='lm_head').parent=group]){
        const bad=CurveMath.copy(saved);modify(bad);let rejected=false;try{other.load(bad);}catch(e){rejected=true;}assert(rejected,'接受非法标注引用');
      }
      let rejected=false;try{m.commit(()=>m.move('lm_head',group));}catch(e){rejected=true;}assert(rejected,'允许源块跨入标注');
      rejected=false;try{m.createLabels(m.planLabels('lm_head'));}catch(e){rejected=true;}assert(rejected,'重复生成没有提示');
      const count=m.nodes.size;m.remove(group);assert(m.nodes.has('lm_head'),'删除标签删了源块');m.undo();assert(m.nodes.size===count,'生成／删除撤销失效');return {legacy:true,roundtrip:true,invalid_rejected:true};
    });
    return results.slice();
  }
  window.AnnotationTests={run};
})();

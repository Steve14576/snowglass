/* 字号与整组边线对齐：不拉字距，不重建权重数据。 */
(() => {
  'use strict';
  const T=THREE,A=UXAnnotationMath,assert=(ok,text)=>{if(!ok)throw Error(text);},near=(a,b,text)=>assert(Math.abs(a-b)<1e-7,text);
  const fresh=()=>new UXModel.Model(uxEditor.model.topo,uxEditor.model.provenance);
  function fixture(){const m=fresh(),g=m.createLabels(m.planLabels('L16.down')),ids=m.children(g).map(n=>n.id);return {m,g,ids};}
  function span(m,g,id){const inv=m.chain(g).invert(),w=m.world(id),xs=[];for(const x of [-.5,.5])for(const y of [-.5,.5])xs.push(new T.Vector3(x,y,0).applyMatrix4(w).applyMatrix4(inv).x);return {left:Math.min(...xs),right:Math.max(...xs),center:(Math.min(...xs)+Math.max(...xs))/2};}
  function aligned(m,g,mode){const rows=m.leaves([g]).map(id=>span(m,g,id));rows.forEach(r=>near(r[mode],m.nodes.get(g).data.alignmentGuide,'组内文字没有贴齐 '+mode));}
  function run(){
    const cases=[],test=(name,fn)=>cases.push({name,result:fn()});
    test('same_font_same_size_uses_one_scale_not_per_text_height',()=>{
      const {m,g,ids}=fixture();m.setLabelText(ids[0],'H');m.setLabelText(ids[1],'Hg');m.setLabelText(ids[2],'国字');
      const sizes=ids.map(id=>A.shape(m,m.nodes.get(id))),nominal=m.resolve(g,'labelSize').value;
      sizes.forEach(size=>{near(size.factor,sizes[0].factor,'相同字号却逐条按墨迹变换');near(size.nominalHeight,nominal,'组内默认字号不统一');});
      assert(sizes[0].metric.height!==sizes[1].metric.height,'测试未覆盖下伸字母');
      near(sizes[0].referenceHeight,64,'字号没有使用统一64px字体标尺');
      const trs=m.localTRS(ids[0]);trs.s=[2,1,1];m.setLocalTRS(ids[0],trs);m.set(ids[0],'labelSize',.45);m.set(g,'labelSize',1.1);
      near(m.resolve(ids[0],'labelSize').value,.45,'清掉了单标签字号覆盖');near(m.localTRS(ids[0]).s[0],2,'清掉了单标签手动缩放');near(m.resolve(ids[1],'labelSize').value,1.1,'其他成员没继承新字号');
      return {uniform_factor:sizes[0].factor,reference_height:sizes[0].referenceHeight,nominal_height:nominal,individual_override_preserved:true};
    });
    test('left_right_center_move_only_and_keep_other_coordinates',()=>{
      for(const mode of ['left','right','center']){
        const {m,g,ids}=fixture();m.setLabelText(ids[0],'短');m.setLabelText(ids[1],'长文字对齐');
        const before=ids.map(id=>({matrix:m.world(id).toArray(),position:new T.Vector3().setFromMatrixPosition(m.world(id))})),guideSpan=ids.map(id=>span(m,g,id));
        const expected=mode==='left'?Math.min(...guideSpan.map(r=>r.left)):mode==='right'?Math.max(...guideSpan.map(r=>r.right)):(Math.min(...guideSpan.map(r=>r.left))+Math.max(...guideSpan.map(r=>r.right)))/2;
        const history=m.history.length;m.setLabelAlignment(g,mode);aligned(m,g,mode);near(m.nodes.get(g).data.alignmentGuide,expected,'没使用整组共同边线');assert(m.history.length===history+1,'一次对齐不是一次撤销');
        ids.forEach((id,i)=>{const w=m.world(id),p=new T.Vector3().setFromMatrixPosition(w);for(const k of [0,1,2,4,5,6,8,9,10])near(w.elements[k],before[i].matrix[k],'对齐改变字宽字距或朝向');near(p.y,before[i].position.y,'对齐改了前后位置');near(p.z,before[i].position.z,'对齐改了层位');});
        const saved=m.snapshot();m.undo();ids.forEach((id,i)=>m.world(id).elements.forEach((v,k)=>near(v,before[i].matrix[k],'对齐撤销位置错误')));m.redo();assert(JSON.stringify(saved)===JSON.stringify(m.snapshot()),'对齐重做错误');
      }return {alignments:3,no_stretch_or_spacing_change:true,undo_redo:true};
    });
    test('edited_text_font_and_size_keep_selected_guide',()=>{
      const {m,g,ids}=fixture();m.setLabelAlignment(g,'right');const guide=m.nodes.get(g).data.alignmentGuide;
      m.setLabelText(ids[0],'这是编辑后更长的文字');aligned(m,g,'right');near(m.nodes.get(g).data.alignmentGuide,guide,'改文字移动共同参考线');
      m.set(g,'labelSize',1.2);aligned(m,g,'right');near(m.nodes.get(g).data.alignmentGuide,guide,'改字号移动参考线');
      m.set(ids[1],'labelSize',.6);aligned(m,g,'right');m.inherit(ids[1],'labelSize');aligned(m,g,'right');
      m.set(g,'labelFont','Arial');aligned(m,g,'right');m.inherit(g,'labelFont');aligned(m,g,'right');
      m.transform([ids[0]],new T.Matrix4().makeTranslation(.2,.1,0));near(span(m,g,ids[0]).right,guide+.2,'不能单独微调标签');
      return {text_font_size_reflow:true,guide_fixed:true,single_manual_edit:true};
    });
    test('alignment_in_rotated_scaled_group_with_individual_pivot',()=>{
      const {m,g,ids}=fixture();m.setLocalTRS(g,{t:[1,2,3],r:[.2,.3,.1],s:[1.2,.8,1.4]});m.setLabelAlignment(g,'left');aligned(m,g,'left');
      const old=ids.map(id=>new T.Vector3().setFromMatrixPosition(m.world(id)));m.setLabelCenter(g,'individual');m.transform([g],new T.Matrix4().makeRotationY(.3),'rotate');
      ids.forEach((id,i)=>{const p=new T.Vector3().setFromMatrixPosition(m.world(id));near(p.distanceTo(old[i]),0,'对齐破坏各自旋转中心');});
      m.setLabelAlignment(g,'center');aligned(m,g,'center');m.validate(m.snapshot());
      const before=ids.map(id=>m.world(id)),ref=A.pose(m,'L16.down');m.transform(['L16.down'],new T.Matrix4().makeTranslation(2,1,0));const delta=A.pose(m,'L16.down').multiply(ref.invert());
      ids.forEach((id,i)=>{const expected=delta.clone().multiply(before[i]);m.world(id).elements.forEach((v,k)=>near(v,expected.elements[k],'对齐破坏源跟随'));});return {local_group_axis:true,individual_pivot:true,follow_preserved:true};
    });
    test('old_labels_keep_size_and_new_layout_roundtrips',()=>{
      const {m,g,ids}=fixture(),old=m.snapshot();old.nodes.filter(n=>n.type==='label').forEach(n=>delete n.data.fontSizing);
      const legacy=fresh();legacy.load(old);const initial=legacy.snapshot(),size=A.shape(legacy,legacy.nodes.get(ids[0]));near(size.height,legacy.resolve(ids[0],'labelSize').value,'旧标签不再保持旧墨迹尺度');
      assert(!legacy.nodes.get(g).data.textAlign,'旧组被强制重新排版');assert(JSON.stringify(initial)===JSON.stringify(legacy.snapshot()),'读取旧工程产生额外操作');
      const position=legacy.world(ids[0]).toArray();legacy.lock(g,'labelSize');assert(legacy.world(ids[0]).elements.every((v,i)=>Math.abs(v-position[i])<1e-7),'只锁同值却改了旧标签尺寸');assert(legacy.nodes.get(ids[0]).data.fontSizing===undefined,'锁定误升级旧字号口径');
      legacy.set(g,'labelSize',.8);legacy.setLabelAlignment(g,'right');aligned(legacy,g,'right');assert(ids.every(id=>legacy.nodes.get(id).data.fontSizing===A.FONT_SIZING),'改组字号没有统一标尺');
      const saved=legacy.snapshot(),other=fresh();other.load(saved);assert(JSON.stringify(saved)===JSON.stringify(other.snapshot()),'对齐字段保存往返不一致');aligned(other,g,'right');
      const exported=other.annotations([g]);assert(exported.every(r=>r.text_alignment[0].mode==='right'&&r.font_sizing===A.FONT_SIZING),'导出缺对齐／字号口径');
      for(const bad of ['justify','wrong']){const invalid=CurveMath.copy(saved);invalid.nodes.find(n=>n.id===g).data.textAlign=bad;let rejected=false;try{other.load(invalid);}catch(e){rejected=true;}assert(rejected,'接受了两端撑开或非法对齐');}
      return {legacy_preserved:true,uniform_on_size_edit:true,roundtrip:true,no_justify:true};
    });
    return cases;
  }
  window.TextLayoutTests={run,span};
})();

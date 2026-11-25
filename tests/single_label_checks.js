/* 单一标注系统：忽略旧标签字段，不迁移文字；现有独立对象及位姿保留。 */
(() => {
  'use strict';
  const C=UXCoordinates,assert=(ok,text)=>{if(!ok)throw Error(text);},fresh=()=>new UXModel.Model(uxEditor.model.topo,uxEditor.model.provenance);
  function clean(doc){return doc.nodes.every(n=>[n.overrides,n.values].every(v=>!v||C.OLD_LABEL_KEYS.every(k=>!Object.hasOwn(v,k))));}
  function run(){
    const cases=[],check=(name,fn)=>cases.push({name,result:fn()});
    check('ignore_legacy_labels_without_generating_objects',()=>{
      const m=fresh(),old=m.snapshot();delete old.annotationPolicy;
      old.nodes.find(n=>n.id==='global').values.labels=true;old.nodes.find(n=>n.id==='global').values.labelText='不要迁移的全局名字';
      old.nodes.find(n=>n.id==='L16.down').overrides={labelText:'旧块文字',labelOutput:true,labelDx:'旧偏移任意内容',labelDy:30,labelDz:20,frameT:.1};
      const before=JSON.stringify(old),world=m.world('L16.down').toArray(),source=m.nodes.get('L16.down').name;m.load(old);
      assert(JSON.stringify(old)===before,'清理覆写了旧文件内容');assert(clean(m.snapshot()),'旧标签字段没有清掉');assert(m.leaves(['annotations']).length===0,'把旧全局开关自动展开成新标签');
      assert(m.world('L16.down').toArray().every((v,i)=>Math.abs(v-world[i])<1e-8)&&m.nodes.get('L16.down').name===source&&m.resolve('L16.down','frameT').value===.1,'清理改变了源身份／几何／非标签参数');
      const p=m.planLabels('lm_head');assert(p.labels[0].text==='LM Head','新生成仍借用旧自定义文字');
      for(const key of C.OLD_LABEL_KEYS){let refused=false;try{m.set('global',key,true);}catch(e){refused=true;}assert(refused,'旧标签入口仍可操作 '+key);}
      return {legacy_discarded:true,no_auto_generation:true,source_unchanged:true};
    });
    check('preserve_existing_new_labels_use_display_as_enabled',()=>{
      for(const visible of [false,true])for(const output of [false,true]){
        const m=fresh(),g=m.createLabels(m.planLabels('lm_head')),id=m.children(g)[0].id;m.setLabelText(id,'已经编辑好的新版文字');m.setLabelCenter(g,'individual');m.transform([id],new THREE.Matrix4().makeTranslation(.3,.2,.1));
        const doc=m.snapshot(),before=m.world(id).toArray();delete doc.annotationPolicy;
        const group=doc.nodes.find(n=>n.id===g);delete group.overrides.labelEnabled;group.overrides.visible=visible;group.overrides.labelOutput=output;
        doc.nodes.find(n=>n.id==='global').values.labelText='丢弃旧文字';const original=JSON.stringify(doc);m.load(doc);
        assert(JSON.stringify(doc)===original&&clean(m.snapshot()),'旧工程被覆写或保留了旧字段');assert(m.nodes.get(id).data.text==='已经编辑好的新版文字'&&UXAnnotationState.centerMode(m,g)==='individual','丢失新版内容或双中心');
        assert(m.resolve(id,'labelEnabled').value===visible&&m.annotations([id])[0].output===visible,'没有按原显示状态合并启用');
        assert(m.world(id).toArray().every((v,i)=>Math.abs(v-before[i])<1e-8),'清理移动了新版标签');
        const saved=m.snapshot(),again=fresh();again.load(saved);assert(JSON.stringify(again.snapshot())===JSON.stringify(saved),'单一策略往返不一致');
      }
      return {display_output_combinations:4,display_wins:true,new_text_transform_and_follow_preserved:true};
    });
    check('enabled_inheritance_and_locked_member',()=>{
      const m=fresh(),g=m.createLabels(m.planLabels('L16.down')),ids=m.children(g).map(n=>n.id);m.lock(ids[0],'labelEnabled');m.set(g,'labelEnabled',false);
      assert(m.resolve(ids[0],'labelEnabled').value&&ids.slice(1).every(id=>!m.resolve(id,'labelEnabled').value),'逐项锁定／继承改变');
      assert(m.annotations([g]).every(a=>a.enabled===a.output),'定义有显示与输出不一致');
      m.inherit(ids[0],'labelEnabled');assert(!m.resolve(ids[0],'labelEnabled').value,'恢复继承失败');m.set(g,'labelEnabled',true);assert(ids.every(id=>m.resolve(id,'labelEnabled').value),'恢复组启用未传递');
      const doc=m.snapshot();doc.nodes.find(n=>n.id===g).overrides.labelEnabled='false';let rejected=false;try{m.load(doc);}catch(e){rejected=true;}assert(rejected,'非布尔启用被接受');
      return {sparse_override_retained:true,invalid_rejected:true};
    });
    const model=fresh(),group=model.createLabels(model.planLabels('L16.down')),ids=model.children(group).map(n=>n.id);model.setLabelText(ids[0],'保留的新标签');model.setLabelCenter(group,'individual');
    const legacy=model.snapshot();delete legacy.annotationPolicy;
    const root=legacy.nodes.find(n=>n.id==='global');root.values.labels=true;root.values.labelText='应丢弃的旧文字';root.values.labelOutput=true;
    const g=legacy.nodes.find(n=>n.id===group);delete g.overrides.labelEnabled;g.overrides.visible=true;g.overrides.labelOutput=false;
    const child=legacy.nodes.find(n=>n.id===ids[1]);child.overrides.visible=false;child.overrides.labelOutput=true;
    return {cases,legacy,group,ids};
  }
  window.SingleLabelTests={run};
})();

/* 独立标注节点：操作父级唯一，源块跟随是独立引用，不迁移模型身份。 */
(() => {
  'use strict';
  const TYPES=['annotationRoot','labelGroup','label'],STYLE=['labelEnabled','labelFont','labelSize','labelDepth','labelGray'],I=()=>new THREE.Matrix4(),mat=a=>new THREE.Matrix4().fromArray(a),copy=CurveMath.copy;
  const is=n=>!!n&&TYPES.includes(n.type);
  function ensureRoot(model){if(!model.nodes.has('annotations'))model.nodes.set('annotations',new UXModel.Node('annotations','annotationRoot','标注','project'));}
  function effective(model,id){let n=model.nodes.get(id);while(is(n)){if(n.data?.follow)return n.data.follow;n=model.nodes.get(n.parent);}return null;}
  function follow(model,id){
    const f=effective(model,id);if(!f)return I();if(f.frozen)return mat(f.frozen);
    return UXAnnotationMath.pose(model,f.sourceId).multiply(mat(f.reference).invert());
  }
  function beforeLocal(model,id){
    const n=model.nodes.get(id);if(n.type==='annotationRoot')return I();
    return follow(model,id).multiply(follow(model,n.parent).invert()).multiply(model.chain(n.parent)).multiply(mat(n.data.base));
  }
  function frame(model,id){return beforeLocal(model,id).multiply(mat(model.nodes.get(id).local));}
  function world(model,id){
    const n=model.nodes.get(id),result=frame(model,id);if(n.type==='label'){const size=UXAnnotationMath.shape(model,n);result.multiply(UXCoordinates.basis()).multiply(I().makeScale(size.width,size.height,1));}return result;
  }
  function setFrame(model,id,w){model.nodes.get(id).local=beforeLocal(model,id).invert().multiply(w).toArray();}
  function alignRows(model,id,reset=false){
    const group=model.nodes.get(id);if(group?.type!=='labelGroup'||!group.data.textAlign)return;
    const groupFrame=frame(model,id),inverse=groupFrame.clone().invert(),records=model.leaves([id]).filter(child=>model.nodes.get(child).type==='label').map(child=>{
      const w=world(model,child),box=new THREE.Box3();for(const x of [-.5,.5])for(const y of [-.5,.5])box.expandByPoint(new THREE.Vector3(x,y,0).applyMatrix4(w).applyMatrix4(inverse));
      return {id:child,frame:frame(model,child),left:box.min.x,right:box.max.x};
    });if(!records.length)return;
    const left=Math.min(...records.map(r=>r.left)),right=Math.max(...records.map(r=>r.right)),mode=group.data.textAlign;
    if(reset||group.data.alignmentGuide===undefined)group.data.alignmentGuide=mode==='left'?left:mode==='right'?right:(left+right)/2;
    const direction=new THREE.Vector3().setFromMatrixColumn(groupFrame,0);
    for(const r of records){const edge=mode==='left'?r.left:mode==='right'?r.right:(r.left+r.right)/2,position=new THREE.Vector3().setFromMatrixPosition(r.frame).addScaledVector(direction,group.data.alignmentGuide-edge);setFrame(model,r.id,r.frame.setPosition(position));}
  }
  function setAlignment(model,id,value){if(model.nodes.get(id)?.type!=='labelGroup'||!['left','right','center'].includes(value))throw Error('标签组文字对齐无效');model.commit(()=>{model.nodes.get(id).data.textAlign=value;alignRows(model,id,true);});}
  function refreshAlignment(model,labels){
    const groups=new Set(labels.flatMap(id=>model.ancestors(id)).filter(id=>model.nodes.get(id)?.type==='labelGroup'&&model.nodes.get(id).data.textAlign));
    [...groups].sort((a,b)=>model.ancestors(b).length-model.ancestors(a).length).forEach(id=>alignRows(model,id));
  }
  function fontChanged(model,id,key){
    if(!['labelFont','labelSize'].includes(key))return;
    const node=model.nodes.get(id);if(id!=='global'&&!is(node))return;
    const descendants=new Set(model.descendants(id)),labels=(id==='global'?[...model.nodes.values()].filter(n=>n.type==='label').map(n=>n.id):model.leaves([id]).filter(child=>model.nodes.get(child).type==='label')).filter(child=>{
      const source=model.resolve(child,key).source;return id==='global'?source==='global':source===id||!descendants.has(source);
    });
    labels.forEach(child=>model.nodes.get(child).data.fontSizing=UXAnnotationMath.FONT_SIZING);refreshAlignment(model,labels);
  }
  function centerMode(model,id){return model.nodes.get(id)?.data?.transformCenter||'group';}
  function setCenter(model,id,value){if(model.nodes.get(id)?.type!=='labelGroup'||!['group','individual'].includes(value))throw Error('标签组旋转／缩放中心无效');model.commit(()=>model.nodes.get(id).data.transformCenter=value);}
  function linearIdentity(m){return [0,1,2,4,5,6,8,9,10].every(i=>Math.abs(m.elements[i]-I().elements[i])<1e-10);}
  function setLocal(model,id,local,operation=null,translation=null){
    const before=frame(model,id),boundaries=model.descendants(id).filter(child=>model.nodes.get(child).data?.follow).map(child=>({id:child,frame:frame(model,child)}));
    const individuals=model.nodes.get(id).type==='labelGroup'&&centerMode(model,id)==='individual'?model.leaves([id]).filter(child=>model.nodes.get(child).type==='label').map(child=>({id:child,frame:frame(model,child)})):[];
    model.nodes.get(id).local=local.toArray();const change=frame(model,id).multiply(before.invert());
    // 独立源的坐标系不同；在引用边界补偿，让一次父级操作对各子组产生相同世界变换。
    for(const child of boundaries)setFrame(model,child.id,change.clone().multiply(child.frame));
    if(individuals.length&&operation!=='translate'&&(operation||!linearIdentity(change))){
      const linear=change.clone();linear.elements[12]=linear.elements[13]=linear.elements[14]=0;
      for(const child of individuals){const position=new THREE.Vector3().setFromMatrixPosition(child.frame);if(translation)position.add(translation);
        setFrame(model,child.id,linear.clone().multiply(child.frame).setPosition(position));}
    }
  }
  function delta(model,id,d,operation=null){const base=beforeLocal(model,id);setLocal(model,id,base.clone().invert().multiply(d).multiply(base).multiply(mat(model.nodes.get(id).local)),operation);}
  function inBranch(model,id){return is(model.nodes.get(id));}
  function move(model,id,parent){
    const n=model.nodes.get(id),p=model.nodes.get(parent);
    if(!is(n)||n.type==='annotationRoot'||!p||!['annotationRoot','labelGroup'].includes(p.type)||id===parent||model.descendants(id).includes(parent))throw Error('标注只能在标注分支内迁移，不能与源块或毛坯混组');
    const w=frame(model,id),binding=effective(model,id);if(binding&&!n.data.follow)n.data.follow=copy(binding);
    n.parent=parent;setFrame(model,id,w);
  }
  function next(model,prefix){let id;do{id=prefix+'-'+model.seq++;}while(model.nodes.has(id));return id;}
  function group(model,ids){
    let result;model.commit(()=>{
      ids=model.roots(ids);if(!ids.length||ids.some(id=>!is(model.nodes.get(id))||id==='annotations'))throw Error('只选择标注分支里的标签或标签组');
      const chains=ids.map(id=>model.ancestors(id)),parent=chains[0].find(id=>chains.every(c=>c.includes(id)));
      if(!is(model.nodes.get(parent)))throw Error('标注不能跨分支打组');
      const center=model.bounds(ids).getCenter(new THREE.Vector3()).applyMatrix4(model.chain(parent).invert()),id=next(model,'label-group');
      const n=new UXModel.Node(id,'labelGroup','标签组 '+id.split('-').pop(),parent);n.data={base:I().makeTranslation(...center.toArray()).toArray(),recipe:null};model.nodes.set(id,n);
      ids.forEach(child=>move(model,child,id));result=id;
    });return result;
  }
  function ungroup(model,id,keep){
    model.commit(()=>{const g=model.nodes.get(id);if(g?.type!=='labelGroup')throw Error('先选一个标签组');
      for(const n of model.children(id)){if(keep)for(const [k,v] of Object.entries(g.overrides))if(!Object.hasOwn(n.overrides,k))n.overrides[k]=copy(v);move(model,n.id,g.parent);}model.nodes.delete(id);
    });
  }
  function create(model,plan,append=false){
    const existing=[...model.nodes.values()].find(n=>n.type==='labelGroup'&&n.data.recipe?.sourceId===plan.sourceId&&n.data.recipe.axis===plan.axis&&n.data.recipe.mode===plan.mode);
    if(existing&&!append)throw Error('该源／模式已有标签组，请定位已有组或明确追加');
    let result;model.commit(()=>{
      UXAnnotationMath.source(model,plan.sourceId);ensureRoot(model);
      const origin=I().makeTranslation(...plan.center),id=next(model,'label-group'),n=new UXModel.Node(id,'labelGroup',plan.sourceId+' · '+plan.axis.toUpperCase()+'标注','annotations');
      const recipe=copy(plan);delete recipe.labels;delete recipe.center;
      n.data={base:origin.toArray(),recipe,follow:{sourceId:plan.sourceId,reference:UXAnnotationMath.pose(model,plan.sourceId).toArray()}};
      n.overrides={labelEnabled:true,labelFont:plan.font,labelSize:plan.height};model.nodes.set(id,n);
      for(const l of plan.labels){const labelId=next(model,'label'),child=new UXModel.Node(labelId,'label',l.text,id);child.data={text:l.text,fontSizing:UXAnnotationMath.FONT_SIZING,members:l.members.slice(),base:origin.clone().invert().multiply(mat(l.matrix)).toArray()};model.nodes.set(labelId,child);}
      model.validate(model.snapshot());result=id;
    });return result;
  }
  function remove(model,ids){
    model.commit(()=>{
      const removed=new Set(model.roots(ids).flatMap(id=>[id,...model.descendants(id)]));
      if(['project','global','work','text','vision','refs','annotations'].some(id=>removed.has(id)))throw Error('不能删除系统根节点');
      for(const n of model.nodes.values())if(is(n)&&n.data?.follow?.sourceId&&removed.has(n.data.follow.sourceId)){
        const f=n.data.follow;n.data.follow={sourceId:null,lostSource:f.sourceId,frozen:follow(model,n.id).toArray()};
      }
      for(const id of removed)model.nodes.delete(id);
      if(!model.nodes.has(model.primaryGhost))model.primaryGhost=[...model.nodes.values()].find(n=>n.type==='ghost')?.id||null;
    });
  }
  function text(model,id,value){UXAnnotationMath.measure(value,model.resolve(id,'labelFont').value);model.commit(()=>{const n=model.nodes.get(id);if(n.type!=='label')throw Error('只修改标签自己的文字');n.data.text=value;n.name=value;n.data.fontSizing=UXAnnotationMath.FONT_SIZING;refreshAlignment(model,[id]);});}
  function validateMatrix(a){if(!Array.isArray(a)||a.length!==16||a.some(v=>!Number.isFinite(v))||Math.abs(mat(a).determinant())<1e-12||Math.abs(a[3])+Math.abs(a[7])+Math.abs(a[11])>1e-8||Math.abs(a[15]-1)>1e-8)throw Error('标注参考矩阵无效');}
  function validateRigid(a){validateMatrix(a);const m=mat(a),axes=[0,1,2].map(i=>new THREE.Vector3().setFromMatrixColumn(m,i));if(axes.some(v=>Math.abs(v.lengthSq()-1)>1e-6)||Math.abs(axes[0].dot(axes[1]))>1e-6||Math.abs(axes[0].dot(axes[2]))>1e-6||Math.abs(axes[1].dot(axes[2]))>1e-6||Math.abs(m.determinant()-1)>1e-6)throw Error('跟随参考必须为刚性位姿，不能含缩放或剪切');}
  function validate(model,map){
    if(map.has('annotations')&&(map.get('annotations').type!=='annotationRoot'||map.get('annotations').parent!=='project'))throw Error('标注根身份被替换');
    const known=new Set([...model.topo.blocks.map(b=>b.id),...(model.topo.geometry_only||[]).map(b=>b.id)]),ids=a=>Array.isArray(a)&&a.length<=known.size&&new Set(a).size===a.length&&a.every(id=>known.has(id));
    for(const n of map.values()){
      if(!is(n)){let p=n;while(p?.parent){p=map.get(p.parent);if(is(p))throw Error('源对象不得属于标注分支');}continue;}
      if(n.sourceId!==null||Object.keys(n.overrides||{}).some(k=>!STYLE.includes(k)))throw Error('非法标注身份或属性');
      if(n.type==='annotationRoot'){if(n.id!=='annotations'||n.parent!=='project'||n.local.some((v,i)=>v!==I().elements[i])||n.data)throw Error('标注根无效');continue;}
      if(!['annotationRoot','labelGroup'].includes(map.get(n.parent)?.type))throw Error('标签上级必须在标注分支');
      const d=n.data;if(!d||Object.keys(d).some(k=>!(n.type==='label'?['text','members','base','follow','fontSizing']:['recipe','base','follow','transformCenter','textAlign','alignmentGuide']).includes(k)))throw Error('标注数据字段无效');validateMatrix(d.base);
      if(n.type==='labelGroup'&&d.transformCenter!==undefined&&!['group','individual'].includes(d.transformCenter))throw Error('标签组变换中心无效');
      if(n.type==='label'&&d.fontSizing!==undefined&&d.fontSizing!==UXAnnotationMath.FONT_SIZING)throw Error('标签字号标尺无效');
      if(n.type==='labelGroup'&&((d.textAlign!==undefined&&!['left','right','center'].includes(d.textAlign))||(d.alignmentGuide!==undefined&&(!d.textAlign||!Number.isFinite(d.alignmentGuide)))))throw Error('标签组对齐属性无效');
      if(n.type==='label'){if(!ids(d.members)||!d.members.length)throw Error('标签成员身份无效');UXAnnotationMath.measure(d.text,'Microsoft YaHei');}
      if(n.type==='labelGroup'&&d.recipe!==null){const r=d.recipe;if(!r||Object.keys(r).some(k=>!['sourceId','axis','mode','side','face','gap','tolerance','scopeIds','font','height'].includes(k))||!known.has(r.sourceId)||!['x','y','z'].includes(r.axis)||!Number.isInteger(r.mode)||r.mode<0||r.mode>2||!ids(r.scopeIds)||!r.scopeIds.length||!Number.isFinite(r.gap)||r.gap<0||!/^[-+][xyz]$/.test(r.side)||!['-y','+z'].includes(r.face)||r.tolerance!==UXAnnotationMath.EPS)throw Error('标注生成配方无效');UXModel.validParam('labelFont',r.font);UXModel.validParam('labelSize',r.height);}
      if(d.follow){const f=d.follow;if(Object.keys(f).some(k=>!['sourceId','reference','frozen','lostSource'].includes(k)))throw Error('跟随字段无效');
        if(f.frozen){if(f.sourceId!==null||!known.has(f.lostSource))throw Error('失源标记无效');validateRigid(f.frozen);}
        else{if(!known.has(f.sourceId)||map.get(f.sourceId)?.type!=='block')throw Error('跟随必须引用存在的源块');validateRigid(f.reference);}
      }
    }
  }
  function exportLabels(model,ids){
    const scope=new Set(ids.flatMap(id=>[id,...model.descendants(id)])),all=scope.has('work')||scope.has('project');
    return [...model.nodes.values()].filter(n=>n.type==='label'&&(all||scope.has(n.id)||n.data.members.some(id=>scope.has(id)))).map(n=>{
      const w=world(model,n.id),box=model.bounds([n.id]),normal=new THREE.Vector3(0,0,1).applyMatrix3(new THREE.Matrix3().getNormalMatrix(w)).normalize(),size=UXAnnotationMath.shape(model,n);
      const depth=model.resolve(n.id,'labelDepth').value,gray=model.resolve(n.id,'labelGray').value;
      // 实体真源：字形轮廓（归一化局部坐标，乘 extent_mm 得毫米）＋挤出厚度＋灰度。加工点化不在这里。
      const outline=depth>0&&window.UXGlyph?window.UXGlyph.outline(size.metric):null,round=v=>Math.round(v*1e6)/1e6;
      return {id:n.id,parent:n.parent,coordinateSystem:UXCoordinates.SYSTEM,localGeometryBasis:'glyph-xy-plane',text:n.data.text,members:n.data.members.slice(),font:model.resolve(n.id,'labelFont').value,size_mm:new THREE.Vector3().setFromMatrixColumn(w,1).length(),nominal_height_mm:size.nominalHeight,font_sizing:n.data.fontSizing||'legacy-ink-height',
              depth_mm:depth,gray,
              glyph_solid:depth>0&&outline&&outline.groups.length?'带灰度的字形挤出实体（与雪花小块同层）；加工点化未做':'厚度为0：仅固定朝向纹理平面',
              glyph_outline:depth>0&&outline&&outline.groups.length?{
                basis:'glyph-local-normalized',z_unit:'mm',extent_mm:[round(size.width),round(size.height)],depth_mm:depth,gray,
                threshold:UXGlyph.THRESHOLD,
                contours:outline.groups.map(group=>({outer:group.outer.map(([x,y])=>[round(x),round(y)]),
                  holes:group.holes.map(hole=>hole.map(([x,y])=>[round(x),round(y)]))}))
              }:null,
        glyph_width_mm:new THREE.Vector3().setFromMatrixColumn(w,0).length(),matrix_mm:w.toArray(),anchor_world_mm:box.getCenter(new THREE.Vector3()).toArray(),front_world:normal.toArray(),
        enabled:model.resolve(n.id,'labelEnabled').value,output:model.resolve(n.id,'labelEnabled').value,follow:copy(effective(model,n.id)),
        text_alignment:model.ancestors(n.id).filter(id=>model.nodes.get(id)?.data?.textAlign).map(id=>({group:id,mode:model.nodes.get(id).data.textAlign,guide_local_x:model.nodes.get(id).data.alignmentGuide})),
        glyph_geometry:depth>0&&outline&&outline.groups.length?'字形轮廓＋沿法向挤出；加工点化与厂家读取契约未接入':'未接入：仅固定朝向纹理平面'};
    });
  }
  window.UXAnnotationState={TYPES,STYLE,is,ensureRoot,effective,follow,beforeLocal,frame,world,setFrame,setLocal,alignRows,setAlignment,fontChanged,centerMode,setCenter,delta,inBranch,move,group,ungroup,create,remove,text,validate,exportLabels};
})();

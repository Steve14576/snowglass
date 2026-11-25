/* 标注分组与字体尺寸：只读模型几何，不读取权重。拍平只聚合成员身份。 */
(() => {
  'use strict';
  const EPS=1e-6,FONT_SIZING='font-reference.v1',metricCache=new Map(),AXES=['x','y','z'];
  const MODES={
    x:[{name:'所选XY · 拍平Y',fixed:'z'},{name:'所选XZ · 拍平Z',fixed:'y'},{name:'整塔 · 每个YZ截面',fixed:null}],
    y:[{name:'所选XY · 拍平X',fixed:'z'},{name:'所选YZ · 拍平Z',fixed:'x'},{name:'整塔 · 每个XZ截面',fixed:null}],
    z:[{name:'所选XZ · 拍平X',fixed:'y'},{name:'所选YZ · 拍平Y',fixed:'x'},{name:'整塔 · 每个XY截面',fixed:null}]
  };
  function measure(text,font){
    if(typeof text!=='string'||!text.trim()||text.length>80||/[\r\n]/.test(text))throw Error('标签需为1–80字的单行文字');
    const key=JSON.stringify([text,font]);if(metricCache.has(key))return metricCache.get(key);
    const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');ctx.font='64px '+JSON.stringify(font)+',sans-serif';
    const m=ctx.measureText(text),left=m.actualBoundingBoxLeft||0,right=m.actualBoundingBoxRight||m.width;
    const ascent=m.actualBoundingBoxAscent||48,descent=m.actualBoundingBoxDescent||0,width=Math.max(1,left+right),height=Math.max(1,ascent+descent);
    const result={text,font,cssFont:ctx.font,left,right,ascent,descent,width,height,padding:4,canvasWidth:Math.ceil(width+8),canvasHeight:Math.ceil(height+8)};
    if(metricCache.size>=256)metricCache.delete(metricCache.keys().next().value);metricCache.set(key,result);return result;
  }
  function dimensions(text,font,nominalHeight,uniform=true){
    const metric=measure(text,font),referenceHeight=uniform?64:metric.height,factor=nominalHeight/referenceHeight;
    return {metric,factor,nominalHeight,referenceHeight,width:metric.width*factor,height:metric.height*factor};
  }
  function shape(model,node){return dimensions(node.data.text,model.resolve(node.id,'labelFont').value,model.resolve(node.id,'labelSize').value,node.data.fontSizing===FONT_SIZING);}
  function pose(model,id){
    const matrix=model.objectFrame(id),p=new THREE.Vector3(),q=new THREE.Quaternion();matrix.decompose(p,q,new THREE.Vector3());
    return new THREE.Matrix4().compose(p,q.normalize(),new THREE.Vector3(1,1,1));
  }
  function aggregate(records,axis,fixed=null,coordinate=0,tolerance=EPS){
    const items=records.filter(r=>!fixed||Math.abs(r.center[fixed]-coordinate)<=tolerance).slice().sort((a,b)=>a.center[axis]-b.center[axis]||a.id.localeCompare(b.id));
    const groups=[];
    for(const item of items){let group=groups[groups.length-1];if(!group||item.center[axis]-group.first>tolerance){group={first:item.center[axis],members:[]};groups.push(group);}group.members.push(item);}
    return groups.map(g=>({coordinate:g.members.reduce((v,r)=>v+r.center[axis],0)/g.members.length,members:g.members}));
  }
  function caption(model,group,axis,index){
    const members=group.members,names=[...new Set(members.map(r=>r.name))],layers=[...new Set(members.map(r=>r.layer))];
    const vision=members[0].tower==='vision',prefix=vision?'V':'L';
    if(members.length===1)return members[0].name.slice(0,80);
    if(layers.length===1&&Number.isInteger(layers[0])){
      const layer=layers[0],type=vision?'视觉层':model.topo.model.layer_types[layer]==='full_attention'?'Full Attention':'Gated DeltaNet';
      return prefix+String(layer).padStart(2,'0')+' · '+type;
    }
    if(names.length===1){const range=layers.filter(Number.isInteger).sort((a,b)=>a-b);return (names[0]+' · '+prefix+range[0]+'–'+prefix+range[range.length-1]).slice(0,80);}
    return axis.toUpperCase()+'列'+String(index+1).padStart(2,'0')+' · '+members.length+'块';
  }
  function source(model,id){
    const block=model.topo.blocks.find(b=>b.id===model.nodes.get(id)?.sourceId),node=model.nodes.get(id);
    if(node?.type!=='block'||(!block&&id!=='mtp'))throw Error('先选一个源功能块');
    const tower=block?.id.startsWith('V')?'vision':'text',layer=tower==='vision'?block?.vlayer:block?.layer;
    return {block,node,tower,layer,regular:Number.isInteger(layer)};
  }
  function generate(model,id,options={}){
    const selected=source(model,id),axis=options.axis||'z',mode=options.mode??2,gap=options.gap??1;
    if(!AXES.includes(axis)||!Number.isInteger(mode)||mode<0||mode>2||!Number.isFinite(gap)||gap<0)throw Error('标注轴、模式或外侧间距无效');
    const tower=selected.tower,entries=model.topo.blocks.filter(b=>model.nodes.has(b.id)&&(tower==='vision'?Number.isInteger(b.vlayer):Number.isInteger(b.layer))&&(b.id.startsWith('V')===(tower==='vision')));
    const records=entries.map(b=>({id:b.id,name:model.nodes.get(b.id).name,tower,layer:tower==='vision'?b.vlayer:b.layer,center:new THREE.Vector3().setFromMatrixPosition(model.world(b.id))}));
    const selectedCenter=new THREE.Vector3().setFromMatrixPosition(model.world(id)),spec=MODES[axis][mode];
    const groups=selected.regular?aggregate(records,axis,spec.fixed,selectedCenter[spec.fixed]):[{coordinate:selectedCenter[axis],members:[{id,name:nodeName(model,id),tower,layer:null}]}];
    if(!groups.length)throw Error('该平面没有可标注的源块');
    let side=axis==='x'?'+y':tower==='vision'?'+x':'-x',face=selected.regular&&axis!=='z'?'+z':'-y';
    if(!selected.regular){if(['lm_head','V.merger'].includes(id))side='+z';else if(['embed','V.patch'].includes(id))side='-z';else if(id==='mtp')side='+x';else side='-x';}
    side=options.side||side;if(!/^[+-][xyz]$/.test(side)||(selected.regular&&side[1]===axis))throw Error('放置侧必须与排列轴垂直');
    const scope=selected.regular?records.map(r=>r.id):id==='final_norm'?entries.map(b=>b.id):[id];
    const bounds=model.bounds(scope.length?scope:[id]),font=model.resolve(id,'labelFont').value,height=model.resolve(id,'labelSize').value;
    const rotation=new THREE.Matrix4();if(face==='+z')rotation.makeRotationX(-Math.PI/2);
    const labels=groups.map((g,i)=>{
      const text=selected.regular?caption(model,g,axis,i):selected.node.name,size=dimensions(text,font,height),position=selectedCenter.clone();position[axis]=g.coordinate;
      const {width}=size,sideAxis=side[1],half=sideAxis==='x'?width/2:sideAxis===(face==='+z'?'y':'z')?size.height/2:0;
      position[sideAxis]=side[0]==='+'?bounds.max[sideAxis]+gap+half:bounds.min[sideAxis]-gap-half;
      const matrix=new THREE.Matrix4().makeTranslation(...position.toArray()).multiply(rotation);
      return {text,members:g.members.map(r=>r.id),matrix:matrix.toArray(),width,height:size.height};
    });
    const center=labels.reduce((sum,l)=>sum.add(new THREE.Vector3().setFromMatrixPosition(new THREE.Matrix4().fromArray(l.matrix))),new THREE.Vector3()).multiplyScalar(1/labels.length);
    return {sourceId:id,axis,mode,side,face,gap,tolerance:EPS,scopeIds:groups.flatMap(g=>g.members.map(r=>r.id)),font,height,center:center.toArray(),labels};
  }
  function nodeName(model,id){return model.nodes.get(id).name;}
  window.UXAnnotationMath={EPS,FONT_SIZING,MODES,measure,dimensions,shape,pose,aggregate,source,generate};
})();

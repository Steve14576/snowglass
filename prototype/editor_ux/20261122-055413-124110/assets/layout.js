/* 从旧编辑器逐字提取的4.2配方，仅在独立副本调用。 */
window.SnowLayout=(topo,config={})=>{
const P={widthMode:'equal',squash:.55,depth:6.2,layerGap:0,vision:true,scale:1,...config};
const assembly=new THREE.Matrix4(),manuals={},blockById=Object.fromEntries(topo.blocks.map(b=>[b.id,b]));
const RECIPE = Object.freeze({mixerStart:-9.2,mixerWidth:7.8,mixerGap:.28,ffnStart:.4,ffnWidth:9.6,ffnGap:.32,
  norm1X:-10.2,norm2X:-.55,normWidth:.65,headWidth:14,visionX:23.5});
function groupWidths(total, items, gap) {
  const available = total - gap * (items.length - 1);
  const sum = items.reduce((n,b) => n + (b.params || 0), 0);
  return items.map(b => available * (P.widthMode === "params" && sum ? b.params / sum : 1 / items.length));
}
function boundsOf(solids) {
  const box = new THREE.Box3(); solids.forEach(s => s.corners.forEach(v => box.expandByPoint(v)));
  return box;
}

function layout() {
  const solids = [], warns = [], slots = [];
  const c = topo.model, sq = P.squash, fix = c.n_layers > 45 ? .72 : 1;
  const h = .72 * sq * fix, pitch = 1.17 * sq * fix, H = c.n_layers * pitch, depth = P.depth;
  const global = assembly.clone().multiply(new THREE.Matrix4().makeScale(P.scale,P.scale,P.scale));
  function add(b, center, dims, kind = "block") {
    if (!b) return;
    const size = dims.map((v,i) => Math.max(.0001, v - (i < 2 ? P.layerGap : 0)));
    if (dims[0] <= P.layerGap || dims[1] <= P.layerGap) warns.push(b.id + " 间隙已大于块尺寸，仅保留最小数学厚度");
    const anchor = global.clone().multiply(new THREE.Matrix4().makeTranslation(...center));
    const matrix = anchor.clone().multiply(new THREE.Matrix4().fromArray(manuals[b.id] || new THREE.Matrix4().toArray()))
      .multiply(new THREE.Matrix4().makeScale(...size));
    const corners = []; for (const x of [-.5,.5]) for (const y of [-.5,.5]) for (const z of [-.5,.5])
      corners.push(new THREE.Vector3(x,y,z).applyMatrix4(matrix));
    const box = new THREE.Box3().setFromPoints(corners), lengths = [0,1,2].map(i => new THREE.Vector3().setFromMatrixColumn(matrix,i).length());
    solids.push({id:b.id,kind,block:b,role:b.role,slot:{center: center.slice(),size:dims.slice()},size:lengths,
      localSize:size,anchor,matrix,corners,box,center:new THREE.Vector3().setFromMatrixPosition(matrix),
      x0:box.min.x,x1:box.max.x,y0:box.min.y,y1:box.max.y,z0:box.min.z,z1:box.max.z});
    slots.push({corners:corners.map(v=>v.clone())});
  }
  function group(items,start,width,gap,y) {
    items.sort((a,b)=>a.order-b.order); let cursor = start;
    groupWidths(width,items,gap).forEach((w,i)=>{add(items[i],[cursor+w/2,y,0],[w,h,depth]);cursor += w+gap;});
  }
  const headH = Math.max(1.4,2.5*sq);
  add(blockById.embed,[0,-H/2-headH/2-1.2,0],[14,headH,depth*1.15]);
  for (let i=0;i<c.n_layers;i++) {
    const y = -H/2+(i+.5)*pitch, items = topo.blocks.filter(b=>b.layer===i);
    add(items.find(b=>b.slot==="norm1"),[-10.2,y,0],[.65,h,depth*.6]);
    group(items.filter(b=>b.slot==="mixer"),RECIPE.mixerStart,RECIPE.mixerWidth,RECIPE.mixerGap,y);
    add(items.find(b=>b.slot==="norm2"),[-.55,y,0],[.65,h,depth*.6]);
    group(items.filter(b=>b.slot==="ffn"),RECIPE.ffnStart,RECIPE.ffnWidth,RECIPE.ffnGap,y);
  }
  add(blockById.final_norm,[0,H/2+.85,0],[6.5,Math.max(.4,.6*sq),depth*.6]);
  add(blockById.lm_head,[0,H/2+headH/2+1.8,0],[14,headH,depth*1.15]);
  if(topo.geometry_only.some(b=>b.id==="mtp")) add({id:"mtp",role:"mtp",label:"MTP · 权重未收录",tensors:[],params:0},
    [10.5,H/2+headH/2+1.8,0],[4.2,headH*.85,depth*.9],"mtp");
  if(P.vision&&c.vision_layers) {
    const x=RECIPE.visionX, vp=Math.max(.65,H*.85/c.vision_layers), vh=vp*.62, span=c.vision_layers*vp;
    add(blockById["V.patch"],[x,-span/2-1.4,0],[8.2,Math.max(1.1,1.7*sq),depth*.9]);
    add(blockById["V.merger"],[x,span/2+1.5,0],[8.5,Math.max(1.2,1.9*sq),depth*.95]);
    for(let i=0;i<c.vision_layers;i++) {
      const y=-span/2+(i+.5)*vp, tag="V"+String(i).padStart(2,"0");
      [["norm1",-4.5,.45,.5],["attn",-2.1,3.6,.85],["norm2",.3,.45,.5],["mlp",2.9,4,.85]].forEach(([slot,dx,w,d])=>
        add(blockById[tag+"."+slot],[x+dx,y,0],[w,vh,depth*d]));
    }
  }
  // 槽位尺度独立于间隙；实际外沿可内缩，不推动邻居或改层节距。
  const slotBounds = new THREE.Box3(); solids.forEach(s=>{
    const slotM=s.anchor.clone().multiply(new THREE.Matrix4().makeScale(...s.slot.size));
    for(const x of [-.5,.5])for(const y of [-.5,.5])for(const z of [-.5,.5])slotBounds.expandByPoint(new THREE.Vector3(x,y,z).applyMatrix4(slotM));
  });
  return {solids,warns,H,pitch,bounds:boundsOf(solids),slotBounds,overlaps:[]};
}

/* ============================================================
   几何量：框与壳的有效厚度（块太小会被收窄）、每块的内部体积
   与点数无关，只由毫米尺寸和两个厚度参数决定
   ============================================================ */

return UXCoordinates.layout(layout());
};

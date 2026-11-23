/* 几何后验仅报告，不限制生成。沿用旧编辑器的仿射盒SAT与毛坯内偏移。 */
(() => {
  'use strict';
  function solid(model,id){const m=model.world(id),corners=[];for(const x of [-.5,.5])for(const y of [-.5,.5])for(const z of [-.5,.5])corners.push(new THREE.Vector3(x,y,z).applyMatrix4(m));return {id,matrix:m,corners,box:new THREE.Box3().setFromPoints(corners)};}
  function overlap(a,b){
    for(const key of ['x','y','z'])if(a.box.max[key]<=b.box.min[key]+1e-6||b.box.max[key]<=a.box.min[key]+1e-6)return false;
    const edges=s=>[0,1,2].map(i=>new THREE.Vector3().setFromMatrixColumn(s.matrix,i));
    const A=edges(a),B=edges(b),normals=e=>[e[0].clone().cross(e[1]),e[1].clone().cross(e[2]),e[2].clone().cross(e[0])];
    for(const axis of [...normals(A),...normals(B),...A.flatMap(x=>B.map(y=>x.clone().cross(y)))]){
      if(axis.lengthSq()<1e-15)continue;axis.normalize();const p=a.corners.map(v=>v.dot(axis)),q=b.corners.map(v=>v.dot(axis));
      if(Math.max(...p)<=Math.min(...q)+1e-6||Math.max(...q)<=Math.min(...p)+1e-6)return false;
    }return true;
  }
  function inset(model,id){
    const d=model.nodes.get(id).data,inv=model.geometryFrame(id).invert(),a=inv.elements,rows=[0,1,2].map(i=>new THREE.Vector3(a[i],a[i+4],a[i+8]));
    const A=rows[0].lengthSq(),C=rows[2].lengthSq(),B=rows[0].dot(rows[2]),radial=Math.sqrt((A+C+Math.sqrt((A-C)**2+4*B*B))/2);
    return {inv,shape:d.shape,dims:d.dims.map((v,i)=>v-2*d.margin*rows[i].length()),radius:d.radius-d.margin*radial,
      height:d.height-2*d.margin*rows[1].length(),approx:d.shape==='cylinder'&&(Math.abs(A-C)>1e-6||Math.abs(B)>1e-6)};
  }
  function run(model){
    const solids=[...model.nodes.values()].filter(n=>n.type==='block'&&model.resolve(n.id,'include').value).map(n=>solid(model,n.id));
    const overlaps=[];for(let i=0;i<solids.length;i++)for(let j=i+1;j<solids.length;j++)if(overlap(solids[i],solids[j]))overlaps.push([solids[i].id,solids[j].id]);
    const ghosts=[...model.nodes.values()].filter(n=>n.type==='ghost').map(n=>{
      const inner=inset(model,n.id),invalid=inner.shape==='box'?inner.dims.some(v=>v<=0):inner.radius<=0||inner.height<=0;
      const outside=solids.filter(s=>invalid||s.corners.some(c=>{const v=c.clone().applyMatrix4(inner.inv);return inner.shape==='box'?v.toArray().some((x,i)=>Math.abs(x)>inner.dims[i]/2+1e-6):Math.hypot(v.x,v.z)>inner.radius+1e-6||Math.abs(v.y)>inner.height/2+1e-6;})).map(s=>s.id);
      return {id:n.id,name:n.name,invalid,approx:inner.approx,outside,primary:model.primaryGhost===n.id};
    });return {solids:solids.length,overlaps,ghosts};
  }
  window.UXChecks={solid,overlap,inset,run};
})();

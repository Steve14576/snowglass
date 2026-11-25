/* 统一右手世界坐标：X向右、Y向后、Z向上。原网格／字体／形状局部数据不重排。 */
(() => {
  'use strict';
  const SYSTEM='snowglass.xyz-z-up.v1',GEOMETRY='legacy-grid-and-primitive-xyz',LABEL_POLICY='explicit-enabled.v1';
  const OLD_LABEL_KEYS=['labels','labelText','labelDx','labelDy','labelDz','labelOutput'];
  const basis=()=>new THREE.Matrix4().makeRotationX(Math.PI/2),inverse=()=>basis().invert();
  function matrix(a){if(!Array.isArray(a)||a.length!==16||a.some(v=>typeof v!=='number'||!Number.isFinite(v)))throw Error('旧工程参考矩阵无效');return new THREE.Matrix4().fromArray(a);}
  function point(a){if(!Array.isArray(a)||a.length!==3||a.some(v=>typeof v!=='number'||!Number.isFinite(v)))throw Error('旧工程坐标向量无效');return [a[0],-a[2],a[1]];}
  function conjugate(m){return basis().multiply(m).multiply(inverse());}
  function direction(s){const map={'+x':'+x','-x':'-x','+y':'+z','-y':'-z','+z':'-y','-z':'+y'};if(!map[s])throw Error('旧工程标注方向无效');return map[s];}
  function labels(doc){
    if(doc.annotationPolicy!==undefined&&doc.annotationPolicy!==LABEL_POLICY)throw Error('工程标签策略不支持');
    const next=CurveMath.copy(doc);if(!Array.isArray(next.nodes))throw Error('工程缺少对象清单');
    const old=next.annotationPolicy!==LABEL_POLICY,global=next.nodes.find(n=>n.type==='global');
    for(const n of next.nodes){
      const annotation=['annotationRoot','labelGroup','label'].includes(n.type);
      if(annotation){const values=n.overrides||{};
        if(!Object.hasOwn(values,'labelEnabled')&&Object.hasOwn(values,'visible'))values.labelEnabled=values.visible;
        if(old&&n.type==='annotationRoot'&&!Object.hasOwn(values,'labelEnabled'))values.labelEnabled=global?.values?.visible??true;
        delete values.visible;n.overrides=values;
      }
      for(const values of [n.overrides,n.values])if(values)for(const key of OLD_LABEL_KEYS)delete values[key];
    }
    if(global?.values&&!Object.hasOwn(global.values,'labelEnabled'))global.values.labelEnabled=true;
    next.annotationPolicy=LABEL_POLICY;return next;
  }
  function prepare(doc){
    if(!doc||typeof doc!=='object')throw Error('工程格式无效');
    if(doc.coordinateSystem===SYSTEM){if(doc.localGeometryBasis!==undefined&&doc.localGeometryBasis!==GEOMETRY)throw Error('工程局部几何版本不支持');return labels(doc);}
    if(doc.coordinateSystem!==undefined&&doc.coordinateSystem!=='legacy-y-up')throw Error('工程坐标版本不支持');
    const next=labels(doc);
    if(!Array.isArray(next.nodes))throw Error('工程缺少对象清单');
    for(const node of next.nodes){
      node.local=conjugate(matrix(node.local)).toArray();
      if(['label','labelGroup'].includes(node.type)&&node.data){
        const d=node.data;d.base=conjugate(matrix(d.base)).toArray();
        if(d.follow){for(const key of ['reference','frozen'])if(d.follow[key])d.follow[key]=conjugate(matrix(d.follow[key])).toArray();}
        if(d.recipe){const r=d.recipe,old=r.axis;if(!['x','y','z'].includes(old)||!Number.isInteger(r.mode)||r.mode<0||r.mode>2)throw Error('旧标注排列轴或模式无效');
          r.axis={x:'x',y:'z',z:'y'}[old];if(old==='x'&&r.mode!==2)r.mode=1-r.mode;r.side=direction(r.side);r.face=direction(r.face);
        }
      }
    }
    if(next.view){for(const key of ['camera','target'])if(next.view[key])next.view[key]=point(next.view[key]);}
    next.coordinateSystem=SYSTEM;next.localGeometryBasis=GEOMETRY;return next;
  }
  function layout(raw){
    const C=basis(),solids=raw.solids.map(s=>{
      const m=C.clone().multiply(s.matrix),corners=s.corners.map(v=>v.clone().applyMatrix4(C)),box=new THREE.Box3().setFromPoints(corners);
      return {...s,recipeMatrix:s.matrix.clone(),matrix:m,anchor:conjugate(s.anchor),corners,box,center:s.center.clone().applyMatrix4(C),
        slot:{...s.slot,center:point(s.slot.center),size:[s.slot.size[0],s.slot.size[2],s.slot.size[1]],geometrySize:s.slot.size.slice()},
        x0:box.min.x,x1:box.max.x,y0:box.min.y,y1:box.max.y,z0:box.min.z,z1:box.max.z};
    });
    return {...raw,solids,
      bounds:raw.bounds.clone().applyMatrix4(C),slotBounds:raw.slotBounds.clone().applyMatrix4(C),coordinateSystem:SYSTEM,localGeometryBasis:GEOMETRY,heightAxis:'z'};
  }
  window.UXCoordinates={SYSTEM,GEOMETRY,LABEL_POLICY,OLD_LABEL_KEYS,basis,inverse,point,conjugate,direction,prepare,layout};
})();

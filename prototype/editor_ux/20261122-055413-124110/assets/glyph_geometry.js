/* 字形轮廓与挤出：文字从贴图变成"带灰度的实体"，与雪花小块同层（单位几何＋灰度）。
   不做加工点化，不读权重。 */
(() => {
  'use strict';
  const THRESHOLD=.5,outlineCache=new Map(),geometryCache=new Map();
  const key=metric=>JSON.stringify([metric.text,metric.font,metric.canvasWidth,metric.canvasHeight]);

  function alphaMap(metric){
    const w=Math.max(1,metric.canvasWidth),h=Math.max(1,metric.canvasHeight),canvas=document.createElement('canvas');
    canvas.width=w;canvas.height=h;
    const ctx=canvas.getContext('2d',{willReadFrequently:true});
    ctx.font=metric.cssFont;ctx.textAlign='left';ctx.textBaseline='alphabetic';ctx.fillStyle='#fff';
    ctx.fillText(metric.text,metric.padding+metric.left,metric.padding+metric.ascent);
    const pixels=ctx.getImageData(0,0,w,h).data,alpha=new Float32Array(w*h);
    for(let i=0;i<w*h;i++)alpha[i]=pixels[i*4+3]/255;
    return {alpha,w,h};
  }

  // 在像素之间做等值线：四个角一起判定，端点按两侧值线性插值，相邻格子共用同一条边的端点。
  function trace(alpha,w,h){
    const at=(x,y)=>(x<0||y<0||x>=w||y>=h)?0:alpha[y*w+x];
    const points=new Map(),links=new Map();
    const endpoint=(id,x1,y1,x2,y2,v1,v2)=>{
      if(!points.has(id)){const t=(THRESHOLD-v1)/((v2-v1)||1e-9);points.set(id,[x1+(x2-x1)*t,y1+(y2-y1)*t]);links.set(id,[]);}
      return id;
    };
    const link=(a,b)=>{links.get(a).push(b);links.get(b).push(a);};
    for(let y=-1;y<h;y++)for(let x=-1;x<w;x++){
      const v1=at(x,y),v2=at(x+1,y),v3=at(x+1,y+1),v4=at(x,y+1);
      const code=(v1>THRESHOLD?1:0)|(v2>THRESHOLD?2:0)|(v3>THRESHOLD?4:0)|(v4>THRESHOLD?8:0);
      if(code===0||code===15)continue;
      const top=()=>endpoint('h:'+x+':'+y,x,y,x+1,y,v1,v2);
      const right=()=>endpoint('v:'+(x+1)+':'+y,x+1,y,x+1,y+1,v2,v3);
      const bottom=()=>endpoint('h:'+x+':'+(y+1),x,y+1,x+1,y+1,v4,v3);
      const left=()=>endpoint('v:'+x+':'+y,x,y,x,y+1,v1,v4);
      const pairs=[];
      switch(code){
        case 1:pairs.push([left(),top()]);break;
        case 2:pairs.push([top(),right()]);break;
        case 3:pairs.push([left(),right()]);break;
        case 4:pairs.push([right(),bottom()]);break;
        case 5:pairs.push([left(),top()],[right(),bottom()]);break;
        case 6:pairs.push([top(),bottom()]);break;
        case 7:pairs.push([left(),bottom()]);break;
        case 8:pairs.push([bottom(),left()]);break;
        case 9:pairs.push([top(),bottom()]);break;
        case 10:pairs.push([top(),right()],[bottom(),left()]);break;
        case 11:pairs.push([right(),bottom()]);break;
        case 12:pairs.push([right(),left()]);break;
        case 13:pairs.push([top(),right()]);break;
        case 14:pairs.push([left(),top()]);break;
      }
      for(const [a,b] of pairs)link(a,b);
    }
    const seen=new Set(),rings=[];
    for(const start of links.keys()){
      if(seen.has(start))continue;
      const ring=[],local=new Set();let current=start,previous=null,closed=false;
      for(;;){
        const neighbours=links.get(current);
        if(local.has(current)||!neighbours||neighbours.length!==2)break;
        local.add(current);seen.add(current);ring.push(points.get(current));
        const next=neighbours[0]===previous?neighbours[1]:neighbours[0];
        previous=current;current=next;
        if(current===start){closed=true;break;}
      }
      if(closed&&ring.length>=3)rings.push(ring);
    }
    return rings.map(ring=>ring.map(([px,py])=>[px/w-.5,.5-py/h]));
  }

  function area(ring){let sum=0;for(let i=0,j=ring.length-1;i<ring.length;j=i++)sum+=(ring[j][0]*ring[i][1]-ring[i][0]*ring[j][1]);return Math.abs(sum)/2;}
  function inside(point,ring){
    let hit=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){
      const [xi,yi]=ring[i],[xj,yj]=ring[j];
      if((yi>point[1])!==(yj>point[1])&&point[0]<(xj-xi)*(point[1]-yi)/((yj-yi)||1e-12)+xi)hit=!hit;
    }
    return hit;
  }

  function outline(metric){
    const id=key(metric);if(outlineCache.has(id))return outlineCache.get(id);
    const {alpha,w,h}=alphaMap(metric);
    const rings=trace(alpha,w,h).filter(ring=>area(ring)>1e-7);
    // 嵌套深度决定外轮廓与洞：偶数层是实体外环，奇数层是洞。
    const depth=rings.map((ring,i)=>rings.reduce((sum,other,j)=>j===i?sum:sum+(inside(ring[0],other)?1:0),0));
    const groups=[];
    rings.forEach((ring,i)=>{
      if(depth[i]%2!==0)return;
      const holes=rings.map((other,j)=>j).filter(j=>depth[j]%2===1&&inside(rings[j][0],ring));
      groups.push({outer:ring,holes:holes.map(j=>rings[j])});
    });
    const result={rings,depth,groups};
    if(outlineCache.size>=128)outlineCache.delete(outlineCache.keys().next().value);
    outlineCache.set(id,result);return result;
  }

  function geometry(metric,depthMm){
    const thickness=Math.max(0,Number(depthMm)||0);
    if(!(thickness>0))return {geometry:null,outline:outline(metric)};
    const id=key(metric)+'|'+thickness.toFixed(4);
    if(geometryCache.has(id))return {geometry:geometryCache.get(id).clone(),outline:outline(metric)};
    const source=outline(metric),shapes=[];
    for(const group of source.groups){
      const shape=new THREE.Shape(group.outer.map(([x,y])=>new THREE.Vector2(x,y)));
      for(const hole of group.holes)shape.holes.push(new THREE.Path(hole.map(([x,y])=>new THREE.Vector2(x,y))));
      shapes.push(shape);
    }
    if(!shapes.length)return {geometry:null,outline:source};
    const built=new THREE.ExtrudeGeometry(shapes,{depth:thickness,bevelEnabled:false,steps:1,curveSegments:1});
    built.translate(0,0,-thickness/2);built.computeVertexNormals();
    if(geometryCache.size>=96)geometryCache.delete(geometryCache.keys().next().value);
    geometryCache.set(id,built);
    return {geometry:built.clone(),outline:source};
  }

  window.UXGlyph={outline,geometry,THRESHOLD};
})();

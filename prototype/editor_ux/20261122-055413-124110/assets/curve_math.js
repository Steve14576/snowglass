/* 曲线是数值映射，不是出点概率。预览与保存共用同一查找表。 */
(() => {
  'use strict';
  const clip=v=>Math.max(0,Math.min(1,v)),copy=v=>JSON.parse(JSON.stringify(v));
  const linear=()=>({nodes:[{x:0,y:0},{x:1,y:1}]});
  function validate(curve){
    if(!curve||!Array.isArray(curve.nodes)||curve.nodes.length<2||curve.nodes.length>64)throw Error('曲线需要2–64个节点');
    const nodes=curve.nodes;
    nodes.forEach((n,i)=>{
      if(![n.x,n.y].every(Number.isFinite)||n.x<0||n.x>1||n.y<0||n.y>1||(i&&n.x<=nodes[i-1].x))throw Error('曲线输入需递增，灰度在0–1内');
      for(const side of ['in','out'])if(n[side]&&(!Array.isArray(n[side])||n[side].length!==2||n[side].some(v=>!Number.isFinite(v)||v<0||v>1)))throw Error('曲线手柄无效');
      if(n.in&&(n.in[0]>n.x||(i&&n.in[0]<nodes[i-1].x)))throw Error('输入手柄不能越过相邻节点');
      if(n.out&&(n.out[0]<n.x||(i<nodes.length-1&&n.out[0]>nodes[i+1].x)))throw Error('输出手柄不能越过相邻节点');
    });
    if(nodes[0].x!==0||nodes.at(-1).x!==1)throw Error('输入端点必须为0和1');return true;
  }
  function segment(a,b){
    const dx=(b.x-a.x)/3,dy=(b.y-a.y)/3;
    return [[a.x,a.y],a.out||[a.x+dx,a.y+dy],b.in||[b.x-dx,b.y-dy],[b.x,b.y]];
  }
  const cubic=(p,t)=>{const u=1-t;return u*u*u*p[0]+3*u*u*t*p[1]+3*u*t*t*p[2]+t*t*t*p[3];};
  function value(curve,x){
    const ns=curve.nodes;let i=0;x=clip(x);while(i<ns.length-2&&ns[i+1].x<x)i++;
    const p=segment(ns[i],ns[i+1]);let lo=0,hi=1;
    for(let k=0;k<24;k++){const mid=(lo+hi)/2;if(cubic(p.map(v=>v[0]),mid)<x)lo=mid;else hi=mid;}
    if(x===0)return ns[0].y;if(x===1)return ns.at(-1).y;
    return clip(cubic(p.map(v=>v[1]),(lo+hi)/2));
  }
  function table(curve,size=4097){validate(curve);return Float64Array.from({length:size},(_,i)=>value(curve,i/(size-1)));}
  function lookup(lut,x){const p=clip(x)*(lut.length-1),i=Math.floor(p);return lut[i]+(lut[Math.min(i+1,lut.length-1)]-lut[i])*(p-i);}
  function path(curve){
    const ns=curve.nodes;let d=`M ${ns[0].x*100} ${(1-ns[0].y)*100}`;
    for(let i=1;i<ns.length;i++){const p=segment(ns[i-1],ns[i]);d+=` C ${p[1][0]*100} ${(1-p[1][1])*100},${p[2][0]*100} ${(1-p[2][1])*100},${p[3][0]*100} ${(1-p[3][1])*100}`;}
    return d;
  }
  function insert(curve,x){
    const c=copy(curve),ns=c.nodes;x=clip(x);let i=0;while(i<ns.length-2&&ns[i+1].x<x)i++;
    if(x-ns[i].x<.001||ns[i+1].x-x<.001)throw Error('节点太接近，先移动原节点');
    const p=segment(ns[i],ns[i+1]);let lo=0,hi=1;for(let k=0;k<24;k++){const t=(lo+hi)/2;if(cubic(p.map(v=>v[0]),t)<x)lo=t;else hi=t;}
    const t=(lo+hi)/2,lerp=(a,b)=>a.map((v,j)=>v+(b[j]-v)*t);
    const a=lerp(p[0],p[1]),b=lerp(p[1],p[2]),d=lerp(p[2],p[3]),e=lerp(a,b),f=lerp(b,d),g=lerp(e,f);
    ns[i].out=a;ns[i+1].in=d;ns.splice(i+1,0,{x:g[0],y:g[1],in:e,out:f});validate(c);return {curve:c,index:i+1};
  }
  function preset(name){
    if(name==='reverse')return {nodes:[{x:0,y:1},{x:1,y:0}]};
    if(name==='s')return {nodes:[{x:0,y:0,out:[.35,0]},{x:1,y:1,in:[.65,1]}]};
    if(name==='gamma'||name==='log')return {nodes:Array.from({length:9},(_,i)=>{const x=i/8;return {x,y:name==='gamma'?x*x:Math.log1p(9*x)/Math.log(10)};})};
    return linear();
  }
  window.CurveMath={clip,copy,linear,validate,segment,value,table,lookup,path,insert,preset};
})();

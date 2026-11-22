/* 多节点与贝塞尔手柄。第一次实际编辑才覆盖，查看／选节点不覆盖。 */
(() => {
  'use strict';
  class CurveUI {
    constructor(container,model,id,error){this.container=container;this.model=model;this.id=id;this.error=error;this.index=0;this.handles=false;this.drag=null;this.build();}
    curve(){return CurveMath.copy(this.model.resolve(this.id,'curve').value);}
    safe(fn){try{fn();}catch(e){this.error(e.message);this.redraw();}}
    build(){
      this.container.innerHTML='<div class="curve-axis"><span>输出灰度 0–1</span><span id="curve-source"></span></div><div class="curve-wrap"><svg viewBox="-4 -4 108 108" preserveAspectRatio="none" aria-label="多点灰度曲线" role="img"></svg><div class="curve-axis"><span>输入 0</span><span>窗口后归一输入</span><span>1</span></div></div><div class="curve-tools"><select id="curve-preset" aria-label="曲线预设"><option value="linear">线性</option><option value="reverse">反转</option><option value="s">S形贝塞尔</option><option value="gamma">平方（9节点近似）</option><option value="log">对数（9节点近似）</option></select><button id="apply-preset">用此预设</button><button id="curve-add">加中间点</button><button id="curve-delete">删除内点</button><button id="curve-handles">显示手柄</button></div><div class="curve-values"><label>节点输入 x<input id="curve-x" type="number" step="0.001" min="0" max="1"></label><label>输出灰度 g<input id="curve-y" type="number" step="0.001" min="0" max="1"></label></div><div class="curve-tools"><button id="curve-lock">固定当前曲线</button><button id="curve-inherit">恢复继承</button></div><p class="prop-note">双击曲线加点；拖节点或手柄。允许反转／峰谷，输入不能折返。4097点查找表近似，预览与保存使用相同规则；任意解析式暂不执行。</p>';
      const q=id=>this.container.querySelector('#'+id);this.svg=this.container.querySelector('svg');
      q('apply-preset').onclick=()=>this.safe(()=>this.model.set(this.id,'curve',CurveMath.preset(q('curve-preset').value)));
      q('curve-add').onclick=()=>this.safe(()=>{const c=this.curve(),i=Math.min(this.index,c.nodes.length-2),r=CurveMath.insert(c,(c.nodes[i].x+c.nodes[i+1].x)/2);this.index=r.index;this.model.set(this.id,'curve',r.curve);});
      q('curve-delete').onclick=()=>this.safe(()=>{const c=this.curve();if(this.index===0||this.index===c.nodes.length-1)return;c.nodes.splice(this.index,1);this.index--;this.model.set(this.id,'curve',c);});
      q('curve-handles').onclick=()=>{this.handles=!this.handles;this.redraw();};
      q('curve-lock').onclick=()=>this.safe(()=>this.model.lock(this.id,'curve'));q('curve-inherit').onclick=()=>this.safe(()=>this.model.inherit(this.id,'curve'));
      for(const axis of ['x','y'])q('curve-'+axis).onchange=()=>this.safe(()=>{const text=q('curve-'+axis).value,value=Number(text);if(!text.trim()||!Number.isFinite(value)||value<0||value>1)throw Error('请输入0–1范围的有效节点值');const c=this.curve();this.adjustNode(c,this.index,axis==='x'?value:c.nodes[this.index].x,axis==='y'?value:c.nodes[this.index].y);this.model.set(this.id,'curve',c);});
      this.svg.ondblclick=e=>this.safe(()=>{if(e.target.dataset.index!==undefined)return;const r=CurveMath.insert(this.curve(),this.xy(e).x);this.index=r.index;this.model.set(this.id,'curve',r.curve);});
      this.svg.onpointerdown=e=>{const target=e.target;if(!target.dataset.index)return;e.preventDefault();e.stopPropagation();this.index=+target.dataset.index;this.drag={index:this.index,side:target.dataset.side||'node',startX:e.clientX,startY:e.clientY,started:false};this.model.beginGesture();this.svg.setPointerCapture(e.pointerId);this.redraw();};
      this.svg.onpointermove=e=>{if(!this.drag)return;if(!this.drag.started&&Math.hypot(e.clientX-this.drag.startX,e.clientY-this.drag.startY)<2)return;this.drag.started=true;this.safe(()=>{const c=this.curve(),p=this.xy(e),d=this.drag,n=c.nodes[d.index];
        if(d.side==='node')this.adjustNode(c,d.index,p.x,p.y);
        else{const min=d.side==='in'?(c.nodes[d.index-1]?.x||0):n.x,max=d.side==='in'?n.x:(c.nodes[d.index+1]?.x||1);n[d.side]=[Math.max(min,Math.min(max,p.x)),p.y];}
        CurveMath.validate(c);this.model.updateGesture(()=>this.model.put(this.id,'curve',c));this.redraw();});};
      const finish=()=>{if(!this.drag)return;this.drag=null;this.model.endGesture();this.redraw();};this.svg.onpointerup=finish;this.svg.onpointercancel=finish;this.redraw();
    }
    xy(e){const r=this.svg.getBoundingClientRect();return {x:CurveMath.clip(((e.clientX-r.left)/r.width*108-4)/100),y:CurveMath.clip(1-((e.clientY-r.top)/r.height*108-4)/100)};}
    adjustNode(curve,index,x,y){
      const ns=curve.nodes,n=ns[index],oldX=n.x,oldY=n.y;
      n.x=index===0?0:index===ns.length-1?1:Math.max(ns[index-1].x+.001,Math.min(ns[index+1].x-.001,x));n.y=CurveMath.clip(y);
      for(const side of ['in','out'])if(n[side])n[side]=[n[side][0]+n.x-oldX,CurveMath.clip(n[side][1]+n.y-oldY)];
      ns.forEach((p,i)=>{if(p.in)p.in[0]=Math.max(ns[i-1]?.x||0,Math.min(p.x,p.in[0]));if(p.out)p.out[0]=Math.max(p.x,Math.min(ns[i+1]?.x||1,p.out[0]));});
      CurveMath.validate(curve);
    }
    redraw(){
      if(!this.container.isConnected)return;const c=this.curve(),ns=c.nodes;this.index=Math.min(this.index,ns.length-1);
      let svg='<path class="curve-grid" d="M0 0H100V100H0Z M25 0V100 M50 0V100 M75 0V100 M0 25H100 M0 50H100 M0 75H100"/>';
      svg+=`<path class="curve-path" d="${CurveMath.path(c)}"/>`;
      if(this.handles){const n=ns[this.index];for(const side of ['in','out']){
        const i=this.index;if(side==='in'&&i===0||side==='out'&&i===ns.length-1)continue;
        const p=side==='in'?CurveMath.segment(ns[i-1],n)[2]:CurveMath.segment(n,ns[i+1])[1];
        svg+=`<line class="curve-tangent" x1="${n.x*100}" y1="${(1-n.y)*100}" x2="${p[0]*100}" y2="${(1-p[1])*100}"/><rect class="curve-handle" data-index="${i}" data-side="${side}" x="${p[0]*100-1.1}" y="${(1-p[1])*100-1.1}" width="2.2" height="2.2"/>`;
      }}
      ns.forEach((n,i)=>svg+=`<circle class="curve-node${i===this.index?' selected':''}" data-index="${i}" cx="${n.x*100}" cy="${(1-n.y)*100}" r="1.6"/>`);this.svg.innerHTML=svg;
      const q=id=>this.container.querySelector('#'+id),r=this.model.resolve(this.id,'curve');
      q('curve-source').textContent=this.id==='global'?'全局曲线':r.own?'本地曲线':'继承自：'+this.model.nodes.get(r.source).name;
      q('curve-x').value=ns[this.index].x.toFixed(4);q('curve-y').value=ns[this.index].y.toFixed(4);q('curve-x').disabled=this.index===0||this.index===ns.length-1;
      q('curve-delete').disabled=this.index===0||this.index===ns.length-1;q('curve-inherit').disabled=!r.own||this.id==='global';q('curve-lock').disabled=this.id==='global';
    }
  }
  window.UXCurveUI=CurveUI;
})();

/* 单视口编辑，实体框壳与固定毫米雪花。未计算块只保留结构，不填模拟。 */
(() => {
  'use strict';
  class Scene {
    constructor(element,model,onSelect,onHover,onGesture){
      const T=THREE;this.model=model;this.element=element;this.onSelect=onSelect;this.onHover=onHover;this.onGesture=onGesture;this.selected=[];this.exposure=1;this.scopeAll=false;this.snowMeshes=new Map();this.isolate=false;this.observation=[];
      this.renderer=new T.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.25));this.renderer.setClearColor(0x000000);element.append(this.renderer.domElement);
      this.initWorldAxes();
      this.scene=new T.Scene();this.camera=new T.PerspectiveCamera(42,1,.001,2000);this.camera.up.set(0,0,1);this.orbit=new T.OrbitControls(this.camera,this.renderer.domElement);this.orbit.addEventListener('change',()=>this.render());
      this.unit=new T.BoxGeometry(1,1,1);this.frames=new T.InstancedMesh(this.unit,new T.MeshBasicMaterial({transparent:true,depthWrite:false,blending:T.AdditiveBlending}),5000);
      this.shells=new T.InstancedMesh(this.unit,new T.MeshBasicMaterial({transparent:true,depthWrite:false,blending:T.AdditiveBlending,side:T.DoubleSide}),2500);
      this.proxy=new T.InstancedMesh(this.unit,new T.MeshBasicMaterial({visible:false}),1000);
      // r128首帧编译前就分配实例颜色，防止之后仍用不含灰度的白色材质程序。
      this.frames.setColorAt(0,new T.Color(0,0,0));this.shells.setColorAt(0,new T.Color(0,0,0));
      [this.frames,this.shells,this.proxy].forEach(m=>{m.count=0;m.frustumCulled=false;this.scene.add(m);});
      this.highlights=new T.Group();this.ghosts=new T.Group();this.snow=new T.Group();this.labels=new T.Group();[this.highlights,this.ghosts,this.snow,this.labels].forEach(g=>this.scene.add(g));this.annotationView=new UXAnnotationView(this);
      this.pivot=new T.Object3D();this.scene.add(this.pivot);this.gumball=new T.TransformControls(this.camera,this.renderer.domElement);this.gumball.setSize(.75);this.scene.add(this.gumball);this.gumball.addEventListener('change',()=>this.render());this.mode='translate';
      this.gumball.addEventListener('dragging-changed',e=>{this.orbit.enabled=!e.value;if(e.value){model.beginGesture();this.startPivot=this.pivot.matrixWorld.clone();this.startLocals=new Map(model.roots(this.selected).flatMap(id=>[id,...model.descendants(id)]).map(id=>[id,model.nodes.get(id).local.slice()]));}
        else{model.endGesture();this.syncPivot();this.onGesture(false);}});
      this.gumball.addEventListener('objectChange',()=>{if(!this.startPivot||!this.gumball.dragging)return;this.pivot.updateMatrixWorld();const d=this.pivot.matrixWorld.clone().multiply(this.startPivot.clone().invert());
        if(Math.abs(d.determinant())<1e-12)return;model.updateGesture(()=>{for(const [id,local] of this.startLocals)model.nodes.get(id).local=local.slice();model.delta(this.selected,d,this.mode);});this.onGesture(true);});
      this.ray=new T.Raycaster();this.mouse=new T.Vector2();this.blockIds=[];this.boxMode=false;this.down=null;
      const canvas=this.renderer.domElement;
      canvas.addEventListener('pointerdown',e=>{this.down={x:e.clientX,y:e.clientY,shift:e.shiftKey,ctrl:e.ctrlKey||e.metaKey};
        const wantBox=this.boxMode||e.shiftKey;
        if(wantBox&&!this.gumball.axis&&!this.gumball.dragging){this.orbit.enabled=false;this.boxStart={x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);}});
      canvas.addEventListener('pointermove',e=>{if(this.boxStart){const r=element.getBoundingClientRect(),box=document.getElementById('marquee');box.hidden=false;box.style.left=Math.min(e.clientX,this.boxStart.x)-r.left+'px';box.style.top=Math.min(e.clientY,this.boxStart.y)-r.top+'px';box.style.width=Math.abs(e.clientX-this.boxStart.x)+'px';box.style.height=Math.abs(e.clientY-this.boxStart.y)+'px';return;}
        if(!this.gumball.dragging)this.onHover(this.pick(e),e);});
      canvas.addEventListener('pointerup',e=>{
        if(this.boxStart){const a=this.boxStart,b={x:e.clientX,y:e.clientY},ids=[...this.blockIds,...this.annotationView.hits.map(m=>m.userData.id)].filter(id=>{const p=this.screen(id);return p.x>=Math.min(a.x,b.x)&&p.x<=Math.max(a.x,b.x)&&p.y>=Math.min(a.y,b.y)&&p.y<=Math.max(a.y,b.y);});
          this.boxStart=null;document.getElementById('marquee').hidden=true;this.orbit.enabled=true;this.onSelect(ids,'replace');return;}
        if(this.down&&Math.hypot(e.clientX-this.down.x,e.clientY-this.down.y)<4&&!this.gumball.axis&&!this.gumball.dragging){
          const id=this.pick(e);
          if(!id){this.onSelect([],'replace');}else this.onSelect([id],this.down.ctrl?'toggle':this.down.shift?'toggle':'replace');
        }this.down=null;
      });
      canvas.addEventListener('pointerleave',()=>this.onHover(null));new ResizeObserver(()=>this.resize()).observe(element);this.fit();this.resize();
    }
    clear(group){for(const o of group.children.slice()){group.remove(o);o.traverse(n=>{if(n.geometry&&n.geometry!==this.unit)n.geometry.dispose();if(n.material){if(n.material.map)n.material.map.dispose();n.material.dispose();}});}}
    initWorldAxes(){
      const box=document.createElement('div');box.id='world-axis';box.dataset.frame='world';box.setAttribute('role','img');
      box.setAttribute('aria-label','世界坐标：X正向右、负向左；Y正向后、负向前；Z正向上、负向下。轴图随相机转动，不随对象转动。');
      const title=document.createElement('div');title.className='axis-title';title.textContent='世界坐标 · XYZ';
      this.axisCanvas=document.createElement('canvas');this.axisCanvas.setAttribute('aria-hidden','true');
      const legend=document.createElement('div');legend.className='axis-legend';
      for(const [axis,text] of [['x','X  +右 / -左'],['y','Y  +后 / -前'],['z','Z  +上 / -下']]){
        const row=document.createElement('span');row.className='axis-'+axis;row.textContent=text;legend.append(row);
      }
      box.append(title,this.axisCanvas,legend);this.element.append(box);
    }
    drawWorldAxes(){
      if(!this.axisCanvas)return;
      const T=THREE,q=this.camera.getWorldQuaternion(new T.Quaternion()).invert(),ratio=Math.min(devicePixelRatio||1,2);
      const signature=JSON.stringify([q.toArray(),ratio]);if(this.axisSignature===signature)return;this.axisSignature=signature;
      const c=this.axisCanvas,ctx=c.getContext('2d'),style=getComputedStyle(document.getElementById('world-axis'));
      c.width=Math.round(144*ratio);c.height=Math.round(108*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);
      const color=key=>'hsl('+style.getPropertyValue(key).trim()+')',background=color('--panel');
      const entries=[];
      for(const [axis,vector] of [['X',[1,0,0]],['Y',[0,1,0]],['Z',[0,0,1]]])for(const sign of [-1,1]){
        const v=new T.Vector3(...vector).multiplyScalar(sign).applyQuaternion(q);
        entries.push({axis,sign,label:(sign>0?'+':'-')+axis,x:72+v.x*30,y:54-v.y*30,depth:v.z});
      }
      this.axisProjection=entries;ctx.textAlign='center';ctx.textBaseline='middle';ctx.font='600 12px system-ui';
      for(const e of entries.slice().sort((a,b)=>a.depth-b.depth)){
        const tint=color('--axis-'+e.axis.toLowerCase()),dx=e.x-72,dy=e.y-54,length=Math.hypot(dx,dy);
        ctx.globalAlpha=e.sign>0?1:.65;ctx.strokeStyle=tint;ctx.fillStyle=tint;ctx.lineWidth=e.sign>0?2:1;
        ctx.setLineDash(e.sign>0?[]:[3,3]);ctx.beginPath();ctx.moveTo(72,54);ctx.lineTo(e.x,e.y);ctx.stroke();ctx.setLineDash([]);
        ctx.beginPath();ctx.arc(e.x,e.y,e.sign>0?4:6,0,Math.PI*2);if(e.sign>0)ctx.fill();else ctx.stroke();
        // 接近正视某根轴时，正负端点重合；仅移开文字，不伪造轴的投影方向。
        const tx=length<6?e.x+e.sign*20:e.x+dx/length*14,ty=length<6?e.y+e.sign*10:e.y+dy/length*14;
        ctx.lineWidth=3;ctx.strokeStyle=background;ctx.strokeText(e.label,tx,ty);ctx.fillText(e.label,tx,ty);
      }
      ctx.globalAlpha=1;ctx.fillStyle=color('--ink');ctx.beginPath();ctx.arc(72,54,2,0,Math.PI*2);ctx.fill();
    }
    render(){this.renderer.render(this.scene,this.camera);this.drawWorldAxes();}
    resize(){const w=this.element.clientWidth,h=this.element.clientHeight;this.renderer.setSize(w,h,false);this.camera.aspect=w/h;this.camera.updateProjectionMatrix();this.render();}
    setMode(mode){this.mode=mode;if(mode==='off')this.gumball.detach();else this.gumball.setMode(mode);this.syncPivot();}
    select(ids){this.selected=ids;this.syncPivot();}
    syncPivot(){if(this.gumball.dragging)return;const T=THREE,ids=this.selected.filter(id=>this.model.nodes.has(id)&&!['project','global','reference','annotationRoot'].includes(this.model.nodes.get(id).type));
      if(!ids.length||this.mode==='off'){this.gumball.detach();return;}const bounds=this.model.bounds(ids);if(bounds.isEmpty()){this.gumball.detach();return;}
      this.pivot.position.copy(bounds.getCenter(new T.Vector3()));
      // 单选时手柄姿态跟随对象自身旋转；多选保持世界轴，避免每个对象各转一个角度而无语义。
      if(ids.length===1){const q=new T.Quaternion();this.model.objectFrame(ids[0]).decompose(new T.Vector3(),q,new T.Vector3());this.pivot.quaternion.copy(q);}
      else this.pivot.quaternion.identity();
      this.pivot.scale.set(1,1,1);this.pivot.updateMatrixWorld();this.gumball.attach(this.pivot);this.gumball.setMode(this.mode);this.render();}
    fit(ids=['work'],front=false){const box=this.model.bounds(ids);if(box.isEmpty())return;const size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3()),d=Math.max(size.x,size.y,size.z,.5)*1.9;
      this.camera.position.copy(center).add(new THREE.Vector3(front?0:d*.3,-d,front?0:d*.14));this.orbit.target.copy(center);this.orbit.update();this.render();}
    screen(id){const p=this.model.bounds([id]).getCenter(new THREE.Vector3()).project(this.camera),r=this.renderer.domElement.getBoundingClientRect();return {x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2};}
    pick(e){const r=this.renderer.domElement.getBoundingClientRect();this.mouse.set((e.clientX-r.left)/r.width*2-1,1-(e.clientY-r.top)/r.height*2);this.scene.updateMatrixWorld();this.ray.setFromCamera(this.mouse,this.camera);
      if(e.altKey){const h=this.ray.intersectObjects(this.ghostHits||[],false)[0];return h?.object.userData.id||null;}const label=this.annotationView.pick(this.ray),hit=this.ray.intersectObject(this.proxy,false)[0];return label&&(!hit||label.distance<hit.distance)?label.object.userData.id:hit?this.blockIds[hit.instanceId]:null;}
    structure(){
      const T=THREE,M=this.model;let fi=0,si=0,pi=0;this.blockIds=[];this.clear(this.highlights);this.clear(this.labels);
      const selected=new Set(M.leaves(this.selected)),observed=new Set(M.leaves(this.observation).filter(id=>M.nodes.get(id).type==='block')),covered=this.annotationView.covered();
      for(const n of M.nodes.values())if(n.type==='block'&&M.resolve(n.id,'visible').value&&(!this.isolate||!observed.size||observed.has(n.id))){
        const m=M.world(n.id),dims=[0,1,2].map(i=>new T.Vector3().setFromMatrixColumn(m,i).length()),[x,y,z]=dims;
        const t=Math.min(M.resolve(n.id,'frameT').value,Math.min(...dims)/2),sh=Math.min(M.resolve(n.id,'shellT').value,Math.min(...dims)/2);
        const basis=m.clone().multiply(new T.Matrix4().makeScale(...dims.map(v=>1/v))),col=new T.Color();
        this.proxy.setMatrixAt(pi++,m);this.blockIds.push(n.id);
        const piece=(mesh,idx,c,d,g)=>{mesh.setMatrixAt(idx,basis.clone().multiply(new T.Matrix4().makeTranslation(...c)).multiply(new T.Matrix4().makeScale(...d)));mesh.setColorAt(idx,col.setRGB(g,g,g));};
        const fg=M.resolve(n.id,'frameGray').value;
        if(t>0)for(const yy of [-y/2+t/2,y/2-t/2])for(const zz of [-z/2+t/2,z/2-t/2])piece(this.frames,fi++,[0,yy,zz],[x,t,t],fg);
        if(t>0)for(const xx of [-x/2+t/2,x/2-t/2])for(const zz of [-z/2+t/2,z/2-t/2])piece(this.frames,fi++,[xx,0,zz],[t,Math.max(.00001,y-2*t),t],fg);
        if(t>0)for(const xx of [-x/2+t/2,x/2-t/2])for(const yy of [-y/2+t/2,y/2-t/2])piece(this.frames,fi++,[xx,yy,0],[t,t,Math.max(.00001,z-2*t)],fg);
        const sg=M.resolve(n.id,'shellGray').value;if(n.id!=='mtp'&&sh>0){
          for(const yy of [-y/2+sh/2,y/2-sh/2])piece(this.shells,si++,[0,yy,0],[x,sh,z],sg);
          for(const zz of [-z/2+sh/2,z/2-sh/2])piece(this.shells,si++,[0,0,zz],[x,Math.max(.00001,y-2*sh),sh],sg);
          for(const xx of [-x/2+sh/2,x/2-sh/2])piece(this.shells,si++,[xx,0,0],[sh,Math.max(.00001,y-2*sh),Math.max(.00001,z-2*sh)],sg);
        }
        if(selected.has(n.id)){
          // 黄色双层轮廓＋低透明外扩面：不隐其它对象，也能一眼看出选中。
          for(const [scale,opacity] of [[1,1],[1.028,.5]]){
            const edge=new T.LineSegments(new T.EdgesGeometry(this.unit),new T.LineBasicMaterial({color:0xffd24a,depthTest:false,transparent:true,opacity}));
            edge.matrixAutoUpdate=false;edge.matrix.copy(m).multiply(new T.Matrix4().makeScale(scale,scale,scale));this.highlights.add(edge);
          }
          const glow=new T.Mesh(this.unit,new T.MeshBasicMaterial({color:0xffd24a,transparent:true,opacity:.10,depthWrite:false,side:T.BackSide}));
          glow.matrixAutoUpdate=false;glow.matrix.copy(m).multiply(new T.Matrix4().makeScale(1.045,1.045,1.045));this.highlights.add(glow);
        }
        if(M.resolve(n.id,'labels').value&&!covered.has(n.id)){const text=M.resolve(n.id,'labelText').value||n.name;const font=M.resolve(n.id,'labelFont').value||'Microsoft YaHei';const c=document.createElement('canvas'),ctx=c.getContext('2d');c.width=512;c.height=64;ctx.font='22px '+font+',sans-serif';ctx.fillStyle='#f3d79a';ctx.fillText(text,8,36);
          const sp=new T.Sprite(new T.SpriteMaterial({map:new T.CanvasTexture(c),depthTest:false})),size=M.resolve(n.id,'labelSize').value;sp.scale.set(size*8,size,1);
          sp.position.copy(new T.Vector3().setFromMatrixPosition(m)).add(new T.Vector3(M.resolve(n.id,'labelDx').value,M.resolve(n.id,'labelDy').value,M.resolve(n.id,'labelDz').value));this.labels.add(sp);}
      }
      this.frames.count=fi;this.shells.count=si;this.proxy.count=pi;for(const mesh of [this.frames,this.shells,this.proxy]){mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;}
      this.clear(this.ghosts);this.ghostHits=[];
      for(const n of M.nodes.values())if(n.type==='ghost'){
        const d=n.data,inner=UXChecks.inset(M,n.id),world=M.geometryFrame(n.id);
        for(const inset of [false,true]){
          let geo;if(d.shape==='box'){const dims=inset?inner.dims:d.dims;if(dims.some(v=>v<=0))continue;geo=new T.BoxGeometry(...dims);}
          else{const r=inset?inner.radius:d.radius,h=inset?inner.height:d.height;if(r<=0||h<=0)continue;geo=new T.CylinderGeometry(r,r,h,40);}
          const selected=this.selected.includes(n.id),line=new T.LineSegments(new T.EdgesGeometry(geo),new T.LineBasicMaterial({color:selected?0x88d8c2:inset?0x4b6262:0x64747b,transparent:true,opacity:inset?.35:.6}));
          line.matrixAutoUpdate=false;line.matrix.copy(world);this.ghosts.add(line);
          if(!inset){const hit=new T.Mesh(geo,new T.MeshBasicMaterial({transparent:true,opacity:0,depthWrite:false,side:T.DoubleSide}));hit.userData.id=n.id;hit.matrixAutoUpdate=false;hit.matrix.copy(world);this.ghosts.add(hit);this.ghostHits.push(hit);}else geo.dispose();
        }
      }
      this.annotationView.update();this.syncPivot();
    }
    drawSnow(results){
      const T=THREE,M=this.model,used=new Set();this.renderedSnow=0;
      for(const result of results){if(!M.nodes.has(result.id)||!M.resolve(result.id,'visible').value)continue;const world=M.world(result.id),q=new T.Quaternion();world.decompose(new T.Vector3(),q,new T.Vector3());
        const side=M.resolve(result.id,'snowSize').value;
        for(const p of result.pieces){
          const key=result.id+'|'+p.key+'|'+p.name;used.add(key);let mesh=this.snowMeshes.get(key);
          if(mesh&&mesh.instanceMatrix.count!==p.gray.length){this.snow.remove(mesh);mesh.material.dispose();mesh.dispose?.();this.snowMeshes.delete(key);mesh=null;}
          if(!mesh){mesh=new T.InstancedMesh(this.unit,new T.MeshBasicMaterial(),p.gray.length);mesh.frustumCulled=false;this.snowMeshes.set(key,mesh);this.snow.add(mesh);}
          const geometryKey=JSON.stringify([world.elements,side,p.region,p.grid,result.settings.filter?[p.data_sha256,p.used,result.settings.windowMode,result.settings.black,result.settings.white,result.settings.cutoff]:false]);
          const colorKey=JSON.stringify([result.signature,p.data_sha256,this.exposure]);
          const updatePositions=mesh.userData.geometryKey!==geometryKey,updateColors=mesh.userData.colorKey!==colorKey;
          if(!updatePositions&&!updateColors){this.renderedSnow+=mesh.count;continue;}
          const mat=new T.Matrix4(),pos=new T.Vector3(),color=new T.Color(),size=new T.Vector3(side,side,side);let count=0;
          for(let i=0;i<p.gray.length;i++){if(!p.mask[i])continue;
            if(updatePositions){pos.fromArray(UXData.position(p,i)).applyMatrix4(world);mat.compose(pos,q,size);mesh.setMatrixAt(count,mat);}
            if(updateColors||updatePositions){const g=Math.min(1,p.gray[i]*this.exposure);mesh.setColorAt(count,color.setRGB(g,g,g));}count++;
          }
          mesh.count=count;if(updatePositions)mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;
          mesh.userData={sourceId:result.id,tensor:p.key,geometryKey,colorKey};this.renderedSnow+=count;
        }
      }
      for(const [key,mesh] of this.snowMeshes)if(!used.has(key)){this.snow.remove(mesh);mesh.material.dispose();mesh.dispose?.();this.snowMeshes.delete(key);}
      this.render();
    }
  }
  window.UXScene=Scene;
})();

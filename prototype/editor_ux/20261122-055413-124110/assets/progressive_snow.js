/* 预览显示调度：真实格子分批建实例；交互用确定性格子概览，统计与输出保持全值。 */
(() => {
  'use strict';
  // 显示层起始资源配置，非科学／加工参数；可据实测调整，不进入切片签名。
  const LIMITS={batchCells:4096,batchMs:6,detailCells:4000000,loadedCells:8000000,overviewPoints:128000};
  class ProgressiveSnow {
    constructor(scene,changed=()=>{}){
      this.scene=scene;scene.progressive=this;this.changed=changed;this.records=new Map();this.enabled=false;this.paused=false;this.interacting=false;
      // 显示精度：overview 始终只画概览；settle 拖动用概览、停下补细节；always 转动时也画完整细节。
      this.mode='settle';
      this.loading=false;this.frame=null;this.allocated=0;this.points=0;this.waiters=[];this.motion=new Set();this.endTimer=null;this.budget=false;
      this.overview=new THREE.Group();scene.snow.add(this.overview);
      scene.orbit.addEventListener('start',()=>this.motionStart('orbit'));
      scene.orbit.addEventListener('end',()=>this.motionEnd('orbit'));
      scene.gumball.addEventListener('mouseDown',()=>{this.motion.delete('orbit');this.motionStart('gumball');});
      scene.gumball.addEventListener('dragging-changed',e=>{if(e.value){this.motion.delete('orbit');this.motionStart('gumball');}else this.motionEnd('gumball');});
      scene.gumball.addEventListener('mouseUp',()=>this.motionEnd('gumball'));
      scene.renderer.domElement.addEventListener('pointerdown',()=>this.motionStart('pointer'),{capture:true});
      const end=()=>this.motionEnd('pointer');window.addEventListener('pointerup',end);window.addEventListener('pointercancel',end);window.addEventListener('blur',()=>{this.motion.clear();this.motionEnd('pointer');});
    }
    status(){
      const records=[...this.records.values()],built=records.reduce((s,r)=>s+r.count,0),ready=records.filter(r=>r.ready).length;
      return {enabled:this.enabled,mode:this.mode,paused:this.paused,interacting:this.interacting,loading:this.loading,budget:this.budget,
        pieces:records.length,ready,built,allocated:this.allocated,overviewPoints:this.points,
        settled:!this.loading&&(this.paused||this.mode==='overview'||this.budget||ready===records.length),limits:LIMITS};
    }
    notify(){this.changed(this.status());}
    wake(){const list=this.waiters.splice(0);list.forEach(resolve=>resolve());}
    // 只有“停下后细化”把拖动当成暂缓；始终轻量要保持概览，始终完整则无需等。
    blocked(){return this.paused||(this.mode==='settle'&&this.interacting);}
    async waitActive(current){while(this.enabled&&this.blocked()){await new Promise(resolve=>this.waiters.push(resolve));if(!current())return false;}return this.enabled&&current();}
    setMode(mode){
      if(!['overview','settle','always'].includes(mode))return this.mode;
      this.mode=mode;if(mode==='overview'&&this.frame!==null){cancelAnimationFrame(this.frame);this.frame=null;}
      this.wake();this.notify();this.scene.render();this.schedule();return this.mode;
    }
    begin(ids){
      this.enabled=true;this.loading=true;this.budget=false;this.order=new Map(ids.map((id,i)=>[id,i]));this.samples=Math.max(1,Math.min(128,Math.floor(LIMITS.overviewPoints/Math.max(1,ids.length*3))));
      const keep=new Set(ids);for(const [key,r] of this.records)if(!keep.has(r.id)){this.remove(r);this.records.delete(key);}
      this.notify();this.schedule();
    }
    finish(){this.loading=false;this.notify();this.schedule();}
    motionStart(kind){
      this.motion.add(kind);clearTimeout(this.endTimer);this.interacting=true;
      if(this.frame!==null){cancelAnimationFrame(this.frame);this.frame=null;}if(this.enabled){this.beforeRender();this.scene.render();this.notify();if(this.mode==='always')this.schedule();}
    }
    motionEnd(kind){
      this.motion.delete(kind);clearTimeout(this.endTimer);
      this.endTimer=setTimeout(()=>{if(this.motion.size)return;this.interacting=false;this.wake();
        if(this.enabled){this.scene.render();this.notify();this.schedule();}},120);
    }
    pause(value){this.paused=!!value;this.wake();if(this.paused&&this.frame!==null){cancelAnimationFrame(this.frame);this.frame=null;}this.scene.render();this.notify();this.schedule();}
    dropDetail(r){
      for(const mesh of r.chunks){this.scene.snow.remove(mesh);this.scene.snowMeshes.delete(mesh.userData.chunkKey);mesh.material.dispose();mesh.dispose?.();this.allocated-=mesh.instanceMatrix.count;}
      r.chunks=[];r.offset=0;r.count=0;r.ready=false;
    }
    remove(r){this.dropDetail(r);this.overview.remove(r.light);r.light.geometry.dispose();r.light.material.dispose();this.points-=r.light.geometry.attributes.position.count;}
    clear(){
      this.enabled=false;this.loading=false;this.paused=false;this.budget=false;this.wake();
      if(this.frame!==null)cancelAnimationFrame(this.frame);this.frame=null;
      for(const r of this.records.values())this.remove(r);this.records.clear();this.scene.drawSnow([]);this.notify();
    }
    offer(result){
      if(!this.enabled)return;const s=this.scene,M=s.model,T=THREE,world=M.world(result.id),q=new T.Quaternion();world.decompose(new T.Vector3(),q,new T.Vector3());
      const used=new Set();
      for(const p of result.pieces){
        const key=result.id+'|'+p.key+'|'+p.name;used.add(key);
        const geometry=JSON.stringify([world.elements,M.resolve(result.id,'snowSize').value,p.region,p.grid]),signature=JSON.stringify([geometry,result.signature,p.data_sha256,s.exposure]);
        let r=this.records.get(key);if(r?.signature===signature)continue;
        if(r){this.remove(r);this.records.delete(key);}
        const capacity=Math.max(0,Math.min(this.samples,p.gray.length,LIMITS.overviewPoints-this.points));
        const positions=[],colors=[];
        for(let j=0;j<capacity;j++){
          const i=Math.min(p.gray.length-1,Math.floor((j+.5)*p.gray.length/capacity));if(!p.mask[i])continue;
          positions.push(...UXData.position(p,i));const g=Math.min(1,p.gray[i]*s.exposure);colors.push(g,g,g);
        }
        const geo=new T.BufferGeometry();geo.setAttribute('position',new T.Float32BufferAttribute(positions,3));geo.setAttribute('color',new T.Float32BufferAttribute(colors,3));
        geo.computeBoundingSphere();const light=new T.Points(geo,new T.PointsMaterial({size:M.resolve(result.id,'snowSize').value,vertexColors:true,sizeAttenuation:true,depthWrite:true}));
        light.matrixAutoUpdate=false;light.matrix.copy(world);light.matrixWorldNeedsUpdate=true;light.userData.sourceId=result.id;this.overview.add(light);this.points+=positions.length/3;
        r={key,id:result.id,p,result,signature,geometry,world:world.clone(),q:q.clone(),side:M.resolve(result.id,'snowSize').value,light,chunks:[],offset:0,count:0,ready:false};this.records.set(key,r);
      }
      for(const [key,r] of this.records)if(r.id===result.id&&!used.has(key)){this.remove(r);this.records.delete(key);}
      this.budget=false;this.schedule();
    }
    beforeRender(){
      if(!this.enabled)return;const s=this.scene,worlds=new Map();let displayed=0;
      for(const r of this.records.values()){
        if(!s.model.nodes.has(r.id)){r.light.visible=false;r.chunks.forEach(m=>m.visible=false);continue;}
        if(!worlds.has(r.id))worlds.set(r.id,s.model.world(r.id));const world=worlds.get(r.id);
        const current=JSON.stringify([world.elements,s.model.resolve(r.id,'snowSize').value,r.p.region,r.p.grid])===r.geometry;
        // overview 不展示细节；always 连转动时也展示；settle 只在停下后展示。
        const moving=this.interacting&&this.mode!=='always';
        const visible=s.model.resolve(r.id,'visible').value,detail=visible&&current&&r.ready&&!moving&&!this.paused&&this.mode!=='overview';
        r.light.matrix.copy(world);r.light.matrixWorldNeedsUpdate=true;r.light.visible=visible&&!detail;
        for(const mesh of r.chunks)mesh.visible=detail;if(detail)displayed+=r.count;
      }
      s.renderedSnow=displayed;
    }
    schedule(){
      if(!this.enabled||this.paused||this.mode==='overview'||(this.interacting&&this.mode!=='always')||this.budget||this.frame!==null||![...this.records.values()].some(r=>!r.ready))return;
      this.frame=requestAnimationFrame(()=>{this.frame=null;this.step();});
    }
    step(){
      if(!this.enabled||this.paused||this.mode==='overview'||(this.interacting&&this.mode!=='always'))return;
      const start=performance.now(),pending=[...this.records.values()].filter(r=>!r.ready).sort((a,b)=>(this.order?.get(a.id)||0)-(this.order?.get(b.id)||0));let chunks=0;
      for(const r of pending){
        while(!r.ready&&chunks<4&&performance.now()-start<LIMITS.batchMs){
          const capacity=Math.min(LIMITS.batchCells,r.p.gray.length-r.offset);
          if(this.allocated+capacity>LIMITS.detailCells){this.budget=true;break;}
          const T=THREE,mesh=new T.InstancedMesh(this.scene.unit,new T.MeshBasicMaterial(),capacity),mat=new T.Matrix4(),position=new T.Vector3(),size=new T.Vector3(r.side,r.side,r.side),color=new T.Color();
          // 颜色缓冲按容量分配；r128首次setColorAt按count分配，不能在count=0时调用。
          mesh.instanceColor=new T.InstancedBufferAttribute(new Float32Array(capacity*3),3);
          mesh.count=0;mesh.frustumCulled=false;const from=r.offset;let count=0;
          for(let i=from;i<from+capacity;i++)if(r.p.mask[i]){
            position.fromArray(UXData.position(r.p,i)).applyMatrix4(r.world);mat.compose(position,r.q,size);mesh.setMatrixAt(count,mat);
            const g=Math.min(1,r.p.gray[i]*this.scene.exposure);mesh.setColorAt(count,color.setRGB(g,g,g));count++;
          }
          mesh.count=count;mesh.instanceMatrix.needsUpdate=true;mesh.instanceColor.needsUpdate=true;
          mesh.userData={sourceId:r.id,tensor:r.p.key,chunkKey:r.key+'#'+from};mesh.visible=false;this.scene.snow.add(mesh);this.scene.snowMeshes.set(mesh.userData.chunkKey,mesh);
          r.chunks.push(mesh);this.allocated+=capacity;r.count+=count;r.offset+=capacity;r.ready=r.offset>=r.p.gray.length;chunks++;
        }
        if(this.budget||chunks>=4||performance.now()-start>=LIMITS.batchMs)break;
      }
      this.scene.render();this.notify();this.schedule();
    }
  }
  window.UXProgressiveSnow=ProgressiveSnow;
})();

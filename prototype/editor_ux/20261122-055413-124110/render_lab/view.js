/* 在独立浏览器页面复用主场景。A/B仅改画布采样与文字纹理过滤。 */
(() => {
  'use strict';
  const filters={linear:'线性 · 无mipmap',mipmap:'mipmap',anisotropic:'mipmap＋斜视过滤'},tick=()=>new Promise(resolve=>requestAnimationFrame(resolve));
  function ratio(value){const device=devicePixelRatio||1,caps={cap125:1.25,cap175:1.75,cap2:2};return value in caps?Math.min(device,caps[value]):Number(value);}
  class View {
    constructor(element,state,hover){
      this.scene=new UXScene(element,state.model,()=>{},hover,()=>{});this.scene.setMode('off');this.scene.orbit.enableDamping=false;
      this.scene.exposure=state.doc?.view?.exposure??1;this.scene.isolate=false;this.state=state;this.profile='a';
      this.layered=new RenderLabLayered(this.scene);
      window.addEventListener('pagehide',()=>this.layered.dispose(),{once:true});
    }
    attach(state){this.state=state;this.scene.model=state.model;this.scene.selected=[];this.scene.exposure=state.doc?.view?.exposure??1;this.scene.isolate=false;}
    draw(results){this.scene.observation=results.map(r=>r.id);this.scene.structure();this.scene.drawSnow(results);}
    restoreCamera(){
      const v=this.state.doc?.view,s=this.scene;
      if(v?.camera&&v?.target){s.camera.position.fromArray(v.camera);s.orbit.target.fromArray(v.target);s.orbit.update();s.render();}
      else s.fit(['work']);
    }
    apply(profile,config){
      const s=this.scene,split=config.comparison==='layered',requested=profile==='a'&&!split?{ratio:'cap125',filter:'linear'}:config;
      const value=ratio(requested.ratio);if(!Number.isFinite(value)||value<=0||value>2)throw Error('对照像素比必须为正且不超过2');
      if(!Object.hasOwn(filters,requested.filter))throw Error('文字过滤选项无效');
      let filter=requested.filter,warning='';
      if(filter!=='linear'&&!s.renderer.capabilities.isWebGL2){filter='linear';warning='此环境为WebGL1，非二次幂文字贴图不强行生成mipmap；当前回退线性过滤。';}
      const anisotropy=filter==='anisotropic'?Math.min(8,s.renderer.capabilities.getMaxAnisotropy()):1;
      for(const item of s.annotationView.textures.values()){
        const texture=item.texture;texture.generateMipmaps=filter!=='linear';texture.minFilter=filter==='linear'?THREE.LinearFilter:THREE.LinearMipmapLinearFilter;
        texture.magFilter=THREE.LinearFilter;texture.anisotropy=anisotropy;texture.needsUpdate=true;
      }
      const sceneRatio=Math.min(value,ratio(config.sceneRatio||'cap125'));
      if(!Number.isFinite(sceneRatio)||sceneRatio<=0)throw Error('雪花画面像素比无效');
      this.layered.active=split&&profile==='b'&&this.layered.supported;this.layered.ratio=sceneRatio;
      if(split&&profile==='b'&&!this.layered.supported)warning+=' 分层实验需要WebGL2；本环境仍用整场景绘制，没有伪装分层。';
      s.renderer.setPixelRatio(value);this.profile=profile;
      this.applied={ratio:value,filter,requestedFilter:requested.filter,anisotropy,warning,comparison:config.comparison||'resolution',pipeline:this.layered.active?'layered':'uniform',sceneRatio:this.layered.active?sceneRatio:value};
      s.resize();return this.applied;
    }
    evidence(){
      const s=this.scene,r=s.renderer,gl=r.getContext(),rect=r.domElement.getBoundingClientRect(),textures=[...s.annotationView.textures.values()].map(v=>v.texture.image);
      const labels=[...this.state.model.nodes.values()].filter(n=>n.type==='label'),enabled=labels.filter(n=>this.state.model.resolve(n.id,'labelEnabled').value);
      const projected=enabled.map(n=>{
        const w=this.state.model.world(n.id),a=new THREE.Vector3(0,-.5,0).applyMatrix4(w).project(s.camera),b=new THREE.Vector3(0,.5,0).applyMatrix4(w).project(s.camera);
        return Math.hypot((a.x-b.x)*rect.width/2,(a.y-b.y)*rect.height/2);
      }).filter(Number.isFinite);
      return {deviceRatio:devicePixelRatio||1,ratio:r.getPixelRatio(),css:[rect.width,rect.height],buffer:[gl.drawingBufferWidth,gl.drawingBufferHeight],
        context:gl.getContextAttributes(),webgl2:r.capabilities.isWebGL2,maxTexture:r.capabilities.maxTextureSize,textureCount:textures.length,
        texturePixels:textures.reduce((sum,img)=>sum+img.width*img.height,0),largestTexture:textures.reduce((a,img)=>Math.max(a,img.width,img.height),0),
        minimumGlyphCssPixels:projected.length?Math.min(...projected):null,labels:labels.length,enabled:enabled.length,snow:s.renderedSnow,
        meshes:s.snowMeshes.size,triangles:this.layered.active?this.layered.last?.triangles:r.info.render.triangles,drawCalls:this.layered.active?this.layered.last?.drawCalls:r.info.render.calls,
        profile:this.profile,applied:this.applied,layered:this.layered.evidence()};
    }
    async benchmark(config,progress){
      const s=this.scene,gl=s.renderer.getContext(),saved=this.profile,orbit=s.orbit.enabled,report={samples:5,unit:'ms',method:'renderer.render＋gl.finish；含CPU提交和GPU完成等待，非完整编辑器帧率',profiles:{}};
      const before=JSON.stringify(this.state.model.snapshot());s.orbit.enabled=false;
      try{
        for(const profile of ['a','b']){
          this.apply(profile,config);for(let i=0;i<2;i++){await tick();s.render();gl.finish();}
          const samples=[];
          for(let i=0;i<report.samples;i++){
            progress(i,report.samples,`短测${profile.toUpperCase()}档 ${i+1} / ${report.samples}；等候显卡完成绘制`);await tick();
            if(gl.isContextLost())throw Error('WebGL上下文已丢失；停止短测，不自动重试');
            const start=performance.now();s.render();gl.finish();samples.push(performance.now()-start);
          }
          const ordered=samples.slice().sort((a,b)=>a-b);report.profiles[profile]={ratio:s.renderer.getPixelRatio(),filter:this.applied.filter,pipeline:this.applied.pipeline,sceneRatio:this.applied.sceneRatio,
            buffer:this.evidence().buffer,layered:this.layered.evidence(),median:ordered[Math.floor(ordered.length/2)],min:ordered[0],max:ordered[ordered.length-1],samples};
        }
        if(before!==JSON.stringify(this.state.model.snapshot()))throw Error('画质短测意外改变工程');return report;
      }finally{s.orbit.enabled=orbit;this.apply(saved,config);}
    }
  }
  window.RenderLabView={View,ratio,filters};
})();

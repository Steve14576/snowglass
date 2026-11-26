/* 隔离图形探针：实际像素读回，不截图、不生成用户标签、不改统计。 */
(() => {
  'use strict';
  const assert=(ok,text)=>{if(!ok)throw Error(text);};
  function run(){
    const view=renderLab.view,s=view.scene,r=s.renderer,T=THREE,annotation=s.annotationView.group;
    if(!view.layered.supported)return {supported:false,note:'WebGL1只核验明确回退，不宣称已验证分层'};
    const model=JSON.stringify(renderLab.state.model.snapshot()),camera=s.camera,profile=view.profile;
    const config={comparison:'layered',ratio:'2',sceneRatio:'1.25',filter:'linear'};
    const visible=s.scene.children.map(o=>[o,o.visible]),children=annotation.children.map(o=>[o,o.visible]);
    const probeCamera=new T.OrthographicCamera(-3,3,3,-3,.1,30);probeCamera.position.set(0,0,10);probeCamera.lookAt(0,0,0);
    const canvas=document.createElement('canvas');canvas.width=128;canvas.height=128;
    const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.font='96px Arial';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText('H',64,64);
    const texture=new T.CanvasTexture(canvas);texture.generateMipmaps=false;texture.minFilter=T.LinearFilter;
    const glyph=new T.Mesh(new T.PlaneGeometry(4,4),new T.MeshBasicMaterial({map:texture,transparent:true,alphaTest:.01,depthWrite:false,side:T.FrontSide}));
    const blocker=new T.Mesh(new T.PlaneGeometry(6,6),new T.MeshBasicMaterial({color:0xff0000,depthWrite:true}));
    function pixels(){
      s.render();const gl=r.getContext(),width=gl.drawingBufferWidth,height=gl.drawingBufferHeight,data=new Uint8Array(width*height*4);
      gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,data);assert(gl.getError()===gl.NO_ERROR,'分层绘制或像素读回出现GL错误');
      let white=0,red=0;for(let i=0;i<data.length;i+=4){if(data[i]>150&&data[i+1]>150&&data[i+2]>150)white++;if(data[i]>200&&data[i+1]<10&&data[i+2]<10)red++;}
      return {data,width,height,white,red};
    }
    try{
      for(const [o] of visible)o.visible=o===annotation;for(const [o] of children)o.visible=false;
      s.camera=probeCamera;annotation.add(glyph);s.scene.add(blocker);
      const counts={};
      for(const z of [-1,1]){
        glyph.position.z=z;view.apply('a',config);const a=pixels();view.apply('b',config);const b=pixels();
        assert(a.width===b.width&&a.height===b.height,'分层对照最终画布尺寸不同');
        if(z<0)assert(a.white===0&&b.white===0&&b.red>a.width*a.height*.95,'背后文字穿透不透明遮挡物');
        else assert(a.white>100&&b.white>100&&Math.abs(a.white-b.white)<Math.max(10,a.white*.01),'前方文字未高清绘制或像素形状显著改变');
        counts[z<0?'behind':'front']={aWhite:a.white,bWhite:b.white,aRed:a.red,bRed:b.red};
      }
      const identity={...config,sceneRatio:'2'};view.apply('a',identity);const a=pixels();view.apply('b',identity);const b=pixels();
      let differences=0;for(let i=0;i<a.data.length;i++)if(Math.abs(a.data[i]-b.data[i])>2)differences++;
      assert(differences/a.data.length<.002,'等分辨率合成改变画面颜色／坐标／文字');
      const allocations=view.layered.allocations;s.render();s.render();assert(view.layered.allocations===allocations,'每帧重新分配离屏缓冲');
      assert(r.getRenderTarget()===null&&r.autoClear===true&&r.info.autoReset===true,'分层pass没有恢复renderer状态');
      assert(annotation.visible&&blocker.visible,'分层没有恢复对象可见性');
      assert(JSON.stringify(renderLab.state.model.snapshot())===model,'像素探针改变主工程定义');
      return {supported:true,counts,identityColorDifferenceFraction:differences/a.data.length,depthPreserved:true,stableAllocations:true,
        antialiasSamples:view.layered.samples,note:'合成遮挡物＋纹理字形探针，仅验证不透明遮挡与字形绘制；真实视觉由用户判断'};
    }finally{
      annotation.remove(glyph);s.scene.remove(blocker);glyph.geometry.dispose();glyph.material.dispose();texture.dispose();blocker.geometry.dispose();blocker.material.dispose();
      for(const [o,v] of visible)o.visible=v;for(const [o,v] of children)o.visible=v;s.camera=camera;
      const selects={comparison:document.getElementById('comparison').value,ratio:document.getElementById('ratio-b').value,sceneRatio:document.getElementById('scene-ratio').value,filter:document.getElementById('filter-b').value};
      view.apply(profile,selects);renderLab.evidence();
    }
  }
  window.LayeredTests={run};
})();

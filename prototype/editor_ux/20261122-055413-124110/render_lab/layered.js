/* 单上下文分层实验：低分辨率颜色／深度 → 全屏合成 → 高清三维文字。只改变绘制路径。 */
(() => {
  'use strict';
  class Layered {
    constructor(owner){
      this.owner=owner;this.target=null;this.allocations=0;this.active=false;this.ratio=1.25;this.last=null;
      const r=owner.renderer,gl=r.getContext();this.supported=r.capabilities.isWebGL2;
      // 保持与整场景档相同的实际多重采样数，不把关闭抗锯齿的收益计入分层。
      this.samples=gl.getContextAttributes().antialias?Math.min(gl.getParameter(gl.SAMPLES),r.capabilities.maxSamples||0):0;
      this.direct=owner.render.bind(owner);owner.render=()=>this.render();
    }
    ensure(){
      const T=THREE,r=this.owner.renderer,size=r.getSize(new T.Vector2());
      const width=Math.max(1,Math.floor(size.x*this.ratio)),height=Math.max(1,Math.floor(size.y*this.ratio));
      if(Math.max(width,height)>r.capabilities.maxTextureSize)throw Error('离屏画布超过显卡纹理上限');
      if(!this.target){
        const Target=this.samples?T.WebGLMultisampleRenderTarget:T.WebGLRenderTarget;
        this.target=new Target(width,height,{format:T.RGBAFormat,type:T.UnsignedByteType,minFilter:T.LinearFilter,magFilter:T.LinearFilter,depthBuffer:true,stencilBuffer:false});
        this.target.texture.generateMipmaps=false;this.target.texture.encoding=r.outputEncoding;
        if(this.samples)this.target.samples=this.samples;
        this.target.depthTexture=new T.DepthTexture(width,height,T.UnsignedIntType);this.target.depthTexture.format=T.DepthFormat;
        this.target.depthTexture.minFilter=T.NearestFilter;this.target.depthTexture.magFilter=T.NearestFilter;
        this.material=new T.RawShaderMaterial({glslVersion:T.GLSL3,uniforms:{colorMap:{value:this.target.texture},depthMap:{value:this.target.depthTexture}},
          vertexShader:'precision highp float; in vec3 position; in vec2 uv; out vec2 vUv; void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}',
          fragmentShader:'precision highp float; uniform sampler2D colorMap; uniform sampler2D depthMap; in vec2 vUv; out vec4 outColor; void main(){outColor=texture(colorMap,vUv);gl_FragDepth=texture(depthMap,vUv).r;}',
          depthTest:true,depthFunc:T.AlwaysDepth,depthWrite:true,blending:T.NoBlending,toneMapped:false});
        this.quad=new T.Mesh(new T.PlaneGeometry(2,2),this.material);this.quad.frustumCulled=false;
        this.copyScene=new T.Scene();this.copyScene.add(this.quad);this.copyCamera=new T.Camera();this.allocations++;
      }else if(this.target.width!==width||this.target.height!==height){this.target.setSize(width,height);this.allocations++;}
      return this.target;
    }
    render(){
      if(!this.active||!this.supported){this.direct();this.last={pipeline:'uniform',passes:1,sceneRatio:this.owner.renderer.getPixelRatio(),allocations:this.allocations};return;}
      const s=this.owner,r=s.renderer,gl=r.getContext();if(gl.isContextLost())return;
      const target=this.ensure(),annotation=s.annotationView.group;
      const saved={target:r.getRenderTarget(),viewport:r.getViewport(new THREE.Vector4()),scissor:r.getScissor(new THREE.Vector4()),
        scissorTest:r.getScissorTest(),autoClear:r.autoClear,infoAutoReset:r.info.autoReset,background:s.scene.background,
        visible:s.scene.children.map(child=>[child,child.visible]),annotationVisible:annotation.visible};
      let drawCalls=0,triangles=0,points=0,lines=0;
      const count=()=>{const v=r.info.render;drawCalls+=v.calls;triangles+=v.triangles;points+=v.points;lines+=v.lines;};
      try{
        r.autoClear=false;r.info.autoReset=false;r.setScissorTest(false);
        annotation.visible=false;r.setRenderTarget(target);r.clear(true,true,true);r.info.reset();r.render(s.scene,s.camera);count();
        // r128在render结束时同时resolve多重采样颜色与深度，随后才能安全采样深度纹理。
        r.setRenderTarget(null);r.setViewport(0,0,r.getSize(new THREE.Vector2()).x,r.getSize(new THREE.Vector2()).y);
        r.clear(true,true,true);r.info.reset();r.render(this.copyScene,this.copyCamera);count();
        for(const [child] of saved.visible)child.visible=child===annotation?saved.annotationVisible:false;
        s.scene.background=null;r.info.reset();r.render(s.scene,s.camera);count();
        this.last={pipeline:'layered',passes:3,sceneRatio:this.ratio,sceneBuffer:[target.width,target.height],samples:this.samples,
          depth:'低分辨率深度最近邻传递；保留不透明几何遮挡，边缘为近似',color:'线性放大；透明结构先合成，文字最后绘制',allocations:this.allocations,drawCalls,triangles,points,lines};
      }finally{
        for(const [child,visible] of saved.visible)child.visible=visible;annotation.visible=saved.annotationVisible;s.scene.background=saved.background;
        r.setRenderTarget(saved.target);r.setViewport(saved.viewport);r.setScissor(saved.scissor);r.setScissorTest(saved.scissorTest);
        r.autoClear=saved.autoClear;r.info.autoReset=saved.infoAutoReset;
      }
      s.drawWorldAxes();
    }
    evidence(){
      const t=this.target,pixels=t?t.width*t.height:0;
      return {...this.last,residentBuffer:t?[t.width,t.height]:null,residentBytesEstimate:pixels*(8+this.samples*8),
        memoryNote:'仅RGBA8＋深度24/32及多重采样缓冲估算，不含默认画布、实例、纹理或驱动额外开销'};
    }
    dispose(){
      this.target?.dispose();this.quad?.geometry.dispose();this.material?.dispose();this.target=null;
    }
  }
  window.RenderLabLayered=Layered;
})();

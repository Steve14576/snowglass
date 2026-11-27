/* 主视口：适度分辨率色深缓冲＋高清文字。来自已核验的独立分层实验，不改工程几何。 */
(() => {
  'use strict';
  class PixelLayers {
    constructor(owner){
      this.owner=owner;this.target=null;this.allocations=0;this.active=true;this.ratio=1.25;this.last=null;
      const r=owner.renderer,gl=r.getContext();this.supported=r.capabilities.isWebGL2;
      this.samples=gl.getContextAttributes().antialias?Math.min(gl.getParameter(gl.SAMPLES),r.capabilities.maxSamples||0):0;
      this.direct=owner.render.bind(owner);owner.render=()=>this.render();
    }
    ensure(){
      const T=THREE,r=this.owner.renderer,size=r.getSize(new T.Vector2());
      const width=Math.max(1,Math.floor(size.x*Math.min(this.ratio,r.getPixelRatio()))),height=Math.max(1,Math.floor(size.y*Math.min(this.ratio,r.getPixelRatio())));
      if(Math.max(width,height)>r.capabilities.maxTextureSize)throw Error('离屏画布超过显卡纹理上限');
      if(!this.target){
        const Target=this.samples?T.WebGLMultisampleRenderTarget:T.WebGLRenderTarget;
        this.target=new Target(width,height,{format:T.RGBAFormat,type:T.UnsignedByteType,minFilter:T.LinearFilter,magFilter:T.LinearFilter,depthBuffer:true,stencilBuffer:false});
        this.target.texture.generateMipmaps=false;this.target.texture.encoding=r.outputEncoding;if(this.samples)this.target.samples=this.samples;
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
      const s=this.owner;s.progressive?.beforeRender();
      if(!this.active||!this.supported){this.direct();return;}
      const r=s.renderer,gl=r.getContext();if(gl.isContextLost())return;
      const target=this.ensure(),annotation=s.annotationView.group;
      const saved={target:r.getRenderTarget(),viewport:r.getViewport(new THREE.Vector4()),scissor:r.getScissor(new THREE.Vector4()),scissorTest:r.getScissorTest(),
        autoClear:r.autoClear,infoAutoReset:r.info.autoReset,background:s.scene.background,visible:s.scene.children.map(child=>[child,child.visible]),annotationVisible:annotation.visible};
      try{
        r.autoClear=false;r.info.autoReset=false;r.setScissorTest(false);
        annotation.visible=false;s.gumball.visible=false;s.highlights.visible=false;r.setRenderTarget(target);r.clear(true,true,true);r.render(s.scene,s.camera);
        r.setRenderTarget(null);const size=r.getSize(new THREE.Vector2());r.setViewport(0,0,size.x,size.y);r.clear(true,true,true);
        r.render(this.copyScene,this.copyCamera);
        // 手柄与选中高亮也留在高清层，沿用自身depthTest语义。
        for(const [child] of saved.visible)child.visible=[annotation,s.gumball,s.highlights].includes(child)?saved.visible.find(([v])=>v===child)[1]:false;
        s.scene.background=null;r.render(s.scene,s.camera);
        this.last={sceneBuffer:[target.width,target.height],finalRatio:r.getPixelRatio(),sceneRatio:Math.min(this.ratio,r.getPixelRatio()),samples:this.samples,allocations:this.allocations};
      }finally{
        for(const [child,visible] of saved.visible)child.visible=visible;annotation.visible=saved.annotationVisible;s.scene.background=saved.background;
        r.setRenderTarget(saved.target);r.setViewport(saved.viewport);r.setScissor(saved.scissor);r.setScissorTest(saved.scissorTest);r.autoClear=saved.autoClear;r.info.autoReset=saved.infoAutoReset;
      }
      s.drawWorldAxes();
    }
    dispose(){this.target?.dispose();this.quad?.geometry.dispose();this.material?.dispose();this.target=null;}
  }
  window.UXPixelLayers=PixelLayers;
})();

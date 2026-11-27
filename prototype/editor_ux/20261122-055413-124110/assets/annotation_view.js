/* 标签有两种表示：轻化时是固定朝向纹理平面，细化时是带灰度的字形挤出实体。
   实体与雪花小块同层（单位几何＋灰度），不做加工点化。 */
(() => {
  'use strict';
  class AnnotationView {
    constructor(scene){this.owner=scene;this.group=new THREE.Group();scene.scene.add(this.group);this.geometry=new THREE.PlaneGeometry(1,1);this.meshes=new Map();this.solids=new Map();this.textures=new Map();this.hits=[];this.detail='settle';this.moving=false;}
    // 三档显示精度：始终轻量只画贴图；停下后细化在拖动时贴图、静止时实体；始终完整始终实体。
    applyDetail(mode='settle',interacting=false){
      this.detail=mode;this.moving=!!interacting;
      const solid=mode==='always'||(mode==='settle'&&!this.moving);this.solidVisible=solid;this.hits=[];
      for(const mesh of this.meshes.values()){const on=!!mesh.userData.enabled&&!solid;mesh.visible=on;if(on)this.hits.push(mesh);}
      for(const item of this.solids.values()){
        const on=!!item.mesh.userData.enabled&&solid;
        // 几何惰性构建：只有真需要显示实体时才做轮廓与挤出，始终轻量档不付这份成本。
        if(on&&item.pendingKey&&item.key!==item.pendingKey){const built=UXGlyph.geometry(item.metric,item.depth);item.mesh.geometry.dispose();item.mesh.geometry=built.geometry||new THREE.BufferGeometry();item.key=item.pendingKey;}
        const usable=on&&!!item.mesh.geometry?.attributes?.position;item.mesh.visible=usable;if(usable)this.hits.push(item.mesh);
      }
    }
    release(key){const item=this.textures.get(key);if(item&&--item.users===0){item.texture.dispose();this.textures.delete(key);}}
    texture(metric){
      const ink='hsl('+getComputedStyle(document.documentElement).getPropertyValue('--ink').trim()+')',key=JSON.stringify([metric.text,metric.font,ink]);
      if(!this.textures.has(key)){
        const limit=this.owner.renderer.capabilities.maxTextureSize,ratio=Math.min(1,limit/metric.canvasWidth,limit/metric.canvasHeight),canvas=document.createElement('canvas');
        canvas.width=Math.max(1,Math.ceil(metric.canvasWidth*ratio));canvas.height=Math.max(1,Math.ceil(metric.canvasHeight*ratio));
        const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);ctx.font=metric.cssFont;ctx.textAlign='left';ctx.textBaseline='alphabetic';ctx.fillStyle=ink;
        ctx.fillText(metric.text,metric.padding+metric.left,metric.padding+metric.ascent);
        const texture=new THREE.CanvasTexture(canvas);texture.minFilter=THREE.LinearFilter;texture.generateMipmaps=false;
        this.textures.set(key,{texture,users:0});
      }
      const item=this.textures.get(key);item.users++;return {key,texture:item.texture};
    }
    update(){
      const s=this.owner,M=s.model,T=THREE,used=new Set(),selected=new Set(M.leaves(s.selected));this.hits=[];
      for(const n of M.nodes.values())if(n.type==='label'){
        const size=UXAnnotationMath.shape(M,n),key=JSON.stringify([size.metric.text,size.metric.font]);let mesh=this.meshes.get(n.id);
        if(!mesh){mesh=new T.Mesh(this.geometry,new T.MeshBasicMaterial({transparent:true,alphaTest:.01,depthWrite:false,side:T.FrontSide}));mesh.matrixAutoUpdate=false;mesh.userData.id=n.id;this.meshes.set(n.id,mesh);this.group.add(mesh);}
        if(mesh.userData.contentKey!==key){if(mesh.userData.textureKey)this.release(mesh.userData.textureKey);const item=this.texture(size.metric);mesh.material.map=item.texture;mesh.material.needsUpdate=true;mesh.userData.contentKey=key;mesh.userData.textureKey=item.key;}
        const factor=size.factor;
        mesh.matrix.copy(M.chain(n.id)).multiply(UXCoordinates.basis()).multiply(new T.Matrix4().makeScale(size.metric.canvasWidth*factor,size.metric.canvasHeight*factor,1));mesh.matrixWorldNeedsUpdate=true;
        mesh.userData.enabled=M.resolve(n.id,'labelEnabled').value;mesh.frustumCulled=false;used.add(n.id);
        // 带灰度的实体：字形轮廓挤出 labelDepth，颜色取 labelGray（与雪花同乘屏幕曝光）。
        const depth=M.resolve(n.id,'labelDepth').value,solidKey=JSON.stringify([size.metric.text,size.metric.font,depth]);
        let solid=this.solids.get(n.id);
        if(!solid){solid={mesh:new T.Mesh(new T.BufferGeometry(),new T.MeshBasicMaterial({depthWrite:true,side:T.DoubleSide})),key:null};solid.mesh.matrixAutoUpdate=false;solid.mesh.frustumCulled=false;solid.mesh.userData.id=n.id;this.solids.set(n.id,solid);this.group.add(solid.mesh);}
        solid.metric=size.metric;solid.depth=depth;solid.pendingKey=solidKey;
        const gray=Math.min(1,Math.max(0,M.resolve(n.id,'labelGray').value))*s.exposure;
        solid.mesh.material.color.setRGB(gray,gray,gray);
        solid.mesh.matrix.copy(mesh.matrix);solid.mesh.matrixWorldNeedsUpdate=true;
        solid.mesh.userData.enabled=mesh.userData.enabled;
        if(selected.has(n.id)&&mesh.userData.enabled){const edge=new T.LineSegments(new T.EdgesGeometry(this.geometry),new T.LineBasicMaterial({color:0xffd24a,depthTest:false}));edge.matrixAutoUpdate=false;edge.matrix.copy(M.world(n.id));s.highlights.add(edge);}
      }
      for(const [id,mesh] of this.meshes)if(!used.has(id)){this.group.remove(mesh);mesh.material.dispose();this.release(mesh.userData.textureKey);this.meshes.delete(id);}
      for(const [id,item] of this.solids)if(!used.has(id)){this.group.remove(item.mesh);item.mesh.geometry.dispose();item.mesh.material.dispose();this.solids.delete(id);}
      this.applyDetail(this.detail,this.moving);
    }
    pick(ray){this.group.updateMatrixWorld(true);return ray.intersectObjects(this.hits,false)[0]||null;}
  }
  window.UXAnnotationView=AnnotationView;
})();

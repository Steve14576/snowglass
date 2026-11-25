/* 固定朝向文字Mesh。纹理共享；视口转动只改变观察，不旋转标签平面。 */
(() => {
  'use strict';
  class AnnotationView {
    constructor(scene){this.owner=scene;this.group=new THREE.Group();scene.scene.add(this.group);this.geometry=new THREE.PlaneGeometry(1,1);this.meshes=new Map();this.textures=new Map();this.hits=[];}
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
        mesh.visible=M.resolve(n.id,'labelEnabled').value;mesh.frustumCulled=false;used.add(n.id);
        if(mesh.visible)this.hits.push(mesh);
        if(selected.has(n.id)&&mesh.visible){const edge=new T.LineSegments(new T.EdgesGeometry(this.geometry),new T.LineBasicMaterial({color:0xffd24a,depthTest:false}));edge.matrixAutoUpdate=false;edge.matrix.copy(M.world(n.id));s.highlights.add(edge);}
      }
      for(const [id,mesh] of this.meshes)if(!used.has(id)){this.group.remove(mesh);mesh.material.dispose();this.release(mesh.userData.textureKey);this.meshes.delete(id);}
    }
    pick(ray){this.group.updateMatrixWorld(true);return ray.intersectObjects(this.hits,false)[0]||null;}
  }
  window.UXAnnotationView=AnnotationView;
})();

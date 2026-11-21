/* 复用已核验的相机同步；本页各张量分区使用同一边长的小立方体。 */
(() => {
  'use strict';
  window.TypeSurveyScene = class {
    static async create(elements) {
      const base = await window.GrayScenes.create(elements);
      base.views.forEach(view => {
        view.scene.children.slice().forEach(obj => {
          view.scene.remove(obj);obj.geometry?.dispose();obj.material?.dispose();
        });
        view.controls.maxDistance = 500;
      });
      return new window.TypeSurveyScene(base);
    }
    constructor(base) { this.base=base;this.signature='';this.width=16;this.height=16; }
    update(pieces,options) {
      const T=window.THREE,cols=Math.min(3,pieces.length),rows=Math.ceil(pieces.length/cols);
      const step=1,spacingX=20,spacingY=20,signature=pieces.map(p=>p.id).join('|');
      this.width=cols*spacingX;this.height=rows*spacingY;
      this.base.views.forEach((view,column)=>{
        view.scene.children.slice().forEach(obj=>{
          view.scene.remove(obj);obj.geometry?.dispose();obj.material?.dispose();
        });
        const meshes=[];
        pieces.forEach((piece,index)=>{
          const dims=piece.grid,position=new T.Vector3((index%cols-(cols-1)/2)*spacingX,
            ((rows-1)/2-Math.floor(index/cols))*spacingY,0);
          const edgeColor=new T.Color(getComputedStyle(document.querySelector('.muted')).color);
          const frame=new T.LineSegments(new T.EdgesGeometry(new T.BoxGeometry(...dims)),
            new T.LineBasicMaterial({color:edgeColor,transparent:true,opacity:.25}));
          frame.position.copy(position);view.scene.add(frame);
          const additive=options.mode==='additive';
          const material=new T.MeshBasicMaterial({transparent:additive,opacity:additive ? .18 : 1,
            depthWrite:!additive,blending:additive?T.AdditiveBlending:T.NormalBlending});
          const values=piece.arrays[column],side=options.size*step;
          const mesh=new T.InstancedMesh(new T.BoxGeometry(side,side,side),material,values.length);
          const matrix=new T.Matrix4(),color=new T.Color();let count=0;
          const axis=options.axis,level=Math.min(dims[axis]-1,Math.round(options.slice*(dims[axis]-1)));
          for(let x=0;x<dims[0];x++)for(let y=0;y<dims[1];y++)for(let z=0;z<dims[2];z++){
            const i=(x*dims[1]+y)*dims[2]+z,g=values[i];
            if(g<=0||(options.slab&&[x,y,z][axis]!==level))continue;
            matrix.makeTranslation(x+.5-dims[0]/2+position.x,y+.5-dims[1]/2+position.y,z+.5-dims[2]/2);
            mesh.setMatrixAt(count,matrix);mesh.setColorAt(count,color.setRGB(g,g,g));count++;
          }
          mesh.count=count;mesh.instanceMatrix.needsUpdate=true;
          if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;
          mesh.frustumCulled=false;view.scene.add(mesh);meshes.push(mesh);
        });
        view.meshes=meshes;
      });
      if(signature!==this.signature){this.signature=signature;this.fit();}
      this.base.render();
    }
    fit() {
      const view=this.base.views[0];
      const distance=Math.max(this.width,this.height,32)*2.5;
      view.camera.position.set(distance*.45,distance*.3,distance);
      view.controls.target.set(0,0,0);view.controls.update();this.base.synchronize(view);
    }
    get views(){return this.base.views;}
  };
})();

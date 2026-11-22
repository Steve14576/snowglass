/* 只载入独立复制的已完成统计。没有计算接口，不制造未计算纹理。 */
(() => {
  'use strict';
  const clip=CurveMath.clip;
  function region(index,total){
    const cols=Math.min(3,total),rows=Math.ceil(total/cols),width=.90/cols,height=.90/rows;
    return {min:[-.45+(index%cols)*width+.03*width,-.45+Math.floor(index/cols)*height+.03*height,-.44],
      size:[width*.94,height*.94,.88]};
  }
  function position(piece,i){const d=piece.grid,r=piece.region,x=Math.floor(i/(d[1]*d[2])),y=Math.floor(i/d[2])%d[1],z=i%d[2];
    return [x,y,z].map((v,a)=>r.min[a]+(v+.5)*r.size[a]/d[a]);}
  class Data {
    constructor(manifest){this.manifest=manifest;this.groups=new Map(manifest.blocks.map(b=>[b.id,b]));this.tensors=new Map(manifest.tensors.map(t=>[t.key,t]));this.cache=new Map();this.luts=new Map();this.evaluated=new Map();}
    async tensor(ref){
      const key=ref.file+':'+ref.gguf;if(!this.cache.has(key)){
        const index=this.tensors.get(key);if(!index)throw Error('缺少已完成张量 '+key);
        const response=await fetch('data/tensors/'+index.data_file,{cache:'no-store'});if(!response.ok)throw Error('统计载入失败 '+response.status);
        const t=await response.json();if(t.key!==key||!t.parts?.length)throw Error('张量缓存身份无效');this.cache.set(key,t);
      }return this.cache.get(key);
    }
    async evaluate(id,model){
      const group=this.groups.get(id);if(!group)return {id,status:id==='mtp'?'权重未收录':'该层尚未计算',pieces:[],count:0,positive:0};
      const tensors=await Promise.all(group.tensors.map(t=>this.tensor(t)));
      const keys=['channel','windowMode','black','white','curve','filter','cutoff'];
      const p=Object.fromEntries(keys.map(k=>[k,model.resolve(id,k).value])),signature=JSON.stringify(p);
      if(p.white<=p.black)throw Error('白端必须高于黑端，保留上一个有效设置');
      if(this.evaluated.get(id)?.signature===signature)return this.evaluated.get(id);
      const curveKey=JSON.stringify(p.curve);if(!this.luts.has(curveKey)){this.luts.set(curveKey,CurveMath.table(p.curve));if(this.luts.size>32)this.luts.delete(this.luts.keys().next().value);}const lut=this.luts.get(curveKey);
      let pieces=[],count=0,positive=0,masked=0,sourceZeros=0,caveats=[];
      for(const t of tensors)for(const part of t.parts){
        let used=p.channel;if(!part[used]){used='full';caveats.push(t.name+'：所选统计不适用，使用完整幅度');}
        if(used==='feature'&&t.spectral.method==='direct')caveats.push(t.name+'：谱不适用，特征为直接幅度');
        if(used==='feature'&&t.spectral.rank_capped)caveats.push(t.name+'：谱方向达到原批次上限，仍为截断结果');
        const w=t.windows[used],raw=part[used],gray=new Float64Array(raw.length),mask=new Uint8Array(raw.length),reference=t.reference_white;
        for(let i=0;i<raw.length;i++){
          const u=p.windowMode==='range'&&w.high>w.low?(raw[i]-w.low)/(w.high-w.low):(reference>0?raw[i]/reference:0);
          const x=clip((u-p.black)/(p.white-p.black)),keep=!p.filter||x>p.cutoff;
          gray[i]=keep?CurveMath.lookup(lut,x):0;mask[i]=keep?1:0;
          count++;if(gray[i]>0)positive++;if(!keep)masked++;if(raw[i]===0)sourceZeros++;
        }
        if(w.constant)caveats.push(t.name+'：源统计恒定，不增加随机纹理');
        pieces.push({name:part.name,tensor:t.name,key:t.key,used,grid:part.grid,raw,gray,mask,counts:part.counts,window:w,reference,
          data_sha256:this.tensors.get(t.key).data_sha256,spectral:t.spectral});
      }
      pieces.forEach((p,i)=>p.region=region(i,pieces.length));
      const result={id,signature,settings:p,status:'真实统计已载入',pieces,count,positive,masked,sourceZeros,caveats:[...new Set(caveats)],lut_size:lut.length};
      this.evaluated.set(id,result);return result;
    }
    async mapping(ids,model){
      const results=[];
      for(const id of model.leaves(ids).filter(id=>model.nodes.get(id).type==='block')){
        const r=await this.evaluate(id,model);
        const node=model.nodes.get(id),center=model.bounds([id]).getCenter(new THREE.Vector3()).toArray();
        const label={text:model.resolve(id,'labelText').value||node.name,font:model.resolve(id,'labelFont').value,
          size_mm:model.resolve(id,'labelSize').value,offset_mm:[model.resolve(id,'labelDx').value,model.resolve(id,'labelDy').value,model.resolve(id,'labelDz').value],
          anchor_world_mm:center,output:model.resolve(id,'labelOutput').value,screen_only:!model.resolve(id,'labelOutput').value,
          orientation:'屏幕贴片朝镜头；导出需固定朝向，未核实',glyph_geometry:'未接入'};
        results.push({id,status:r.status,include_in_work:model.resolve(id,'include').value,label,matrix_mm:model.world(id).toArray(),snow_size_mm:model.resolve(id,'snowSize').value,
          statistics_source:this.manifest.source_run,settings:r.settings||null,
          pieces:r.pieces.map(p=>({tensor:p.key,name:p.name,channel:p.used,grid:p.grid,region:p.region,gray:Array.from(p.gray),mask:Array.from(p.mask),
            counts:p.counts,window:p.window,reference_white:p.reference,data_sha256:p.data_sha256}))});
      }
      return {kind:'snowglass.ux-gray-mapping.v1',created_at:new Date().toISOString(),source_run:this.manifest.source_run,
        topology_sha256:model.provenance.topology_sha256,manifest_sha256:model.provenance.manifest_sha256,
        approximation:{lut_size:4097,lookup:'linear',note:'贝塞尔数值映射使用查找表近似；预览与此文件共用同一求值规则'},
        label_pipeline:'文字定义已随结果输出；字形几何、固定朝向与厂家读取契约尚未接入，本文件不是可加工文字。',
        disclaimer:'这是统计与灰度映射记录，不是已核实的厂家加工文件；未计算块没有补模拟数据。',results};
    }
  }
  window.UXData={Data,position,region};
})();

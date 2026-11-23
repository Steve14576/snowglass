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
    constructor(manifest){this.manifest=manifest;this.groups=new Map(manifest.blocks.map(b=>[b.id,b]));this.tensors=new Map();this.providers=new Map();this.cache=new Map();this.combined=new Map();this.luts=new Map();this.evaluated=new Map();manifest.tensors.forEach(t=>this.register({...t,source_run:manifest.source_run}));}
    compatibility(index){return JSON.stringify([index.grid||[16,16,32],index.sourceConvention||'hf']);}
    desired(id,model){return JSON.stringify([['gridX','gridY','gridZ'].map(k=>model.resolve(id,k).value),model.resolve(id,'sourceConvention').value]);}
    register(index){
      const key=index.key,compat=this.compatibility(index);if(!this.providers.has(key))this.providers.set(key,new Map());
      const variants=this.providers.get(key);if(!variants.has(compat))variants.set(compat,{});let providers=variants.get(compat);
      if(providers.full?.packed_sha256&&index.packed_sha256&&providers.full.packed_sha256!==index.packed_sha256){providers={};variants.set(compat,providers);}
      for(const c of ['full','feature','residual','rowcol'])if(!index.channel_status||['ready','not_applicable'].includes(index.channel_status[c]))providers[c]=index;
      if(index.extraDiagnostics!==false)providers.signed=index;
      this.tensors.set(key,index);this.combined.clear();
    }
    sources(ref,id,model){
      const key=ref.file+':'+ref.gguf,variants=this.providers.get(key);if(!variants)return null;
      const desired=id&&model?this.desired(id,model):this.compatibility(this.tensors.get(key));
      return {providers:variants.get(desired)||variants.get(this.compatibility(this.tensors.get(key))),matched:variants.has(desired)};
    }
    fresh(id,model){
      const group=this.groups.get(id);if(!group)return false;const channel=model.resolve(id,'channel').value;
      return group.tensors.every(ref=>{const s=this.sources(ref,id,model);const same=index=>!!index&&(!s.providers.full?.packed_sha256||!index.packed_sha256||index.packed_sha256===s.providers.full.packed_sha256);return s?.matched&&same(s.providers[channel])&&(!model.resolve(id,'extraDiagnostics').value||same(s.providers.signed));});
    }
    merge(manifest){
      if(!Array.isArray(manifest.blocks)||!Array.isArray(manifest.tensors))throw Error('切片清单无效');
      const completeKeys=new Set(manifest.blocks.flatMap(b=>b.tensors.map(t=>t.file+':'+t.gguf)));
      for(const t of manifest.tensors.filter(t=>completeKeys.has(t.key)))this.register({...t,source_run:manifest.source_run});
      for(const b of manifest.blocks){this.groups.set(b.id,b);this.evaluated.delete(b.id);}
      this.manifest={...this.manifest,blocks:[...this.groups.values()],tensors:[...this.tensors.values()],
        source_runs:[...new Set([...(this.manifest.source_runs||[this.manifest.source_run]),manifest.source_run])]};
    }
    async file(index,key){
      const url=index.url||('data/tensors/'+index.data_file);
      if(!this.cache.has(url)){const response=await fetch(url,{cache:'no-store'});if(!response.ok)throw Error('统计载入失败 '+response.status);
        const t=await response.json();if(t.key!==key||!t.parts?.length)throw Error('张量缓存身份无效');this.cache.set(url,t);}
      const t=this.cache.get(url);if(t.packed_sha256)index.packed_sha256=t.packed_sha256;return t;
    }
    async tensor(ref,model=null,id=null){
      const key=ref.file+':'+ref.gguf,s=this.sources(ref,id,model);if(!s)throw Error('缺少已完成张量 '+key);
      const channel=id&&model?model.resolve(id,'channel').value:'full',providers=s.providers;
      if(!providers[channel])throw Error(key+'：所选统计尚未生成，请点击一级切片；不会用full冒充。');
      const diagnostic=id&&model&&model.resolve(id,'extraDiagnostics').value?providers.signed:null;
      const signature=JSON.stringify([key,channel,providers.full.data_sha256,providers[channel].data_sha256,diagnostic?.data_sha256,s.matched]);
      if(this.combined.has(signature))return this.combined.get(signature);
      const full=await this.file(providers.full,key),chosen=await this.file(providers[channel],key),diag=diagnostic?await this.file(diagnostic,key):null;
      if(full.packed_sha256!==chosen.packed_sha256){delete providers[channel];throw Error('通道来自不同原张量，拒绝混用，请重新切片。');}
      if(diag&&diag.packed_sha256!==full.packed_sha256){delete providers.signed;throw Error('诊断来自不同原张量，请重新切片。');}
      const parts=full.parts.map(p=>{const c=chosen.parts.find(v=>v.name===p.name);if(!c||JSON.stringify(c.grid)!==JSON.stringify(p.grid)||p.counts.some((v,i)=>v!==c.counts[i]))throw Error('通道网格或合并计数不匹配');return {...p,[channel]:c[channel]};});
      const t={...full,parts,windows:{...full.windows,[channel]:chosen.windows[channel]},statistics:diag?.statistics||full.statistics,
        spectral:['feature','residual'].includes(channel)?chosen.spectral:full.spectral,actualConvention:providers.full.sourceConvention||'hf',
        matched:s.matched,channel_hashes:{full:providers.full.data_sha256,[channel]:providers[channel].data_sha256},
                channel_runs:{full:providers.full.source_run,[channel]:providers[channel].source_run}};
      this.combined.set(signature,t);return t;
    }
    async evaluate(id,model){
      const group=this.groups.get(id);if(!group)return {id,status:id==='mtp'?'权重未收录':'该层尚未计算',pieces:[],count:0,positive:0};
      const tensors=await Promise.all(group.tensors.map(t=>this.tensor(t,model,id)));
      const keys=['channel','sourceConvention','extraDiagnostics','gridX','gridY','gridZ','windowMode','black','white','curve','filter','cutoff'];
      const p=Object.fromEntries(keys.map(k=>[k,model.resolve(id,k).value])),signature=JSON.stringify(p);
      if(p.white<=p.black)throw Error('白端必须高于黑端，保留上一个有效设置');
      if(this.evaluated.get(id)?.signature===signature)return this.evaluated.get(id);
      const curveKey=JSON.stringify(p.curve);if(!this.luts.has(curveKey)){this.luts.set(curveKey,CurveMath.table(p.curve));if(this.luts.size>32)this.luts.delete(this.luts.keys().next().value);}const lut=this.luts.get(curveKey);
      let pieces=[],count=0,positive=0,masked=0,sourceZeros=0,caveats=[];
      for(const t of tensors){if(!t.matched)caveats.push(t.name+'：当前展示既有旧约定／网格统计，尚未应用选定计算设置。');}
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
          data_sha256:t.channel_hashes[used],source_convention:t.actualConvention,source_run:t.channel_runs[used],spectral:t.spectral});
      }
      pieces.forEach((p,i)=>p.region=region(i,pieces.length));
      const result={id,signature,settings:p,status:tensors.every(t=>t.matched)?'真实统计已载入':'既有旧约定／网格结果（待切片）',pieces,count,positive,masked,sourceZeros,caveats:[...new Set(caveats)],lut_size:lut.length};
      this.evaluated.set(id,result);return result;
    }
    async mapping(ids,model){
      const results=[];
      for(const id of model.leaves(ids).filter(id=>model.nodes.get(id).type==='block')){
        const group=this.groups.get(id);if(group&&group.tensors.some(ref=>!this.sources(ref,id,model)?.matched))throw Error(id+'：选定约定／网格尚未生成，不保存旧数据冒充当前设置。');
        const r=await this.evaluate(id,model);
        const node=model.nodes.get(id),center=model.bounds([id]).getCenter(new THREE.Vector3()).toArray();
        const label={text:model.resolve(id,'labelText').value||node.name,font:model.resolve(id,'labelFont').value,
          size_mm:model.resolve(id,'labelSize').value,offset_mm:[model.resolve(id,'labelDx').value,model.resolve(id,'labelDy').value,model.resolve(id,'labelDz').value],
          anchor_world_mm:center,output:model.resolve(id,'labelOutput').value,screen_only:!model.resolve(id,'labelOutput').value,
          orientation:'屏幕贴片朝镜头；导出需固定朝向，未核实',glyph_geometry:'未接入'};
        results.push({id,status:r.status,include_in_work:model.resolve(id,'include').value,label,matrix_mm:model.world(id).toArray(),snow_size_mm:model.resolve(id,'snowSize').value,
          statistics_source:this.groups.get(id)?.slice_signature||this.manifest.source_run,settings:r.settings||null,
          pieces:r.pieces.map(p=>({tensor:p.key,name:p.name,channel:p.used,grid:p.grid,region:p.region,gray:Array.from(p.gray),mask:Array.from(p.mask),
            counts:p.counts,window:p.window,reference_white:p.reference,data_sha256:p.data_sha256,source_convention:p.source_convention,source_run:p.source_run}))});
      }
      return {kind:'snowglass.ux-gray-mapping.v1',coordinateSystem:UXCoordinates.SYSTEM,localGeometryBasis:UXCoordinates.GEOMETRY,created_at:new Date().toISOString(),source_run:this.manifest.source_run,
        topology_sha256:model.provenance.topology_sha256,manifest_sha256:model.provenance.manifest_sha256,
        source_runs:this.manifest.source_runs||[this.manifest.source_run],
        approximation:{lut_size:4097,lookup:'linear',note:'贝塞尔数值映射使用查找表近似；预览与此文件共用同一求值规则'},
        annotations:model.annotations(ids),
        label_pipeline:'独立标注带固定世界位姿；旧块标签仍为屏幕贴片。字形轮廓与厂家读取契约未接入，本文件不是可加工文字。',
        disclaimer:'这是统计与灰度映射记录，不是已核实的厂家加工文件；未计算块没有补模拟数据。',results};
    }
  }
  window.UXData={Data,position,region};
})();

/* 本机一级切片任务控制。参数快照与已有结果分开，改灰度／几何不触发权重计算。 */
(() => {
  'use strict';
  const $=id=>document.getElementById(id),defaults=[16,16,32];
  class Slicing {
    constructor(model,data,callbacks){
      this.model=model;this.data=data;this.callbacks=callbacks;this.online=false;this.token='';this.active=null;
      this.tasks=[];this.pollTimer=null;this.polling=false;this.errors=0;this.last=null;
      $('slice-1').onclick=()=>this.start();
      $('slice-cancel').onclick=()=>this.cancel();
      $('slice-scope').onchange=()=>this.render();
      model.listeners.push(()=>this.render());
    }
    blocks(scope='work'){
      const ids=scope==='selected'?this.callbacks.selected():['work'];
      return this.model.leaves(ids).filter(id=>this.model.nodes.get(id)?.type==='block'&&id!=='mtp'&&this.model.resolve(id,'include').value);
    }
    grid(id){return ['gridX','gridY','gridZ'].map(k=>this.model.resolve(id,k).value);}
    fresh(id){return this.data.fresh(id,this.model);}
    requestFor(id){return {id,grid:this.grid(id),source:this.model.resolve(id,'channel').value,
      convention:this.model.resolve(id,'sourceConvention').value,diagnostics:this.model.resolve(id,'extraDiagnostics').value};}
    summary(){const ids=this.blocks();return {total:ids.length,ready:ids.filter(id=>this.fresh(id)).length};}
    render(){
      const button=$('slice-1'),scope=$('slice-scope').value,ids=this.blocks(scope),pending=ids.some(id=>!this.fresh(id));
      const preview=this.callbacks.view()==='preview';
      button.disabled=!this.online||!!this.active||!ids.length||(preview&&!pending);
      button.textContent=this.active?'切片中…':'一级切片';
      button.title=!this.online?'请用本机计算服务启动；静态预览不能执行 Python':this.active?'任务正在运行':
        pending?'统计来源、约定或网格尚未生成；点击切片按需计算':'当前范围所需统计匹配，无需重新切片';
      $('slice-scope').disabled=!!this.active;
      $('view-prepare').disabled=!!this.active;$('view-preview').disabled=!!this.active;
      const s=this.summary(),badge=$('slice-state');
      badge.textContent=this.active?'计算任务进行中':`${s.ready}/${s.total} 块统计匹配`+(s.ready<s.total?' · 待切片':'');
      badge.classList.toggle('warning',s.ready<s.total);
    }
    async api(path,body){
      const response=await fetch('/api/slice1/'+path,{cache:'no-store',method:body?'POST':'GET',
        headers:body?{'Content-Type':'application/json','X-Snowglass-Token':this.token}:{},
        ...(body?{body:JSON.stringify(body)}:{})});
      const content=await response.json();
      if(!response.ok)throw Error(content.error||'计算服务 HTTP '+response.status);
      return content;
    }
    async initialize(doc){
      try{
        const capabilities=await this.api('capabilities');
        if(capabilities.kind!=='snowglass.slice1-service.v1'||capabilities.recipe!=='on-demand-v1')throw Error('本机服务尚未更新到可选处理版本，请重启服务；不会启动旧预算管线');
        this.token=capabilities.token;this.online=true;
        await this.restore(doc);
        if(capabilities.active){this.active=capabilities.active;this.poll();}
      }catch(e){this.callbacks.message('当前仅静态预览；一级切片服务不可用：'+e.message);}
      this.render();
    }
    async restore(doc){
      for(const id of doc?.slice?.tasks||[]){
        if(typeof id!=='string'||!/^slice-[0-9-]+$/.test(id))throw Error('工程切片编号无效');
        if(this.tasks.includes(id))continue;
        const manifest=await this.api('jobs/'+id+'/manifest');
        this.install(manifest,id);
      }
    }
    install(manifest,id){
      if(manifest.schema!=='snowglass.slice1.v1'||manifest.topology_sha256!==this.model.provenance.topology_sha256)
        throw Error('切片结果与当前拓扑不匹配');
      this.data.merge(manifest);
      if(!this.tasks.includes(id))this.tasks.push(id);
    }
    snapshot(){return {tasks:this.tasks.slice(),active:this.active};}
    async start(){
      if(!this.online||this.active)return;
      try{
        const ids=this.blocks($('slice-scope').value),request={blocks:ids.map(id=>this.requestFor(id))};
        const plan=await this.api('plan',request);
        if(!await this.callbacks.confirm('执行一级切片',
          `本次范围：${plan.block_count} 个块，${plan.tensor_count} 个张量。\n`+
          `按快照计算：谱来源 ${request.blocks.filter(b=>['feature','residual'].includes(b.source)).length} 块；行列来源 ${request.blocks.filter(b=>b.source==='rowcol').length} 块；额外诊断 ${request.blocks.filter(b=>b.diagnostics).length} 块。\n`+
          'full只做直接池化；谱来源才运行SVD。GGUF原值／HF约定按各块选项处理。大张量仍需分块读取。\n'+
          plan.note+'\n'+
          '新结果另存 out/slices；匹配的完成张量复用，旧缓存不覆盖。\n'+
          '网格记录的是分区各轴上限，实际合并数保存在 counts；包络、灰度和小块毫米尺寸不参加重算。'))return;
        const job=await this.api('start',request);this.active=job.id;this.last=job;this.errors=0;
        this.render();this.poll();
      }catch(e){this.callbacks.message('切片未启动：'+e.message);}
    }
    async poll(){
      if(!this.active||this.polling)return;
      this.polling=true;
      try{
        const status=await this.api('jobs/'+this.active+'/status');this.last=status;this.errors=0;
        this.callbacks.progress(status.completed+status.failed,status.total,
          `${status.stage} · ${status.completed}/${status.total} 张量 · 复用 ${status.reused||0} · 失败 ${status.failed||0}`);
        $('progress-note').textContent=(status.tensor||'')+' · 已用 '+(status.elapsed_seconds||0)+' 秒；10秒心跳，取消会保留已完成统计。';
        $('slice-cancel').hidden=false;
        if(['complete','partial','cancelled','failed','interrupted'].includes(status.state)){
          const id=this.active;this.active=null;$('slice-cancel').hidden=true;
          if(status.manifest_url){
            const manifest=await this.api('jobs/'+id+'/manifest');
            if(manifest.blocks.length){this.install(manifest,id);await this.callbacks.dataChanged(status.state==='complete');}
            if(status.state==='complete'){
              this.callbacks.message(`一级切片完成：${manifest.blocks.length} 块，${status.total} 张量；复用 ${status.reused||0}。`);
              await this.callbacks.preview();
            }else this.callbacks.message(`任务${status.state==='cancelled'?'已取消':'部分完成'}：成功块已保留；再次执行会校验后复用。`);
          }else this.callbacks.message('任务未完成：'+(status.error||status.stage)+'；旧结果保留。');
          this.callbacks.hideProgress();this.render();return;
        }
      }catch(e){
        this.errors++;this.callbacks.message('任务连接中断：'+e.message+'；计算不因页面断线而停止，正在重连。');
      }finally{this.polling=false;}
      if(this.active)this.pollTimer=setTimeout(()=>this.poll(),this.errors?3000:1000);
    }
    async cancel(){
      try{await this.api('jobs/'+this.active+'/cancel',{});$('slice-cancel').hidden=true;}
      catch(e){this.callbacks.message('取消失败：'+e.message);}
    }
  }
  window.UXSlicing=Slicing;
})();

/* 只读主工程和已完成统计；不实例化切片客户端，不请求任何计算接口。 */
(() => {
  'use strict';
  const storageKeys=['snowglass.editor-ux.20261122-055413-124110.v3-zup','snowglass.editor-ux.20261122-055413-124110.v2'];
  const root=new URL('.',document.baseURI),pause=()=>new Promise(resolve=>setTimeout(resolve,0));
  async function json(path){
    const url=new URL(path,root);if(url.origin!==location.origin)throw Error('仅允许同源工程与统计');
    const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(30000)});
    if(!response.ok)throw Error(url.pathname+' HTTP '+response.status);return response.json();
  }
  async function libraries(message){
    for(const path of ['build/three.min.js','examples/js/controls/OrbitControls.js','examples/js/controls/TransformControls.js']){
      let loaded=false;
      for(const base of ['https://cdn.jsdelivr.net/npm/three@0.128.0/','https://unpkg.com/three@0.128.0/']){
        message('加载与主文件相同的三维依赖：'+path);
        try{await new Promise((resolve,reject)=>{
          const script=document.createElement('script');script.src=base+path;
          const timer=setTimeout(()=>{script.remove();reject(Error('三维依赖超时'));},10000);
          script.onload=()=>{clearTimeout(timer);resolve();};script.onerror=()=>{clearTimeout(timer);script.remove();reject(Error('三维依赖不可用'));};document.head.append(script);
        });loaded=true;break;}catch(e){/* 单项最多尝试两处源，不无限重试。 */}
      }
      if(!loaded)throw Error('无法加载 '+path+'；请检查网络后刷新。');
    }
  }
  function stored(){
    for(const key of storageKeys){const raw=localStorage.getItem(key);if(raw)return {doc:JSON.parse(raw),name:'主页面自动保存（'+location.host+'）',key};}
    return null;
  }
  /* 只读列举任务编号与进度；用于在没有工程引用时找出已完成的全量切片。 */
  async function jobList(){
    const value=await json('/api/slice1/jobs');if(!Array.isArray(value.jobs))throw Error('任务清单格式无效');return value.jobs;
  }
  class Source {
    constructor(topo,manifest,provenance){Object.assign(this,{topo,manifest,provenance});}
    async open(doc,name,progress){
      const model=new UXModel.Model(this.topo,this.provenance),data=new UXData.Data(this.manifest),warnings=[],tasks=[];
      const prepared=doc?UXCoordinates.prepare(doc):null;if(prepared){model.validate(prepared);model.restore(prepared);}
      if(prepared?.slice?.tasks!==undefined&&!Array.isArray(prepared.slice.tasks))throw Error('工程切片引用必须是任务编号清单');
      const refs=[...new Set(prepared?.slice?.tasks||[])];
      if(refs.length>256||refs.some(id=>typeof id!=='string'||!/^slice-[0-9-]+$/.test(id)))throw Error('工程切片引用无效');
      for(let i=0;i<refs.length;i++){
        progress(i,refs.length,'只读恢复切片结果 '+refs[i]);
        try{
          const manifest=await json('/api/slice1/jobs/'+refs[i]+'/manifest');
          if(manifest.schema!=='snowglass.slice1.v1'||manifest.topology_sha256!==this.provenance.topology_sha256)throw Error('切片拓扑不匹配');
          data.merge(manifest);tasks.push(refs[i]);
        }catch(e){warnings.push(refs[i]+' 未恢复：'+e.message);}
      }
      // 工程没有引用任何任务时，只读挑出已完成且张量数最多的那一个；不启动、不续跑。
      let autoTask=null,autoNote='';
      if(!tasks.length){
        try{
          const ranked=(await jobList()).filter(j=>['complete','partial'].includes(j.state)&&Number(j.completed)>0)
            .sort((a,b)=>(b.completed||0)-(a.completed||0)||(a.id<b.id?1:-1));
          if(!ranked.length)autoNote='本机没有已完成的一级切片任务';
          for(const job of ranked.slice(0,3)){
            if(tasks.length)break;
            try{
              const manifest=await json('/api/slice1/jobs/'+job.id+'/manifest');
              if(manifest.schema!=='snowglass.slice1.v1'||manifest.topology_sha256!==this.provenance.topology_sha256)throw Error('切片拓扑不匹配');
              data.merge(manifest);tasks.push(job.id);autoTask=job.id;
            }catch(e){warnings.push('自动读取 '+job.id+' 失败：'+e.message);}
          }
        }catch(e){autoNote='未读到任务清单：'+e.message;}
      }
      return {model,data,doc:prepared,name,origin:location.origin,tasks,warnings,results:[],autoTask,autoNote};
    }
    async evaluate(state,scope,progress){
      if(scope==='none')return {results:[],failures:[],requested:0};
      const {model,data}=state;let ids=[...data.groups.keys()].filter(id=>model.nodes.get(id)?.type==='block');
      if(scope==='selected'&&state.doc){
        const chosen=(state.doc?.view?.selected||[]).filter(id=>model.nodes.has(id)),members=new Set();
        for(const id of chosen)for(const leaf of model.leaves([id])){
          const n=model.nodes.get(leaf);if(n.type==='block')members.add(leaf);if(n.type==='label')n.data.members.forEach(v=>members.add(v));
        }
        ids=ids.filter(id=>members.has(id));
      }
      const loaded=new Array(ids.length),failures=[],queue=ids.map((id,i)=>({id,i}));let done=0;
      await Promise.all(Array.from({length:Math.min(6,ids.length)},async()=>{
        while(queue.length){const {id,i}=queue.shift();
          try{loaded[i]=await data.evaluate(id,model);}catch(e){failures.push(id+'：'+e.message);}
          progress(++done,ids.length,`载入已切片统计 ${done} / ${ids.length} 块；没有读取原权重`);await pause();
        }
      }));
      return {results:loaded.filter(Boolean),failures,requested:ids.length};
    }
  }
  window.RenderLabIO={json,libraries,stored,jobList,Source,storageKeys,pause};
})();

/* 已完成统计的读取／JSON解析移到工作线程；不访问GGUF，不执行池化或谱计算。 */
'use strict';
self.onmessage=async event=>{
  const {id,url,key}=event.data;
  try{
    const target=new URL(url,self.location.href);if(target.origin!==self.location.origin)throw Error('统计必须同源');
    const response=await fetch(target,{cache:'no-store',signal:AbortSignal.timeout(30000)});
    if(!response.ok)throw Error('统计载入失败 '+response.status);
    const value=await response.json();if(value.key!==key||!value.parts?.length)throw Error('张量缓存身份无效');
    const buffers=[];
    for(const part of value.parts)for(const name of ['full','signed','feature','residual','rowcol'])if(Array.isArray(part[name])){
      // 保持JS Number的双精度，不改变源统计值；传输缓冲避免再克隆整套数值数组。
      const data=new Float64Array(part[name]);part[name]=data;buffers.push(data.buffer);
    }
    self.postMessage({id,value},buffers);
  }catch(error){self.postMessage({id,error:error.message});}
};

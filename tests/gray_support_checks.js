/* 在 ?study=support 页执行；检查后恢复设置，不写主编辑器工程。 */
(async()=>{
  'use strict';
  const app=window.graySampleTest,math=window.GraySupport,saved={...app.state.settings},passed=[];
  const assert=(ok,text)=>{if(!ok)throw new Error(text);};
  const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
  try{
    assert(app.supportStudy,'需要区域选取模式');
    document.getElementById('reset').click();
    assert(app.state.support.info.retained===2096,'注意力基准掩膜不一致');
    assert(app.state.support.info.componentCount===23&&app.state.support.info.largest.cells===1840,'空间连通统计错误');
    passed.push('注意力默认掩膜与 Python 缓存分析一致');
    const fixture=await(await fetch('data/gray_samples/support-20261121-214004-601105/fixture.json')).json();
    const f=math.calculate(fixture.values,1,fixture.dims,.2,1,1);
    assert(f.info.retained===fixture.expected.retained&&f.info.componentCount===fixture.expected.component_count,'六邻接跨语言不一致');
    assert(same(f.info.axisCounts,fixture.expected.axis_counts),'各轴分布不一致');
    assert(math.calculate([.25,.3],1,[1,1,2],.25,1,1).info.retained===1,'门槛等号语义错误');
    passed.push('六邻接、逐层计数与严格门槛跨语言一致');
    const before=app.state.support.mask.slice(),gray=app.state.arrays[2].slice();
    app.set({gain:4,gamma:.7});
    assert(same(before,app.state.support.mask),'曝光或幂次改变了入选位置');
    assert(!same(gray,app.state.arrays[2]),'曝光没有改变输出灰度');
    passed.push('曝光／幂次与入选位置解耦');
    const rawHash=JSON.stringify(app.samples.attention.channels);
    app.set({gain:1,gamma:1,cutoff:.25});
    for(let i=0;i<app.state.arrays[0].length;i++){
      const kept=app.state.support.mask[i];
      assert(app.state.arrays[1][i]===kept,'位置图不等于掩膜');
      assert(app.state.arrays[2][i]===(kept?app.state.arrays[0][i]:0),'保留格灰度被扣门槛或改变');
    }
    assert(JSON.stringify(app.samples.attention.channels)===rawHash,'改写了源统计');
    passed.push('入选格保留同一原值灰度、源统计不变');
    app.set({cutoff:.24});const a=app.state.support.info.retained;
    app.set({cutoff:.26});const b=app.state.support.info.retained;
    assert(a===2640&&b===1582,'相邻门槛计数错误');
    passed.push('门槛敏感性与 Python 一致');
    app.set({tensor:'mlp',cutoff:.25});
    assert(app.state.support.info.retained===0&&app.state.support.neighbor.upperJaccard===null,'空掩膜错误或被冒充稳定');
    assert(document.getElementById('support-summary').textContent.includes('没有选中任何格子'),'缺少空结果提示');
    assert(app.state.statistics[0].positive===8192,'基线不应随掩膜消失');
    app.set({cutoff:.1});assert(app.state.support.info.retained===2256,'MLP 门槛切换错误');
    passed.push('MLP 空结果与手动恢复，无自动改门槛');
    app.set({tensor:'attention',resolution:'coarse',cutoff:.25,axis:2,slice:31});
    assert(app.state.statistics.every(v=>v.cells===1024)&&app.state.settings.slice==='15','粗尺度或切面边界错误');
    assert(app.state.support.info.axisCounts.every(v=>v.reduce((x,y)=>x+y,0)===app.state.support.info.retained),'粗尺度计数不守恒');
    passed.push('粗尺度与切面范围一致');
    const create=URL.createObjectURL,click=HTMLAnchorElement.prototype.click;let blob;
    try{
      URL.createObjectURL=b=>{blob=b;return 'blob:gray-support-test';};HTMLAnchorElement.prototype.click=function(){};
      document.getElementById('export').click();const record=JSON.parse(await blob.text());
      assert(record.schema==='snowglass.gray-support-view.v1','导出缺少模式身份');
      assert(record.selection.indices.length===app.state.support.info.retained,'导出缺少入选索引');
      record.selection.indices.forEach((i,k)=>assert(record.selection.gray[k]===app.state.arrays[2][i],'导出灰度与预览不一致'));
    }finally{URL.createObjectURL=create;HTMLAnchorElement.prototype.click=click;}
    passed.push('设置导出包含确定的入选位置与连续灰度');
    document.getElementById('reset').click();
    for(const [i,view] of app.views.entries()){
      assert(view.mesh.count===(i===0?8192:2096),'实际绘制实例数与掩膜不一致');
      const gl=view.renderer.getContext(),size=gl.drawingBufferWidth*gl.drawingBufferHeight*4;
      const on=new Uint8Array(size),off=new Uint8Array(size);
      view.renderer.render(view.scene,view.camera);
      gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,on);
      view.mesh.visible=false;view.renderer.render(view.scene,view.camera);
      gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,off);
      view.mesh.visible=true;view.renderer.render(view.scene,view.camera);
      assert(on.some((v,i)=>i%4!==3&&v!==off[i]),'三维仅剩线框');
    }
    passed.push('实际三维像素贡献与掩膜实例数一致');
    const modeLink=new URL(document.getElementById('study-switch').href);
    assert(!modeLink.searchParams.has('study'),'没有保留原三版入口');
    assert(document.getElementById('threshold').closest('label').hidden&&document.getElementById('residue').closest('label').hidden,'旧耦合控件未隐藏');
    passed.push('独立模式入口和参数说明正确');
    return {passed:passed.length,checks:passed};
  }finally{app.set(saved);}
})();

/* 在 gray_samples.html 控制台执行；只调整小样页，结束恢复其参数，不触及主编辑器。 */
(async () => {
  'use strict';
  const app = window.graySampleTest;
  if (!app) throw new Error('请先打开已加载完成的灰度小样页');
  const saved = {...app.state.settings};
  const passed = [];
  const assert = (condition, message) => {if (!condition) throw new Error(message);};
  const equal = (a,b,tol=1e-10) => Math.abs(a-b)<=tol;
  try {
    for (const sample of Object.values(app.samples)) {
      const f=sample.gray_fixture;
      f.input.forEach((v,i)=>assert(equal(app.mapping(v,sample.reference_white,f.gain,f.threshold,f.gamma),f.output[i]),'Python/JS 曲线不一致'));
    }
    passed.push('两张量 Python/JS 灰度公式一致');
    document.getElementById('reset').click();
    assert(app.state.settings.gain==='1' && app.state.settings.threshold==='0','重置按钮未绑定');
    assert(app.state.statistics.every(s=>s.cells===8192&&s.positive===8192),'共同基线正灰度格数错误');
    passed.push('重置及三版共同基线');
    const hash = JSON.stringify(app.samples.attention.channels);
    document.getElementById('reveal').click();
    assert(app.state.settings.gain==='3' && app.state.settings.gamma==='0.7','显影按钮未绑定');
    assert(JSON.stringify(app.samples.attention.channels)===hash,'曲线修改了原始统计');
    passed.push('共同显影不修改统计源');
    app.set({gain:1,gamma:1,threshold:0,residue:0});
    assert(app.state.arrays[1].every((v,i)=>equal(v,app.state.arrays[2][i])),'残差为零未还原纯谱版本');
    passed.push('残差系数零边界');
    app.set({threshold:.8});
    assert(app.state.statistics.every(s=>s.positive===0),'高门槛应为空');
    passed.push('零灰度空场景');
    app.set({tensor:'mlp',resolution:'coarse',axis:2,slice:31,gain:1,gamma:1,threshold:0,residue:.15});
    assert(app.state.statistics.every(s=>s.cells===1024),'粗网格长度不正确');
    assert(app.state.settings.slice==='15','粗网格切面未限制范围');
    assert(equal(app.state.statistics[0].mean,.5,1e-6),'粗网格不守恒');
    passed.push('张量切换、粗池化守恒及切面边界');
    for (const axis of [0,1,2]) {
      app.set({axis,slice:0,slab:true});
      const canvas=document.querySelector('.slice'), others=[0,1,2].filter(i=>i!==axis);
      assert(canvas.width===app.state.dims[others[1]]&&canvas.height===app.state.dims[others[0]],'切面尺寸错误');
      const pixel=canvas.getContext('2d').getImageData(0,0,1,1).data;
      const xyz=[0,0,0];xyz[axis]=0;xyz[others[0]]=app.state.dims[others[0]]-1;
      const i=(xyz[0]*app.state.dims[1]+xyz[1])*app.state.dims[2]+xyz[2];
      assert(pixel[0]===Math.round(app.state.arrays[0][i]*255),'切面格子与三维索引不对应');
    }
    passed.push('三轴切面像素与 C-order 数值一致');
    app.set({'render-mode':'opaque',slab:false,size:.8});
    assert(app.state.statistics[0].cells===1024,'显示几何改动不应改统计格数');
    passed.push('观察模式与等大小块不改统计');
    const originalCreate=URL.createObjectURL, originalClick=HTMLAnchorElement.prototype.click;
    let blob, download;
    try {
      URL.createObjectURL=b=>{blob=b;return 'blob:gray-sample-test';};
      HTMLAnchorElement.prototype.click=function(){download=this.download;};
      document.getElementById('export').click();
      const result=JSON.parse(await blob.text());
      assert(result.run&&result.settings.tensor==='mlp'&&download.endsWith('.json'),'保存设置内容错误');
    } finally {URL.createObjectURL=originalCreate;HTMLAnchorElement.prototype.click=originalClick;}
    passed.push('保存小样设置按钮（不下载测试文件）');
    assert(document.querySelectorAll('.viewport canvas').length===3,'三维画布未建立');
    passed.push('三个三维视图已建立');
    app.set({tensor:'attention',resolution:'fine',gain:1,gamma:1,threshold:0,residue:.15,slab:false});
    for (const view of app.views) {
      const gl=view.renderer.getContext(), n=gl.drawingBufferWidth*gl.drawingBufferHeight*4;
      const withMesh=new Uint8Array(n), withoutMesh=new Uint8Array(n);
      view.renderer.render(view.scene,view.camera);
      gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,withMesh);
      view.mesh.visible=false;
      view.renderer.render(view.scene,view.camera);
      gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,withoutMesh);
      view.mesh.visible=true;view.renderer.render(view.scene,view.camera);
      assert(withMesh.some((v,i)=>i%4!==3&&v!==withoutMesh[i]),'小块没有实际显示颜色，只剩框');
      assert(view.mesh.count===8192,'三维实例数不是全部正灰度格子');
    }
    passed.push('三版三维小块实际像素贡献与实例数');
    return {passed:passed.length,checks:passed};
  } finally {app.set(saved);}
})();

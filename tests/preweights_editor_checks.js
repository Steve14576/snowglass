/* 在编辑器页面执行：(0,eval)(await (await fetch('../tests/preweights_editor_checks.js')).text())。
   仅测试布局与模拟样本；最终恢复测试前工程和选择，不调用真实权重切片。 */
(() => {
  const api = window.snowglass, original = api.getProject(), selection = api.projectSelection(), results = [];
  const assert = (yes, text) => { if (!yes) throw new Error(text); };
  const close = (a, b) => Math.abs(a - b) < 1e-7;
  const solid = id => api.getLayout().solids.find(s => s.id === id);
  const sizes = s => [0, 1, 2].map(i => Math.hypot(...s.matrix_mm.slice(i * 4, i * 4 + 3)));
  const centers = s => s.matrix_mm.slice(12, 15);
  const test = (name, fn) => { try { fn(); results.push({name, pass:true}); } catch(e) { results.push({name, pass:false, error:e.message}); } };
  try {
    api.resetProject();
    test('4.2 默认尺寸、数量、零重叠', () => {
      const l = api.getLayout();
      assert(l.solids.length === 370, '应有370个实体');
      assert(l.checks.overlaps.length === 0, '默认应零重叠');
      assert(l.solids.every(s => close(s.matrix_mm[14], 0)), '默认中心z应为零');
      assert(close(solid('L00.attn_norm').slot.center[0], -10.2), 'Norm1位置');
      assert(close(solid('L00.post_norm').slot.center[0], -.55), 'Norm2位置');
      assert(close(solid('L00.mix0').slot.size[0], (7.8 - .56) / 3), '混合块宽');
      assert(close(solid('L00.up').slot.size[0], (9.6 - .64) / 3), 'FFN块宽');
      assert(close(solid('V00.attn').slot.center[0], 21.4), '视觉塔位置');
      assert(!l.solids.some(s => /rod|residual/.test(s.id)), '不得存在残差棒');
      // 独立测试基准取自 real_config4.2.html 的 build / mixer / ffn / visionTower，不作为生产排布器。
      const H=32*.6435,h=.396,D=6.2,w=(7.8-.56)/3,f=(9.6-.64)/3;
      const ends={embed:[[0,-H/2-.7-1.2,0],[14,1.4,D*1.15]],final_norm:[[0,H/2+.85,0],[6.5,.4,D*.6]],
        lm_head:[[0,H/2+.7+1.8,0],[14,1.4,D*1.15]],mtp:[[10.5,H/2+.7+1.8,0],[4.2,1.4*.85,D*.9]],
        'V.patch':[[23.5,-17.55/2-1.4,0],[8.2,1.1,D*.9]],'V.merger':[[23.5,17.55/2+1.5,0],[8.5,1.2,D*.95]]};
      for(const s of l.solids){let expected=ends[s.id],m=s.id.match(/^L(\d+)\.(.+)$/),v=s.id.match(/^V(\d+)\.(.+)$/);
        if(m){const y=-H/2+(Number(m[1])+.5)*.6435,key=m[2];
          const slots={attn_norm:[-10.2,.65,D*.6],post_norm:[-.55,.65,D*.6],
            mix0:[-9.2+w/2,w,D],mix1:[-9.2+w/2+w+.28,w,D],mix2:[-9.2+w/2+2*(w+.28),w,D],
            gate:[.4+f/2,f,D],up:[.4+f/2+f+.32,f,D],down:[.4+f/2+2*(f+.32),f,D]};
          const a=slots[key];expected=[[a[0],y,0],[a[1],h,a[2]]];
        }else if(v){const y=-17.55/2+(Number(v[1])+.5)*.65;
          const a={norm1:[-4.5,.45,.5],attn:[-2.1,3.6,.85],norm2:[.3,.45,.5],mlp:[2.9,4,.85]}[v[2]];
          expected=[[23.5+a[0],y,0],[a[1],.65*.62,D*a[2]]];}
        assert(expected&&centers(s).every((x,i)=>close(x,expected[0][i]))&&sizes(s).every((x,i)=>close(x,expected[1][i])), '坐标或尺寸不符4.2：'+s.id);
      }
    });
    test('计算出的精细尺寸不被输入步长误报无效',()=>{
      api.select(['L00.mix0']);assert([...document.querySelectorAll('#selectionSizes input')].every(x=>x.checkValidity()),'计算结果被step误报');api.select([]);
    });
    const digest = JSON.stringify(api.mockDigest('L00.mix0'));
    test('块间隙中心不动、深度不变、样本不重采', () => {
      const before = solid('L00.mix0');
      api.setParam('layerGap', .02); api.flush();
      const after = solid('L00.mix0');
      assert(centers(after).every((v,i) => close(v,centers(before)[i])), '块中心改变');
      assert(close(sizes(after)[2], sizes(before)[2]), '深度被改');
      assert(close(sizes(after)[0], sizes(before)[0] - .02), '宽度未内缩');
      assert(JSON.stringify(api.mockDigest('L00.mix0')) === digest, '样本改变');
      api.setParam('layerGap', 0); api.flush();
    });
    test('双模式只重排，同组总体宽不变', () => {
      const before = solid('L03.mix0');
      api.setParam('widthMode', 'params'); api.flush();
      const after = solid('L03.mix0');
      assert(!close(sizes(before)[0], sizes(after)[0]), '模式切换未改变块宽');
      assert(close(solid('L03.mix2').aabb_mm[3], -1.4), '混合组右界改变');
      assert(JSON.stringify(api.mockDigest('L00.mix0')) === digest, '样本改变');
      api.setParam('widthMode', 'equal'); api.flush();
    });
    test('局部三轴非均匀缩放，不取平均，不动邻居', () => {
      const before = solid('L00.mix0'), neighbor = JSON.stringify(solid('L00.mix1').matrix_mm), size = sizes(before);
      api.select(['L00.mix0']);
      api.resizeSelection(0, size[0] * 2); api.resizeSelection(1, size[1] * 3); api.resizeSelection(2, size[2] * .5);
      const actual = sizes(solid('L00.mix0'));
      assert(actual.every((v,i) => close(v,size[i] * [2,3,.5][i])), '三轴缩放不正确');
      assert(JSON.stringify(solid('L00.mix1').matrix_mm) === neighbor, '邻居被移动');
      assert(close(solid('L00.mix0').frame_t, .04), '框厚随缩放');
      assert(JSON.stringify(api.mockDigest('L00.mix0')) === digest, '样本改变');
    });
    test('参数变更仅保存，不重算模拟或真实雪花', () => {
      api.setParam('gamma', 3, 'data'); api.setParam('compress', 2, 'data'); api.setParam('pitch', .05, 'data'); api.flush();
      assert(JSON.stringify(api.mockDigest('L00.mix0')) === digest, '雪花参数改变样本');
      assert(api.getProject().dirtySnow, '未记录待切片参数修改');
      assert(api.getLayout().realSnowLoaded === false, '错误宣称加载权重');
    });
    test('工程往返恢复变换、毛坯与固定样本', () => {
      const saved = api.getProject(), matrix = JSON.stringify(solid('L00.mix0').matrix_mm);
      api.resetProject(); api.restoreProject(JSON.parse(JSON.stringify(saved)));
      assert(JSON.stringify(solid('L00.mix0').matrix_mm) === matrix, '变换未恢复');
      assert(JSON.stringify(api.mockDigest('L00.mix0')) === digest, '样本未恢复');
    });
    test('无效工程不会污染现有状态', () => {
      const saved = api.getProject(), before = JSON.stringify(saved); saved.manuals['L00.mix0'][0] = null;
      let rejected = false; try { api.restoreProject(saved); } catch(e) { rejected = true; }
      assert(rejected, '无效矩阵未拒绝');
      assert(JSON.stringify(api.getProject()) === before, '无效工程污染状态');
    });
    test('幽灵圆柱创建、编辑、删除不影响模型', () => {
      const before = JSON.stringify(api.getLayout().solids.map(s => s.matrix_mm));
      api.newGhost('cylinder'); api.flush();
      const doc = api.getProject(), cylinder = doc.ghosts.find(g => g.shape === 'cylinder');
      assert(cylinder, '圆柱未创建'); cylinder.radius = 100; cylinder.height = 100; cylinder.margin = 5;
      api.restoreProject(doc);
      assert(JSON.stringify(api.getLayout().solids.map(s => s.matrix_mm)) === before, '改毛坯移动模型');
      api.select(['ghost:' + cylinder.id]); api.deleteGhost(); api.flush();
      assert(!api.getProject().ghosts.some(g => g.id === cylinder.id), '毛坯未删除');
    });
    test('旋转后真正分离的块不被AABB误报', () => {
      api.resetProject(); const doc = api.getProject(), angle = Math.PI / 4;
      const place = (id, offset) => {
        const base = solid(id).slot.center;
        const target = [-Math.sin(angle) * offset, Math.cos(angle) * offset, 0];
        const m = new THREE.Matrix4().makeTranslation(...target.map((v,i) => v-base[i]));
        m.multiply(new THREE.Matrix4().makeRotationZ(angle)); doc.manuals[id] = m.toArray();
      };
      place('L00.mix0', 0); place('L00.mix1', .7); api.restoreProject(doc);
      assert(!api.getLayout().checks.overlaps.some(pair => pair.includes('L00.mix0') && pair.includes('L00.mix1')), '误报旋转盒重叠');
      place('L00.mix1', .1); api.restoreProject(doc);
      assert(api.getLayout().checks.overlaps.some(pair => pair.includes('L00.mix0') && pair.includes('L00.mix1')), '真实重叠未报告');
    });
  } finally { api.restoreProject(original); api.select(selection); }
  return {passed:results.filter(t=>t.pass).length,total:results.length,results};
})()

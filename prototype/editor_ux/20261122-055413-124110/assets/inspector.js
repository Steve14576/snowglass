/* 所选对象属性：继承值可直接改，改这一项才覆盖；固有身份不继承。 */
(() => {
  'use strict';
  const typeNames={global:'全局配置',root:'模型根',tower:'塔',layer:'层',group:'操作组',block:'权重功能块',ghost:'幽灵毛坯',reference:'参照集合',project:'工程',annotationRoot:'标注',labelGroup:'标签组',label:'独立标签'};
  const RANGES={
    gridX:[1,64,1],gridY:[1,64,1],gridZ:[1,64,1],
    frameT:[0,.5,.001],shellT:[0,.5,.001],frameGray:[0,1,.005],shellGray:[0,1,.002],
    snowSize:[.002,.08,.001],gap:[-.3,.3,.005],labelSize:[.1,4,.05],
    labelDx:[-30,30,.1],labelDy:[-30,30,.1],labelDz:[-30,30,.1],
    black:[-.5,1.5,.01],white:[-.5,2.5,.01],cutoff:[0,1,.005],
    squash:[.2,2,.01],depth:[1,30,.1],pitch:[.02,.3,.005],dotUm:[20,120,1],speed:[500,20000,100]
  };
  class Inspector {
    constructor(model,error,actions={}){this.model=model;this.error=error;this.actions=actions;this.ids=[];this.open=new Set(['gray','labels','ghost']);this.element=document.getElementById('properties');this.curveUI=null;}
    safe(fn){try{fn();}catch(e){this.error(e.message);this.render();}}
    section(key,title){const d=document.createElement('details');d.className='prop-section';d.open=this.open.has(key);d.ontoggle=()=>{d.open?this.open.add(key):this.open.delete(key);};
      const s=document.createElement('summary');s.textContent=title;const body=document.createElement('div');body.className='prop-body';d.append(s,body);this.element.append(d);return body;}
    note(body,text,warning=false){const p=document.createElement('p');p.className='prop-note'+(warning?' warning':'');p.textContent=text;body.append(p);}
    field(body,key,label,options=null){
      const M=this.model,ids=this.ids,resolved=ids.map(id=>M.resolve(id,key)),mixed=resolved.some(r=>JSON.stringify(r.value)!==JSON.stringify(resolved[0].value)),r=resolved[0];
      const row=document.createElement('div');row.className='prop-row';const lab=document.createElement('label');lab.textContent=label;lab.htmlFor='field-'+key;
      let input;
      if(options){input=document.createElement('select');if(mixed)input.add(new Option('混合',''));options.forEach(([value,text])=>input.add(new Option(text,value)));input.value=mixed?'':r.value;}
      else if(typeof r.value==='boolean'){input=document.createElement('input');input.type='checkbox';input.checked=!!r.value;input.indeterminate=mixed;}
      else{input=document.createElement('input');input.type='number';input.step='any';input.value=mixed?'':Number(r.value).toPrecision(6);input.placeholder=mixed?'混合':'';}
      input.id=lab.htmlFor;
      const applyTo=v=>ids.forEach(id=>{if(JSON.stringify(M.resolve(id,key).value)!==JSON.stringify(v))M.put(id,key,v);});
      input.onchange=()=>this.safe(()=>{const value=options?input.value:input.type==='checkbox'?input.checked:Number(input.value);
        if(!options&&input.type!=='checkbox'&&!input.value.trim())throw Error('请输入数值，混合不是零');
        M.commit(()=>applyTo(value));});
      let wrap=input,range=null;
      const spec=RANGES[key];
      if(spec&&input.type==='number'){
        const [min,max,step]=spec;const rng=document.createElement('input');rng.type='range';rng.min=min;rng.max=max;rng.step=step;rng.value=Math.min(max,Math.max(min,Number(r.value)||0));
        rng.setAttribute('aria-label',label+' 滑块');wrap=document.createElement('div');wrap.className='prop-inputs';wrap.append(rng,input);range=rng;
        let dragging=false;
        rng.onpointerdown=()=>{dragging=true;M.beginGesture();};
        rng.oninput=()=>{const v=+rng.value;input.value=v.toPrecision(6);
          try{if(dragging)M.updateGesture(()=>applyTo(v));else{M.commit(()=>applyTo(v));
            // 单步调整（键盘、点击滑轨）会重建面板，把焦点还回同一控件，否则连续按方向键会断。
            requestAnimationFrame(()=>document.getElementById('field-'+key)?.focus());}
          }catch(e){this.error(e.message);}};
        const done=()=>{if(!dragging)return;dragging=false;M.endGesture();};rng.onchange=done;rng.onpointerup=done;rng.onpointercancel=done;
      }
      const button=document.createElement('button');button.className='inherit-button';const global=ids.every(id=>id==='global'),allOwn=resolved.every(v=>v.own);
      button.textContent=global?'—':allOwn?'继':'锁';button.disabled=global;button.title=allOwn?'恢复继承，读取上级当前值':'固定当前有效值为本地覆盖';button.setAttribute('aria-label',label+' 继承状态');
      button.onclick=()=>this.safe(()=>M.commit(()=>ids.forEach(id=>{if(allOwn)delete M.nodes.get(id).overrides[key];else M.put(id,key,CurveMath.copy(M.resolve(id,key).value));})));
      const source=document.createElement('div');source.className='prop-source'+(allOwn?' local':'');source.textContent=mixed?'混合值 · 查看成员差异':global?'全局默认':allOwn?'本地覆盖':'继承自：'+M.nodes.get(r.source).name;
      row.append(lab,button);if(wrap===input)row.append(input);else row.append(wrap);row.append(source);body.append(row);
    }
    textField(body,key,label,placeholder=''){
      const M=this.model,ids=this.ids,resolved=ids.map(id=>M.resolve(id,key)),r=resolved[0];
      const row=document.createElement('div');row.className='prop-row';
      const lab=document.createElement('label');lab.textContent=label;lab.htmlFor='field-'+key;
      const input=document.createElement('input');input.type='text';input.id=lab.htmlFor;input.maxLength=80;input.placeholder=placeholder;input.value=r.value||'';
      input.onchange=()=>this.safe(()=>M.commit(()=>ids.forEach(id=>M.put(id,key,input.value))));
      const button=document.createElement('button');button.className='inherit-button';const allOwn=resolved.every(v=>v.own);
      button.textContent=allOwn?'继':'锁';button.title=allOwn?'恢复继承':'固定当前文字为本地值';
      button.onclick=()=>this.safe(()=>M.commit(()=>ids.forEach(id=>{if(allOwn)delete M.nodes.get(id).overrides[key];else M.put(id,key,M.resolve(id,key).value);})));
      const source=document.createElement('div');source.className='prop-source'+(allOwn?' local':'');
      source.textContent=ids.every(id=>id==='global')?'全局默认':allOwn?'本地覆盖':'继承自：'+M.nodes.get(r.source).name;
      row.append(lab,button,input,source);body.append(row);
    }
    transform(body){
      const M=this.model,ids=this.ids,single=ids.length===1?M.nodes.get(ids[0]):null;
      const editable=single&&!['global','project','reference','annotationRoot'].includes(single.type);
      if(!editable){
        const box=M.bounds(ids);if(box.isEmpty())return;
        this.note(body,'多选或不可直接变换的对象：下面是世界读数，只读。要参数化整体变换，先把它们打成组再选中该组。');
        const read=document.createElement('p');read.className='readonly-readout';
        read.textContent=`世界中心 ${box.getCenter(new THREE.Vector3()).toArray().map(v=>v.toFixed(3)).join(', ')} mm · 包围盒 ${box.getSize(new THREE.Vector3()).toArray().map(v=>v.toFixed(3)).join(' × ')} mm`;
        body.append(read);return;
      }
      if(single.type==='labelGroup'){
        const row=document.createElement('div');row.className='prop-row';const label=document.createElement('label');label.textContent='旋转／缩放中心';label.htmlFor='label-transform-center';
        const input=document.createElement('select');input.id=label.htmlFor;input.add(new Option('整组中心','group'));input.add(new Option('各标签自身中心','individual'));input.value=UXAnnotationState.centerMode(M,single.id);
        input.onchange=()=>this.safe(()=>M.setLabelCenter(single.id,input.value));row.append(label,input);body.append(row);
        this.note(body,'整组会改变排布；各自中心只改朝向／尺寸，保持每个标签中心。平移仍统一操作。父组记录控制变换，子标签位置会补偿；作用于此组全部后代标签。');
      }
      this.note(body,'相对默认位置的参数化值，可直接复制记录。父级XYZ使用Z向上的约定（X右、Y后、Z上）；偏移与旋转相对上级默认槽位，缩放是倍数。gumball与数字共用状态，权重网格的局部轴另行记录。');
      const trs=M.localTRS(single.id);
      for(const [key,title,values,factor,hint] of [
        ['t','偏移 mm',trs.t,1,'可负值；0 即回到默认位置。'],
        ['r','旋转 °',trs.r.map(v=>v*180/Math.PI),1,'绕上级默认姿态，XYZ 顺序。'],
        ['s','缩放倍数',trs.s,1,'必须非零，1 为默认尺寸。']
      ]){
        const p=document.createElement('p');p.className='subheading';p.textContent=title;
        const grid=document.createElement('div');grid.className='transform-grid';body.append(p,grid);
        values.forEach((v,axis)=>{
          const label=document.createElement('label');label.textContent=['X','Y','Z'][axis];
          const input=document.createElement('input');input.type='number';input.step='any';
          input.value=v.toFixed(key==='s'?4:3);
          input.dataset.trs=key;input.dataset.axis=axis;
          input.setAttribute('aria-label',title+' '+label.textContent);
          label.append(input);grid.append(label);
          input.onchange=()=>this.safe(()=>{
            if(!input.value.trim()||!Number.isFinite(+input.value))throw Error('请输入有效变换数值');
            const next=M.localTRS(single.id);
            if(key==='t')next.t[axis]=+input.value;
            else if(key==='r')next.r[axis]=+input.value*Math.PI/180;
            else{if(Math.abs(+input.value)<1e-6)throw Error('缩放不能为 0');next.s[axis]=+input.value;}
            M.setLocalTRS(single.id,next);
          });
        });
        const note=document.createElement('p');note.className='prop-note';note.textContent=hint;body.append(note);
      }
      const box=M.bounds([single.id]);
      if(!box.isEmpty()){
        const read=document.createElement('p');read.className='readonly-readout';
        read.textContent=`世界包围盒 ${box.getSize(new THREE.Vector3()).toArray().map(v=>v.toFixed(3)).join(' × ')} mm（只读；随偏移／旋转／缩放变化）`;
        body.append(read);
      }
    }
    render(){
      const M=this.model;this.ids=this.ids.filter(id=>M.nodes.has(id));const ids=this.ids;
      document.getElementById('property-title').textContent=ids.length===1?M.nodes.get(ids[0]).name:ids.length?'已选 '+ids.length+' 个对象':'对象属性';
      document.getElementById('property-kind').textContent=ids.length===1?typeNames[M.nodes.get(ids[0]).type]:'';this.element.textContent='';this.curveUI=null;
      const summary=document.getElementById('property-summary');summary.textContent=ids.length?'修改值才覆盖，其余实时继承。缺少所需来源／约定／网格／诊断时需显式切片；窗口、曲线与几何即时生效。':'在树或视口选择对象；不自动把输入当作修改全局。';
      if(!ids.length)return;const first=M.nodes.get(ids[0]),global=ids.length===1&&first.type==='global';
      if(ids.length===1&&['group','ghost','labelGroup'].includes(first.type)){const input=document.createElement('input');input.type='text';input.value=first.name;input.setAttribute('aria-label','对象名称');input.onchange=()=>this.safe(()=>M.rename(first.id,input.value));this.element.append(input);}
      if(ids.every(id=>!['global','project','reference','annotationRoot'].includes(M.nodes.get(id).type)))this.transform(this.section('transform','变换 · 相对默认位置'));
      if(UXAnnotationUI.render(this))return;
      if(ids.length===1&&first.type==='ghost'){
        const body=this.section('ghost','毛坯基本特征与参照'),d=first.data;this.note(body,'形状：'+(d.shape==='box'?'长方体':'圆柱')+'；切换形状的换算未拍板，可新建另一形状。');
        const fields=d.shape==='box'?[['宽 mm · 局部X',0,d.dims[0]],['高 mm · 局部Z',1,d.dims[1]],['深 mm · 局部Y',2,d.dims[2]]]:[['半径 mm','radius',d.radius],['高度 mm','height',d.height]];
        fields.push(['向内预留 mm','margin',d.margin]);for(const [name,key,value] of fields){const label=document.createElement('div');label.className='prop-row';const span=document.createElement('span');span.textContent=name;const input=document.createElement('input');input.type='number';input.step='any';input.value=value;input.dataset.ghostKey=key;input.setAttribute('aria-label',name);input.onchange=()=>this.safe(()=>{if(!input.value.trim())throw Error('请输入尺寸');M.ghostField(first.id,key,+input.value);});label.append(span,input);body.append(label);}
        const button=document.createElement('button');button.textContent=M.primaryGhost===first.id?'当前主参照':'设为主参照';button.disabled=M.primaryGhost===first.id;button.onclick=()=>M.commit(()=>M.primaryGhost=first.id);body.append(button);this.note(body,'毛坯只作参照；改变它不缩模型、不重算权重。圆柱非均匀变换下内偏移为保守近似。',true);return;
      }
      if(ids.some(id=>['project','reference','ghost'].includes(M.nodes.get(id).type))){this.note(this.element,'此选择仅支持适用的几何管理；没有雪花算法属性。');return;}
      const slice=this.section('slice','一级切片 · 统计生成');
      this.field(slice,'gridX','数据局部 X 格数上限');this.field(slice,'gridY','数据局部 Y 格数上限');this.field(slice,'gridZ','数据局部 Z 格数上限');
      this.note(slice,'网格改后点击右上一级切片。所有权重参与均值合并；网格XYZ是折叠数据的局部轴，不是世界轴，坐标迁移不改变这些格数。每格具体合并多少以 counts 为准。默认16×16×32沿用原探路配方；每分区最多65536格是当前资源限制。');
      this.field(slice,'sourceConvention','权重数值约定',[['gguf','GGUF文件原值'],['hf','HF约定对齐（可选）']]);
      this.field(slice,'extraDiagnostics','额外诊断统计（可选）');
      this.note(slice,'新工程默认GGUF原值、不启用额外诊断；旧工程保留当时的HF约定，需显式切换。对齐只修正数值／排列约定，不恢复量化前精度。');
      this.note(slice,'额外诊断包括带符号均值、原矩阵极值／零比例／RMS。未启用诊断且选完整幅度时不计算这些；谱来源仍须计算RMS作为阈值，这是算法依赖。');
      const gray=this.section('gray','输出灰度 · 即时缓存映射');this.field(gray,'channel','统计来源',[['full','完整权重幅度'],['feature','谱／直接特征'],['rowcol','行列强度'],['residual','谱残差幅度']]);
      this.field(gray,'windowMode','输入窗口',[['range','每张量实际跨度'],['reference','原幅度参考标尺']]);this.field(gray,'black','黑端 · 相对输入');this.field(gray,'white','白端 · 相对输入');
      this.note(gray,'已有对应统计立即映射；未生成的来源提示需要切片，不拿full冒充。完整幅度只直接池化，行列强度才计算行列范数，谱／残差来源才运行SVD并成对生成。');
      this.note(gray,'窗口和曲线只改缓存映射，不读原权重；黑色不表示权重缺失。');
      if(ids.length===1){const container=document.createElement('div');gray.append(container);this.curveUI=new UXCurveUI(container,M,ids[0],text=>this.error(text));}
      else this.note(gray,'多选先查看共同参数；要统一编辑曲线可打组，避免把临时选区当持久组。');
      const support=this.section('filter','独立位置筛选');this.field(support,'filter','启用筛选');this.field(support,'cutoff','曲线前输入门槛');this.note(support,'默认关闭；比较窗口后的输入，不受曲线反转影响，不是无用权重判断。');
      const structure=this.section('structure','框、壳与雪花几何');for(const [key,label] of [['frameT','框截面 mm'],['frameGray','框输出灰度'],['shellT','包络壳厚 mm'],['shellGray','壳输出灰度'],['snowSize','雪花边长 mm']])this.field(structure,key,label);
      this.note(structure,'厚度 0 = 不生成该结构件（导出也没有）；灰度 0 只是不显影，几何仍在。两者不同。');
      this.note(structure,'雪花边长默认0.012mm只供这批缓存观察，不是加工推荐；固定毫米值不随包络缩放。形状暂用已有立方体。',true);
      const layout=this.section('layout','排布配方');this.field(layout,'gap','块间隙增减 mm');this.field(layout,'widthMode','槽位组块宽',[['equal','同组等宽'],['params','按参数规模']]);
      if(global){this.field(layout,'squash','纵向压缩配方');this.field(layout,'depth','基础配方深度 mm');}this.note(layout,'配方不是空间变换；块宽以原层槽位组为单位，不在任意打组中重分参数量。');
      const compose=this.section('compose','显示与作品组成');this.field(compose,'visible','屏幕可见');this.field(compose,'include','进入作品');this.note(compose,'屏幕隐藏不等于不进作品；两者分开。');
      const label=this.section('labels','文字与输出');
      if(ids.length===1&&first.type==='block')UXAnnotationUI.controls(this,label,first.id);
      this.field(label,'labels','屏幕上显示');
      this.field(label,'labelOutput','随作品／切片输出');
      this.textField(label,'labelText','标签文字','留空则用对象自身名字');
      this.textField(label,'labelFont','字体族','如 Microsoft YaHei');
      this.field(label,'labelSize','标签高度 mm');
      this.field(label,'labelDx','标签偏移 X mm');this.field(label,'labelDy','标签偏移 Y mm');this.field(label,'labelDz','标签偏移 Z mm');
      this.note(label,'文字是对象自己的属性，打组不改成员文字。“屏幕上显示”只管预览；“随作品输出”才会写进导出清单。');
      this.note(label,'当前导出管线未接入：文字定义（内容、字体、毫米字号、三轴偏移、锚点位置）会写入灰度映射 JSON，但尚未转成可加工字形几何；朝向、中文字形与轮廓授权仍待核实。',true);
      if(global){const machine=this.section('machine','全局机台与后验参照');for(const [key,text] of [['pitch','机台点距 mm'],['dotUm','爆点点径 μm'],['speed','打点速度 / 秒']])this.field(machine,key,text);this.note(machine,'仅作未核实的工艺参照，不能推断可辨灰阶或安全。',true);}
      const calculation=this.section('calculation','后续计算边界');this.note(calculation,'一级切片已接本机任务服务；统计网格可配置，统计来源按需生成；仅谱来源沿用原SVD配方。任意解析式、自适应、字体几何及厂家OBJ/STL导出仍未接入。每格合并量n不是另行拍板的固定值，以实际 counts 为准。',true);
      this.resultsBody=this.section('results','所选真实统计与来源');this.note(this.resultsBody,'正在载入所选对象的已有统计……');
    }
    selection(ids){this.ids=ids;this.render();}
    updateTransform(){
      const single=this.ids.length===1?this.model.nodes.get(this.ids[0]):null;
      if(!single||['global','project','reference','annotationRoot'].includes(single.type))return;
      const trs=this.model.localTRS(single.id);
      this.element.querySelectorAll('[data-trs]').forEach(input=>{
        if(input===document.activeElement)return;
        const k=input.dataset.trs,a=+input.dataset.axis;
        const v=k==='t'?trs.t[a]:k==='r'?trs.r[a]*180/Math.PI:trs.s[a];
        input.value=v.toFixed(k==='s'?4:3);
      });
      const box=this.model.bounds([single.id]),read=this.element.querySelector('.readonly-readout');
      if(read&&!box.isEmpty())read.textContent=`世界包围盒 ${box.getSize(new THREE.Vector3()).toArray().map(v=>v.toFixed(3)).join(' × ')} mm（只读；随偏移／旋转／缩放变化）`;
    }
    results(results){
      if(!this.resultsBody?.isConnected)return;this.resultsBody.textContent='';let total=0;
      for(const r of results){total+=r.count;this.note(this.resultsBody,r.id+' · '+r.status+' · '+r.count+'候选格 / '+(r.positive||0)+'正灰度格');
        for(const p of r.pieces){const div=document.createElement('div');div.className='source-piece';div.textContent=`${p.tensor} / ${p.name} · ${p.used} · ${p.source_convention==='gguf'?'GGUF原值':'HF约定'} · ${p.grid.join('×')} · 每格${Math.min(...p.counts)}–${Math.max(...p.counts)}值 · 源窗[${p.window.low.toPrecision(5)}, ${p.window.high.toPrecision(5)}]`;this.resultsBody.append(div);}
        r.caveats?.forEach(v=>this.note(this.resultsBody,v,true));
      }this.note(this.resultsBody,'统计来源：'+this.model.provenance.source_run+'。总候选格'+total+'；不从正灰度数推爆点数。');
    }
  }
  window.UXInspector=Inspector;
})();

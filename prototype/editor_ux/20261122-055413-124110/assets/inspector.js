/* 所选对象属性：继承值可直接改，改这一项才覆盖；固有身份不继承。 */
(() => {
  'use strict';
  const typeNames={global:'全局配置',root:'模型根',tower:'塔',layer:'层',group:'操作组',block:'权重功能块',ghost:'幽灵毛坯',reference:'参照集合',project:'工程'};
  class Inspector {
    constructor(model,error){this.model=model;this.error=error;this.ids=[];this.open=new Set(['gray','ghost']);this.element=document.getElementById('properties');this.curveUI=null;}
    safe(fn){try{fn();}catch(e){this.error(e.message);this.render();}}
    section(key,title){const d=document.createElement('details');d.className='prop-section';d.open=this.open.has(key);d.ontoggle=()=>{d.open?this.open.add(key):this.open.delete(key);};
      const s=document.createElement('summary');s.textContent=title;const body=document.createElement('div');body.className='prop-body';d.append(s,body);this.element.append(d);return body;}
    note(body,text,warning=false){const p=document.createElement('p');p.className='prop-note'+(warning?' warning':'');p.textContent=text;body.append(p);}
    field(body,key,label,options=null){
      const M=this.model,ids=this.ids,resolved=ids.map(id=>M.resolve(id,key)),mixed=resolved.some(r=>JSON.stringify(r.value)!==JSON.stringify(resolved[0].value)),r=resolved[0];
      const row=document.createElement('div');row.className='prop-row';const lab=document.createElement('label');lab.textContent=label;lab.htmlFor='field-'+key;
      let input;if(options){input=document.createElement('select');if(mixed)input.add(new Option('混合',''));options.forEach(([value,text])=>input.add(new Option(text,value)));input.value=mixed?'':r.value;}
      else{input=document.createElement('input');input.type=typeof r.value==='boolean'?'checkbox':'number';if(input.type==='checkbox'){input.checked=!!r.value;input.indeterminate=mixed;}else{input.step='any';input.value=mixed?'':Number(r.value).toPrecision(6);input.placeholder=mixed?'混合':'';}}
      input.id=lab.htmlFor;input.onchange=()=>this.safe(()=>{const value=options?input.value:input.type==='checkbox'?input.checked:Number(input.value);if(!options&&input.type!=='checkbox'&&!input.value.trim())throw Error('请输入数值，混合不是零');
        M.commit(()=>ids.forEach(id=>{if(JSON.stringify(M.resolve(id,key).value)!==JSON.stringify(value))M.put(id,key,value);}));});
      const button=document.createElement('button');button.className='inherit-button';const global=ids.every(id=>id==='global'),allOwn=resolved.every(v=>v.own);
      button.textContent=global?'—':allOwn?'继':'锁';button.disabled=global;button.title=allOwn?'恢复继承，读取上级当前值':'固定当前有效值为本地覆盖';
      button.onclick=()=>this.safe(()=>M.commit(()=>ids.forEach(id=>{if(allOwn)delete M.nodes.get(id).overrides[key];else M.put(id,key,CurveMath.copy(M.resolve(id,key).value));})));
      const source=document.createElement('div');source.className='prop-source'+(allOwn?' local':'');source.textContent=mixed?'混合值 · 查看成员差异':global?'全局默认':allOwn?'本地覆盖':'继承自：'+M.nodes.get(r.source).name;
      row.append(lab,input,button,source);body.append(row);
    }
    transform(body){
      this.note(body,'世界坐标与包围盒尺寸，单位mm；旋转为世界矩阵分解读数。拖手柄与输入修改同一变换。');
      const M=this.model,box=M.bounds(this.ids);if(box.isEmpty())return;const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());
      for(const [kind,title,values] of [['position','中心位置',center.toArray()],['size','世界包围盒尺寸',size.toArray()]]){
        const p=document.createElement('p');p.className='subheading';p.textContent=title;const grid=document.createElement('div');grid.className='transform-grid';body.append(p,grid);
        values.forEach((v,axis)=>{const label=document.createElement('label');label.textContent=['X','Y','Z'][axis];const input=document.createElement('input');input.type='number';input.step='any';input.value=v.toFixed(4);input.dataset.transform=kind;input.dataset.axis=axis;input.setAttribute('aria-label',title+' '+label.textContent);label.append(input);grid.append(label);
          input.onchange=()=>this.safe(()=>{if(!input.value.trim()||!Number.isFinite(+input.value))throw Error('请输入有效变换数值');const delta=new THREE.Matrix4();
            if(kind==='position'){const d=[0,0,0];d[axis]=+input.value-M.bounds(this.ids).getCenter(new THREE.Vector3()).getComponent(axis);delta.makeTranslation(...d);}
            else{if(+input.value<=0)throw Error('尺寸必须为正');const b=M.bounds(this.ids),c=b.getCenter(new THREE.Vector3()),scale=[1,1,1];scale[axis]=+input.value/b.getSize(new THREE.Vector3()).getComponent(axis);delta.makeTranslation(...c.toArray()).multiply(new THREE.Matrix4().makeScale(...scale)).multiply(new THREE.Matrix4().makeTranslation(...c.toArray().map(v=>-v)));}
            M.transform(this.ids,delta);});
        });
      }
      if(this.ids.length===1){const id=this.ids[0],m=M.world(id),q=new THREE.Quaternion();m.decompose(new THREE.Vector3(),q,new THREE.Vector3());const e=new THREE.Euler().setFromQuaternion(q),grid=document.createElement('div');grid.className='transform-grid';const title=document.createElement('p');title.textContent='世界旋转 °';title.className='subheading';body.append(title,grid);
        [e.x,e.y,e.z].forEach((v,axis)=>{const label=document.createElement('label');label.textContent=['X','Y','Z'][axis];const input=document.createElement('input');input.type='number';input.step='any';input.value=(v*180/Math.PI).toFixed(3);input.dataset.transform='rotation';input.dataset.axis=axis;input.setAttribute('aria-label','世界旋转 '+label.textContent);label.append(input);grid.append(label);
          input.onchange=()=>this.safe(()=>{if(!input.value.trim()||!Number.isFinite(+input.value))throw Error('请输入有效角度');const old=new THREE.Quaternion();M.world(id).decompose(new THREE.Vector3(),old,new THREE.Vector3());const e=new THREE.Euler().setFromQuaternion(old);e[['x','y','z'][axis]]=+input.value*Math.PI/180;
            const change=new THREE.Quaternion().setFromEuler(e).multiply(old.clone().invert()),center=M.bounds([id]).getCenter(new THREE.Vector3());M.transform([id],new THREE.Matrix4().makeTranslation(...center.toArray()).multiply(new THREE.Matrix4().makeRotationFromQuaternion(change)).multiply(new THREE.Matrix4().makeTranslation(...center.toArray().map(v=>-v))));});
        });
      }
    }
    render(){
      const M=this.model;this.ids=this.ids.filter(id=>M.nodes.has(id));const ids=this.ids;
      document.getElementById('property-title').textContent=ids.length===1?M.nodes.get(ids[0]).name:ids.length?'已选 '+ids.length+' 个对象':'对象属性';
      document.getElementById('property-kind').textContent=ids.length===1?typeNames[M.nodes.get(ids[0]).type]:'';this.element.textContent='';this.curveUI=null;
      const summary=document.getElementById('property-summary');summary.textContent=ids.length?'修改值才覆盖，没改的实时继承。数据计算未接入，不会自动读取权重。':'在树或视口选择对象；不自动把输入当作修改全局。';
      if(!ids.length)return;const first=M.nodes.get(ids[0]),global=ids.length===1&&first.type==='global';
      if(ids.length===1&&['group','ghost'].includes(first.type)){const input=document.createElement('input');input.type='text';input.value=first.name;input.setAttribute('aria-label','对象名称');input.onchange=()=>this.safe(()=>M.rename(first.id,input.value));this.element.append(input);}
      if(ids.every(id=>!['global','project','reference'].includes(M.nodes.get(id).type)))this.transform(this.section('transform','变换与实际尺寸'));
      if(ids.length===1&&first.type==='ghost'){
        const body=this.section('ghost','毛坯基本特征与参照'),d=first.data;this.note(body,'形状：'+(d.shape==='box'?'长方体':'圆柱')+'；切换形状的换算未拍板，可新建另一形状。');
        const fields=d.shape==='box'?[['宽 mm',0,d.dims[0]],['高 mm',1,d.dims[1]],['深 mm',2,d.dims[2]]]:[['半径 mm','radius',d.radius],['高度 mm','height',d.height]];
        fields.push(['向内预留 mm','margin',d.margin]);for(const [name,key,value] of fields){const label=document.createElement('label');label.className='prop-row';label.textContent=name;const input=document.createElement('input');input.type='number';input.step='any';input.value=value;input.dataset.ghostKey=key;input.setAttribute('aria-label',name);input.onchange=()=>this.safe(()=>{if(!input.value.trim())throw Error('请输入尺寸');M.ghostField(first.id,key,+input.value);});label.append(input);body.append(label);}
        const button=document.createElement('button');button.textContent=M.primaryGhost===first.id?'当前主参照':'设为主参照';button.disabled=M.primaryGhost===first.id;button.onclick=()=>M.commit(()=>M.primaryGhost=first.id);body.append(button);this.note(body,'毛坯只作参照；改变它不缩模型、不重算权重。圆柱非均匀变换下内偏移为保守近似。',true);return;
      }
      if(ids.some(id=>['project','reference','ghost'].includes(M.nodes.get(id).type))){this.note(this.element,'此选择仅支持适用的几何管理；没有雪花算法属性。');return;}
      const gray=this.section('gray','输出灰度 · 即时缓存映射');this.field(gray,'channel','统计来源',[['full','完整权重幅度'],['feature','谱／直接特征'],['rowcol','行列强度'],['residual','谱残差幅度']]);
      this.field(gray,'windowMode','输入窗口',[['range','每张量实际跨度'],['reference','原幅度参考标尺']]);this.field(gray,'black','黑端 · 相对输入');this.field(gray,'white','白端 · 相对输入');
      this.note(gray,'组继承的是窗口策略；实际源端点逐张量列出。曲线前统计与灰度分开，黑色不表示权重缺失。');
      if(ids.length===1){const container=document.createElement('div');gray.append(container);this.curveUI=new UXCurveUI(container,M,ids[0],text=>this.error(text));}
      else this.note(gray,'多选先查看共同参数；要统一编辑曲线可打组，避免把临时选区当持久组。');
      const support=this.section('filter','独立位置筛选');this.field(support,'filter','启用筛选');this.field(support,'cutoff','曲线前输入门槛');this.note(support,'默认关闭；比较窗口后的输入，不受曲线反转影响，不是无用权重判断。');
      const structure=this.section('structure','框、壳与雪花几何');for(const [key,label] of [['frameT','框截面 mm'],['frameGray','框输出灰度'],['shellT','包络壳厚 mm'],['shellGray','壳输出灰度'],['snowSize','雪花边长 mm']])this.field(structure,key,label);
      this.note(structure,'雪花边长默认0.012mm只供这批缓存观察，不是加工推荐；固定毫米值不随包络缩放。形状暂用已有立方体。',true);
      const layout=this.section('layout','排布配方');this.field(layout,'gap','块间隙增减 mm');this.field(layout,'widthMode','槽位组块宽',[['equal','同组等宽'],['params','按参数规模']]);
      if(global){this.field(layout,'squash','纵向压缩配方');this.field(layout,'depth','基础配方深度 mm');}this.note(layout,'配方不是空间变换；块宽以原层槽位组为单位，不在任意打组中重分参数量。');
      const label=this.section('labels','成员标签与作品组成');for(const [key,text] of [['visible','屏幕可见'],['include','进入作品'],['labels','显示成员标签'],['labelSize','标签高度 mm'],['labelDx','标签偏移 X mm'],['labelDy','标签偏移 Y mm'],['labelDz','标签偏移 Z mm']])this.field(label,key,text);
      this.note(label,'成员名字不被组名替换。标签仅屏幕，字体和加工文字不在首批实现。');
      if(global){const machine=this.section('machine','全局机台与后验参照');for(const [key,text] of [['pitch','机台点距 mm'],['dotUm','爆点点径 μm'],['speed','打点速度 / 秒']])this.field(machine,key,text);this.note(machine,'仅作未核实的工艺参照，不能推断可辨灰阶或安全。',true);}
      const calculation=this.section('calculation','统计与后续计算');this.note(calculation,'当前只载入已完成的固定网格缓存。每格合并量n仍待最终确认；网格与谱重算、任意解析式、自适应、厂家OBJ/STL导出未接入，不触发新权重实验。',true);
      const b=document.createElement('button');b.textContent='统计重算 · 首批未接入';b.disabled=true;calculation.append(b);
      this.resultsBody=this.section('results','所选真实统计与来源');this.note(this.resultsBody,'正在载入所选对象的已有统计……');
    }
    selection(ids){this.ids=ids;this.render();}
    updateTransform(){
      if(!this.ids.length)return;const b=this.model.bounds(this.ids);if(b.isEmpty())return;const values={position:b.getCenter(new THREE.Vector3()).toArray(),size:b.getSize(new THREE.Vector3()).toArray()};
      this.element.querySelectorAll('[data-transform]').forEach(input=>{if(input===document.activeElement)return;const v=values[input.dataset.transform]?.[+input.dataset.axis];if(v!==undefined)input.value=v.toFixed(4);});
    }
    results(results){
      if(!this.resultsBody?.isConnected)return;this.resultsBody.textContent='';let total=0;
      for(const r of results){total+=r.count;this.note(this.resultsBody,r.id+' · '+r.status+' · '+r.count+'候选格 / '+(r.positive||0)+'正灰度格');
        for(const p of r.pieces){const div=document.createElement('div');div.className='source-piece';div.textContent=`${p.tensor} / ${p.name} · ${p.used} · ${p.grid.join('×')} · 每格${Math.min(...p.counts)}–${Math.max(...p.counts)}值 · 源窗[${p.window.low.toPrecision(5)}, ${p.window.high.toPrecision(5)}]`;this.resultsBody.append(div);}
        r.caveats?.forEach(v=>this.note(this.resultsBody,v,true));
      }this.note(this.resultsBody,'统计来源：'+this.model.provenance.source_run+'。总候选格'+total+'；不从正灰度数推爆点数。');
    }
  }
  window.UXInspector=Inspector;
})();

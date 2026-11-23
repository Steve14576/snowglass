/* 标注专用属性和生成入口。浏览配方不创建对象，确认后才提交一次生成。 */
(() => {
  'use strict';
  function note(ins,body){ins.note(body,'固定朝向文字平面；可保存位置和样式，尚未生成厂家可加工字形。相机转动不转字。',true);}
  function render(ins){
    const M=ins.model,ids=ins.ids;if(!ids.some(id=>UXAnnotationState.is(M.nodes.get(id))))return false;
    if(!ids.every(id=>UXAnnotationState.is(M.nodes.get(id)))){ins.note(ins.element,'模型与标注混合选择时仅显示变换读数；请分开编辑样式。');return true;}
    const body=ins.section('labels','文字与输出'),single=ids.length===1?M.nodes.get(ids[0]):null;
    if(single?.type==='label'){
      const row=document.createElement('div');row.className='prop-row';const label=document.createElement('label');label.textContent='标签自己的文字';label.htmlFor='annotation-text';
      const input=document.createElement('input');input.id=label.htmlFor;input.type='text';input.maxLength=80;input.value=single.data.text;
      input.onchange=()=>ins.safe(()=>M.setLabelText(single.id,input.value));row.append(label,input);body.append(row);
      ins.note(body,'对应源块：'+single.data.members.join('、'));
    }
    ins.field(body,'visible','屏幕上显示');ins.field(body,'labelOutput','随作品／切片输出');ins.textField(body,'labelFont','字体族');ins.field(body,'labelSize','实际字形高度 mm');
    const f=single&&UXAnnotationState.effective(M,single.id);
    if(f)ins.note(body,f.lostSource?'源块已删除：'+f.lostSource+'；保留最后位置，跟随已解除。':'跟随源块：'+f.sourceId+'；跟随平移／旋转，不继承源缩放。');
    if(single?.data.recipe){const r=single.data.recipe;ins.note(body,r.sourceId+' · '+UXAnnotationMath.MODES[r.axis][r.mode].name+' · 初始放置'+r.side+' · 初始朝向'+r.face+'；包含'+M.leaves([single.id]).length+'个标签。');}
    ins.note(body,'组只继承样式，不继承文字内容；用变换数字或gumball调位置／朝向。');note(ins,body);
    const save=document.createElement('button');save.textContent='保存标注定义';save.onclick=()=>ins.actions.saveAnnotations?.(ids.slice());body.append(save);
    return true;
  }
  function controls(ins,body,id){
    const M=ins.model,regular=UXAnnotationMath.source(M,id).regular;
    if(!ins.annotationDrafts)ins.annotationDrafts=new Map();if(!ins.annotationDrafts.has(id))ins.annotationDrafts.set(id,{axis:'z',mode:2,side:'',gap:1});
    const draft=ins.annotationDrafts.get(id),form=document.createElement('div');form.className='annotation-generator';
    const field=(title,input)=>{const row=document.createElement('label');row.className='annotation-field';row.append(document.createTextNode(title),input);form.append(row);};
    const axis=document.createElement('select');axis.id='annotation-axis';for(const a of ['x','y','z'])axis.add(new Option(a.toUpperCase()+'方向排列',a));axis.value=draft.axis;axis.disabled=!regular;field('排列轴',axis);
    const mode=document.createElement('select');mode.id='annotation-mode';mode.disabled=!regular;field('聚合方式',mode);
    const side=document.createElement('select');side.id='annotation-side';field('初始放置侧',side);
    const gap=document.createElement('input');gap.id='annotation-gap';gap.type='number';gap.min='0';gap.step='.1';gap.value=draft.gap;field('外侧间距 mm',gap);
    const output=document.createElement('p');output.className='prop-note';output.id='annotation-preview';form.append(output);
    const selectOptions=()=>{mode.textContent='';UXAnnotationMath.MODES[draft.axis].forEach((s,i)=>mode.add(new Option(s.name,String(i))));mode.value=String(draft.mode);
      side.textContent='';side.add(new Option('按约定自动选择',''));for(const a of ['x','y','z'])if(!regular||a!==draft.axis)for(const sign of ['-','+'])side.add(new Option(sign+a.toUpperCase(),sign+a));side.value=draft.side;};
    const preview=()=>{try{const plan=M.planLabels(id,draft);output.textContent=(regular?UXAnnotationMath.MODES[draft.axis][draft.mode].name:'独立块单标签')+' · '+plan.labels.length+'个标签 · 放'+plan.side+'侧 · 朝'+plan.face+'；只创建标注，不读权重。';}catch(e){output.textContent=e.message;}};
    axis.onchange=()=>{draft.axis=axis.value;draft.side='';selectOptions();preview();};mode.onchange=()=>{draft.mode=+mode.value;preview();};side.onchange=()=>{draft.side=side.value;preview();};gap.oninput=()=>{draft.gap=gap.value.trim()?+gap.value:NaN;preview();};
    const button=document.createElement('button');button.id='generate-annotations';button.textContent='生成独立标签对象';
    button.onclick=async()=>{
      try{
        const plan=M.planLabels(id,draft),existing=[...M.nodes.values()].find(n=>n.type==='labelGroup'&&n.data.recipe?.sourceId===id&&n.data.recipe.axis===plan.axis&&n.data.recipe.mode===plan.mode);
        if(existing&&!await ins.actions.confirm('同源标注已存在','确认将追加一组新标签，不覆盖已有排版。取消后定位已有组。')){ins.actions.select([existing.id]);return;}
        if(!await ins.actions.confirm('创建独立标签对象',`${plan.labels.length} 个标签；源 ${id}\n${regular?UXAnnotationMath.MODES[plan.axis][plan.mode].name:'独立块'}；外侧 ${plan.side}；间距 ${plan.gap} mm；字面 ${plan.face}\n创建后整组跟随所选源块的平移／旋转，单个仍可调。不会重新切权重。`))return;
        const group=M.createLabels(plan,!!existing);ins.actions.select([group]);ins.actions.message('已创建'+plan.labels.length+'个独立标签；在标注分支编辑，源块未改。');
      }catch(e){ins.error(e.message);}
    };
    form.append(button);body.append(form);selectOptions();preview();
    const related=[...M.nodes.values()].filter(n=>n.type==='labelGroup'&&n.data.recipe?.sourceId===id);
    for(const n of related){const jump=document.createElement('button');jump.className='annotation-jump';jump.textContent='定位 '+n.name;jump.onclick=()=>ins.actions.select([n.id]);body.append(jump);}
    ins.note(body,'生成的成员不再重复显示旧自动块标签；旧覆盖值保留，移除显式标注后可恢复。');
  }
  function identity(model,node){
    const f=UXAnnotationState.effective(model,node.id),lines=[];
    if(node.type==='label')lines.push('文字：'+node.data.text,'源成员：'+node.data.members.join('、'));
    else if(node.type==='labelGroup')lines.push('标签组 · '+model.leaves([node.id]).length+'个标签');
    else lines.push('独立标注分支，不计入权重块');
    if(f)lines.push(f.lostSource?'跟随已解除 · 源缺失 '+f.lostSource:'跟随 '+f.sourceId+' · 平移／旋转');
    if(node.type==='label'){const normal=new THREE.Vector3(0,0,1).applyMatrix3(new THREE.Matrix3().getNormalMatrix(model.world(node.id))).normalize();lines.push('字面世界方向：'+normal.toArray().map(v=>v.toFixed(3)).join('、'));}
    lines.push('固定朝向纹理平面；可加工字形未接入');return lines;
  }
  window.UXAnnotationUI={render,controls,identity};
})();

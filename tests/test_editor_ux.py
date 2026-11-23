# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.50,<2"]
# ///
"""独立UX的数值、对象、实际控件与原件冻结检查。不自动截图、不读原权重。"""
import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--folder',type=Path,required=True);parser.add_argument('--phase',choices=['probe','axes','coordinates','pivots','annotations','full'],default='full');parser.add_argument('--url',default='http://127.0.0.1:8128/');args=parser.parse_args()
    bundle=args.folder.resolve();provenance=json.loads((bundle/'provenance.json').read_text(encoding='utf-8'))
    # 归档只改路径、不改内容：按 provenance.archived_paths 解析新位置，仍是同一份哈希。
    moved=provenance.get('archived_paths',{})
    def source_path(name):return ROOT/moved.get(name,name)
    missing=[name for name in provenance['source_hashes'] if not source_path(name).exists()]
    assert not missing,'原件缺失（既不在原路径也不在归档路径）：'+', '.join(missing)
    before={name:sha(source_path(name)) for name in provenance['source_hashes']};assert before==provenance['source_hashes']
    # 原谱小样报告已经记录的冻结核心，GUI改动不得以当前值替换基准。
    frozen_math={'survey_data.py':'5f575e82eb3ecac72b1f983651cf3043770cff97da9c638cbce9d9d32a20952f',
                 'survey_math.py':'185d454ede44535f3e2641a6535e56b86311ca7e8041d1cca5a91c6930d2f62d',
                 'run_type_survey.py':'33f95251b804ad9b3ab36b91f8dc25289a2585c63a6f0be25f35146ffd028c16'}
    assert frozen_math=={name:sha(ROOT/'scripts'/name) for name in frozen_math},'冻结科学脚本已变化'
    output=bundle/'verification'/('run-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));(bundle/'verification').mkdir(exist_ok=True);output.mkdir(exist_ok=False)
    assets=[bundle/'index.html',*list((bundle/'assets').glob('*'))];asset_hashes={str(p.relative_to(bundle)):sha(p) for p in assets}
    cases=[];errors=[];pending=set();diagnostic={};start=time.monotonic();failure=None
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True,args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'])
            page=browser.new_page(viewport={'width':1600,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:pending.add(r.url));page.on('requestfinished',lambda r:pending.discard(r.url));page.on('requestfailed',lambda r:pending.discard(r.url))
            try:
                page.goto(args.url,wait_until='domcontentloaded',timeout=15000)
                page.wait_for_function('window.uxEditor && uxEditor.results.length && uxEditor.results[0].count===8192',timeout=45000)
                assert page.evaluate('()=>uxEditor.model.resolve("global","sourceConvention").value')=='gguf'
                assert page.evaluate('()=>uxEditor.model.resolve("global","extraDiagnostics").value') is False
                # 后续原有科学缓存回归明确选择其HF约定，不把旧缓存冒充新默认原值。
                if args.phase not in ('axes','coordinates','pivots','annotations'):
                    page.evaluate('()=>uxEditor.model.set("global","sourceConvention","hf")')
                    page.wait_for_function('uxEditor.results[0].settings.sourceConvention==="hf"')
            except Exception:
                diagnostic={'status':page.locator('#status').inner_text(timeout=1000),'pending':sorted(pending)}
                raise
            baseline=page.evaluate('''()=>{
                const a=uxEditor,m=a.model,size=m.bounds(['work']).getSize(new THREE.Vector3()).toArray(),old=SnowLayout(m.topo).bounds.getSize(new THREE.Vector3()).toArray();
                if(size.some((v,i)=>Math.abs(v-old[i])>1e-9))throw Error('未保持4.2默认排布');
                if(a.results[0].count!==8192)throw Error('真实格数错误');
                if(a.scene.renderedSnow!==0)throw Error('准备视图不应画雪花');
                const sb=document.getElementById('sidebar').getBoundingClientRect(),v=document.getElementById('view').getBoundingClientRect(),t=document.querySelector('.tree-panel').getBoundingClientRect(),p=document.querySelector('.property-panel').getBoundingClientRect();
                if(sb.right>v.left+1||t.y>=p.y)throw Error('侧栏不在左侧或属性不在下方 '+JSON.stringify({sb:[sb.x,sb.y,sb.width,sb.height],v:[v.x,v.y,v.width,v.height],t:[t.x,t.y,t.width,t.height],p:[p.x,p.y,p.width,p.height]}));
                if(!document.getElementById('sidebar-resizer'))throw Error('缺少宽度拖拽条');
                if(document.querySelectorAll('.tree-row').length!==1)throw Error('对象树不应默认展开');
                const idn=document.getElementById('identity');
                if(idn.hidden||!idn.textContent.includes('L16.down'))throw Error('选中后没有身份卡');
                if(idn.getBoundingClientRect().right<innerWidth*0.6)throw Error('身份卡不在编辑区右侧');
                document.getElementById('report-toggle').click();
                const rep=document.getElementById('report').getBoundingClientRect();
                if(rep.right<innerWidth*0.6||rep.top>160)throw Error('后验报告不在右上');
                document.getElementById('report-toggle').click();
                const accent=getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),hue=parseFloat(accent);
                if(hue>=90&&hue<=180)throw Error('强调色仍偏绿：'+accent);
                const cs=getComputedStyle(document.documentElement),sat=v=>parseFloat((v||'').trim().split(/[ \t]+/)[1]);
                if(sat(cs.getPropertyValue('--local'))<25)throw Error('本地覆盖色被去色');
                if(sat(cs.getPropertyValue('--danger'))<25)throw Error('报红色被去色');
                if(sat(cs.getPropertyValue('--info'))<25)throw Error('文件操作色被去色');
                const fileColor=getComputedStyle(document.querySelector('.file-actions button')).color;
                if(fileColor===getComputedStyle(document.body).color)throw Error('文件按钮与正文同色，无法区分');
                if(document.getElementById('isolate-view').classList.contains('active'))throw Error('默认不应隔离隐藏其它对象');
                const saveBtn=document.getElementById('save-project').getBoundingClientRect(),sliceBtn=document.getElementById('slice-1').getBoundingClientRect();
                if(saveBtn.left>innerWidth/2||sliceBtn.left<innerWidth*0.45)throw Error('文件／切片按钮没有分置左上与右上');
                return {nodes:m.nodes.size,blocks:[...m.nodes.values()].filter(n=>n.type==='block').length,real_count:a.results[0].count,dimensions:size,sidebar_right:sb.right,view_left:v.left,tree_y:t.y,properties_y:p.y,slice_disabled:document.getElementById('slice-1').disabled};
            }''')
            cases.append({'name':'startup_real_geometry_and_layout','result':baseline})
            print(json.dumps({'baseline':baseline,'errors':errors},ensure_ascii=False),flush=True)
            if errors:raise AssertionError(errors)
            axes=page.evaluate('''()=>{
                const a=uxEditor,s=a.scene,m=a.model,before=JSON.stringify(m.snapshot()),selection=s.selected.slice(),snow=s.renderedSnow;
                const el=document.getElementById('world-axis'),r=el.getBoundingClientRect(),view=s.element.getBoundingClientRect(),caption=document.getElementById('view-caption').getBoundingClientRect();
                if(el.dataset.frame!=='world'||getComputedStyle(el).pointerEvents!=='none'||!el.getAttribute('aria-label').includes('Z正向上'))throw Error('世界轴语义或鼠标穿透错误');
                if(r.width<100||r.left<view.left||r.right>view.right||r.top<view.top||r.bottom>caption.top)throw Error('世界轴超出视口或遮挡状态栏');
                const position=s.camera.position.clone(),target=s.orbit.target.clone();
                try{
                    s.fit(['work'],true);const front=s.axisProjection.map(v=>({...v})),p=label=>front.find(v=>v.label===label);
                    if(p('+X').x<=72||p('-X').x>=72||p('+Z').y>=54||p('-Z').y<=54||p('-Y').depth<.99||p('+Y').depth>-.99||s.camera.up.z!==1)throw Error('正面世界XYZ方向错误');
                    s.camera.position.copy(s.orbit.target).add(new THREE.Vector3(60,0,0));s.orbit.update();s.render();
                    const side=s.axisProjection.find(v=>v.label==='+X');if(side.depth<.99)throw Error('世界轴未随相机转动');
                    const c=s.axisCanvas,rgba=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let pixels=0;for(let i=3;i<rgba.length;i+=4)if(rgba[i])pixels++;
                    if(pixels<60)throw Error('世界轴画布没有实际绘制');
                    if(JSON.stringify(m.snapshot())!==before||s.renderedSnow!==snow||JSON.stringify(s.selected)!==JSON.stringify(selection))throw Error('轴指示改动了模型／雪花／选择');
                    return {front,side,pixels,model_unchanged:true,mouse_passthrough:true};
                }finally{s.camera.position.copy(position);s.orbit.target.copy(target);s.orbit.update();s.render();}
            }''')
            cases.append({'name':'world_axes_projection_and_view_only','result':axes})
            if args.phase in ('coordinates','full'):
                coordinate_suite=page.evaluate('(source)=>{(0,eval)(source);return CoordinateTests.run();}',(ROOT/'tests/coordinate_checks.js').read_text(encoding='utf-8'))
                cases.extend(coordinate_suite['cases'])
            if args.phase in ('annotations','full'):
                suite=page.evaluate('(source)=>{(0,eval)(source);return AnnotationTests.run();}',(ROOT/'tests/annotation_checks.js').read_text(encoding='utf-8'))
                cases.extend(suite)
                print(json.dumps({'annotation_math_cases':len(suite)},ensure_ascii=False),flush=True)
            if args.phase in ('pivots','full'):
                cases.extend(page.evaluate('(source)=>{(0,eval)(source);return PivotTests.run();}',(ROOT/'tests/pivot_checks.js').read_text(encoding='utf-8')))
            if args.phase=='pivots':
                starts=[];page.on('request',lambda r:starts.append(r.url) if '/api/slice1/start' in r.url else None)
                source_state=page.evaluate('()=>({nodes:uxEditor.model.topo.blocks.map(b=>[b.id,uxEditor.model.world(b.id).toArray()]),request:uxEditor.slicing.blocks().map(id=>uxEditor.slicing.requestFor(id))})')
                group=page.evaluate('()=>{const a=uxEditor,g=a.model.createLabels(a.model.planLabels("L16.down"));a.select([g]);return g;}')
                page.get_by_text('变换 · 相对默认位置',exact=True).click() if not page.locator('#label-transform-center').is_visible() else None
                assert page.locator('#label-transform-center').input_value()=='group'
                page.locator('#label-transform-center').select_option('individual')
                positions=page.evaluate('()=>uxEditor.model.leaves(uxEditor.selected).map(id=>({id,p:new THREE.Vector3().setFromMatrixPosition(uxEditor.model.world(id)).toArray()}))')
                page.locator('[data-trs="r"][data-axis="0"]').fill('30');page.locator('[data-trs="r"][data-axis="0"]').dispatch_event('change')
                page.locator('[data-trs="s"][data-axis="2"]').fill('2');page.locator('[data-trs="s"][data-axis="2"]').dispatch_event('change')
                actual=page.evaluate('()=>uxEditor.model.leaves(uxEditor.selected).map(id=>({id,p:new THREE.Vector3().setFromMatrixPosition(uxEditor.model.world(id)).toArray()}))')
                assert all(a['id']==b['id'] and all(abs(x-y)<1e-7 for x,y in zip(a['p'],b['p'])) for a,b in zip(positions,actual)),'各自中心数字旋缩移动位置'
                gesture=page.evaluate('''()=>{
                    const a=uxEditor,m=a.model,s=a.scene,g=a.selected[0],ids=m.leaves([g]),compare=(w,expected)=>{if(w.elements.some((v,i)=>Math.abs(v-expected.elements[i])>1e-7))throw Error('多帧手柄累积了旋缩或移动了中心');};
                    function perform(mode,values){
                        s.setMode(mode);s.syncPivot();s.pivot.updateMatrixWorld(true);const initial=s.pivot.matrixWorld.clone(),quaternion=s.pivot.quaternion.clone(),old=ids.map(id=>m.world(id)),count=m.history.length;
                        s.gumball.dispatchEvent({type:'dragging-changed',value:true});s.gumball.dragging=true;
                        for(const value of values){if(mode==='rotate')s.pivot.quaternion.copy(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1),value).multiply(quaternion));else s.pivot.scale.z=value;
                            s.pivot.updateMatrixWorld(true);const d=s.pivot.matrixWorld.clone().multiply(initial.clone().invert());s.gumball.dispatchEvent({type:'objectChange'});
                            ids.forEach((id,i)=>compare(m.world(id),d.clone().multiply(old[i]).setPosition(new THREE.Vector3().setFromMatrixPosition(old[i]))));}
                        s.gumball.dragging=false;s.gumball.dispatchEvent({type:'dragging-changed',value:false});if(m.history.length!==count+1)throw Error('一次手势不止一次撤销');
                        const saved=m.snapshot();m.undo();ids.forEach((id,i)=>compare(m.world(id),old[i]));m.redo();if(JSON.stringify(m.snapshot())!==JSON.stringify(saved))throw Error('手柄重做不完整');
                    }
                    perform('rotate',[.1,.2]);perform('scale',[1.1,1.4]);return {frames_not_accumulated:true,rotate_and_scale:true,undo_redo:true};
                }''')
                after_state=page.evaluate('()=>({nodes:uxEditor.model.topo.blocks.map(b=>[b.id,uxEditor.model.world(b.id).toArray()]),request:uxEditor.slicing.blocks().map(id=>uxEditor.slicing.requestFor(id))})')
                assert source_state==after_state and not starts,'中心模式影响源块或启动权重任务'
                saved=page.evaluate('()=>uxEditor.getProject()')
                restored=browser.new_page(viewport={'width':1600,'height':1050})
                restored.add_init_script('(doc=>localStorage.setItem("snowglass.editor-ux.20261122-055413-124110.v3-zup",JSON.stringify(doc)))('+json.dumps(saved)+')')
                restored.goto(args.url,wait_until='domcontentloaded');restored.wait_for_function('(id)=>window.uxEditor?.model.nodes.get(id)?.data.transformCenter==="individual" && uxEditor.scene.annotationView.meshes.size===32',arg=group,timeout=45000)
                assert restored.evaluate('()=>uxEditor.scene.renderedSnow')==0
                restored.close();assert not errors,errors
                cases.append({'name':'actual_pivot_selector_numeric_multiframe_gumball_and_restore','result':gesture})
                browser.close()
            elif args.phase=='coordinates':
                legacy_json=json.dumps(coordinate_suite['legacy'],ensure_ascii=False)
                restored=browser.new_page(viewport={'width':1600,'height':1050})
                restored.add_init_script('(value=>localStorage.setItem("snowglass.editor-ux.20261122-055413-124110.v2",value))('+json.dumps(legacy_json)+')')
                restored.goto(args.url,wait_until='domcontentloaded')
                restored.wait_for_function('window.uxEditor?.model.nodes.has("label-old") && uxEditor.scene.annotationView.meshes.size===1 && uxEditor.results.length',timeout=45000)
                state=restored.evaluate('()=>({camera:uxEditor.scene.camera.position.toArray(),target:uxEditor.scene.orbit.target.toArray(),system:uxEditor.getProject().coordinateSystem,old:localStorage.getItem("snowglass.editor-ux.20261122-055413-124110.v2"),key:uxEditor.storageKey})')
                assert state['old']==legacy_json and state['key'].endswith('.v3-zup')
                for actual,expected in ((state['camera'],coordinate_suite['expectedCamera']),(state['target'],coordinate_suite['expectedTarget'])):
                    assert all(abs(a-b)<1e-7 for a,b in zip(actual,expected)),(actual,expected)
                restored.wait_for_function('JSON.parse(localStorage.getItem(uxEditor.storageKey)||"null")?.coordinateSystem==="snowglass.xyz-z-up.v1"')
                assert restored.evaluate('()=>uxEditor.scene.renderedSnow')==0
                assert restored.evaluate('()=>localStorage.getItem("snowglass.editor-ux.20261122-055413-124110.v2")')==legacy_json
                restored.close()
                page.locator('#project-file').set_input_files({'name':'legacy.json','mimeType':'application/json','buffer':legacy_json.encode('utf-8')})
                page.wait_for_function('document.getElementById("status").textContent.includes("新版工程已恢复")')
                file_state=page.evaluate('()=>({camera:uxEditor.scene.camera.position.toArray(),system:uxEditor.getProject().coordinateSystem,labels:uxEditor.scene.annotationView.meshes.size})')
                assert file_state['labels']==1 and file_state['system']=='snowglass.xyz-z-up.v1'
                assert all(abs(a-b)<1e-7 for a,b in zip(file_state['camera'],coordinate_suite['expectedCamera']))
                cases.append({'name':'legacy_browser_storage_and_file_open_preserve_camera','result':{'original_storage_unchanged':True,'new_coordinate_system':state['system']}})
                browser.close()
            elif args.phase=='annotations':
                starts=[];page.on('request',lambda r:starts.append(r.url) if '/api/slice1/start' in r.url else None)
                before_state=page.evaluate('()=>({parents:uxEditor.model.topo.blocks.map(b=>[b.id,uxEditor.model.nodes.get(b.id).parent,uxEditor.model.world(b.id).toArray()]),requests:uxEditor.slicing.blocks().map(id=>uxEditor.slicing.requestFor(id))})')
                page.evaluate('()=>uxEditor.select(["L16.down"])')
                page.locator('#annotation-axis').select_option('x');page.locator('#annotation-mode').select_option('2')
                assert '8个标签' in page.locator('#annotation-preview').inner_text()
                page.locator('#generate-annotations').click(timeout=10000)
                page.wait_for_function('document.getElementById("confirm-dialog").open')
                assert '8 个标签' in page.locator('#confirm-body').inner_text()
                page.locator('#confirm-ok').click(timeout=10000)
                page.wait_for_function('uxEditor.model.nodes.get(uxEditor.selected[0])?.type==="labelGroup"')
                gid=page.evaluate('()=>uxEditor.selected[0]')
                assert page.locator('#field-gridX').count()==0
                interaction=page.evaluate('''()=>{
                    const a=uxEditor,s=a.scene,m=a.model,g=a.selected[0],labels=m.children(g),id=labels[0].id,count=m.history.length,before=m.world(id);
                    s.syncPivot();s.pivot.updateMatrixWorld(true);s.gumball.dispatchEvent({type:'dragging-changed',value:true});s.gumball.dragging=true;
                    s.pivot.position.x+=.3;s.pivot.updateMatrixWorld(true);s.gumball.dispatchEvent({type:'objectChange'});s.gumball.dragging=false;s.gumball.dispatchEvent({type:'dragging-changed',value:false});
                    const after=m.world(id);if(Math.abs(after.elements[12]-before.elements[12]-.3)>1e-7||m.history.length!==count+1)throw Error('标签组gumball／手势撤销错误');
                    a.select([id]);return {id,g,count:labels.length,group_delta:.3};
                }''')
                assert page.locator('#annotation-text').is_visible()
                page.get_by_text('变换 · 相对默认位置',exact=True).click() if not page.locator('[data-trs="t"][data-axis="0"]').is_visible() else None
                page.locator('[data-trs="t"][data-axis="0"]').fill('0.2');page.locator('[data-trs="t"][data-axis="0"]').dispatch_event('change')
                single=page.evaluate('''()=>{
                    const a=uxEditor,m=a.model,s=a.scene,id=a.selected[0];if(Math.abs(m.localTRS(id).t[0]-.2)>1e-8)throw Error('标签数值变换未写入');
                    const before=m.world(id),count=m.history.length;s.syncPivot();s.pivot.updateMatrixWorld(true);s.gumball.dispatchEvent({type:'dragging-changed',value:true});s.gumball.dragging=true;
                    s.pivot.position.z+=.15;s.pivot.updateMatrixWorld(true);s.gumball.dispatchEvent({type:'objectChange'});s.gumball.dragging=false;s.gumball.dispatchEvent({type:'dragging-changed',value:false});
                    if(Math.abs(m.world(id).elements[14]-before.elements[14]-.15)>1e-7||m.history.length!==count+1)throw Error('单标签gumball未共享状态');return {numeric:.2,gumball_z:.15};
                }''')
                page.locator('#annotation-text').fill('长中文标签用于完整字形测量与保存验证'*3)
                page.locator('#annotation-text').dispatch_event('change')
                page.wait_for_function('uxEditor.scene.annotationView.meshes.get(uxEditor.selected[0])?.userData.contentKey.includes("长中文")')
                view=page.evaluate('''()=>{
                    const a=uxEditor,s=a.scene,m=a.model,id=a.selected[0],mesh=s.annotationView.meshes.get(id),w=m.world(id).toArray();
                    if(!mesh.isMesh||mesh.isSprite)throw Error('仍是相机Sprite');const size=UXAnnotationMath.shape(m,m.nodes.get(id));
                    if(Math.abs(new THREE.Vector3().setFromMatrixColumn(m.world(id),1).length()-.7)>1e-7)throw Error('字号不是字形高度');
                    const c=mesh.material.map.image,pixels=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let minX=c.width,maxX=-1,minY=c.height,maxY=-1;
                    for(let y=0;y<c.height;y++)for(let x=0;x<c.width;x++)if(pixels[(y*c.width+x)*4+3]>20){minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);}
                    if(minX<2||maxX>=c.width-2||minY<2||maxY>=c.height-2||maxX<0)throw Error('字形贴图裁切或未绘制');
                    const camera=s.camera.position.clone(),target=s.orbit.target.clone();s.camera.position.x+=10;s.orbit.update();s.render();
                    if(m.world(id).toArray().some((v,i)=>Math.abs(v-w[i])>1e-8))throw Error('相机带着字转');s.camera.position.copy(camera);s.orbit.target.copy(target);s.orbit.update();
                    const other=m.children(m.nodes.get(id).parent).find(n=>n.id!==id);m.setLabelText(other.id,m.nodes.get(id).data.text);s.structure();
                    if(s.annotationView.meshes.get(other.id).material.map!==mesh.material.map)throw Error('相同文字没有共享纹理');
                    const mapping=m.annotations([id])[0];if(mapping.front_world[2]<.99||mapping.follow.sourceId!=='L16.down')throw Error('固定朝向／跟随导出错误');
                    return {canvas:[c.width,c.height],ink:[minX,minY,maxX,maxY],glyph_height:size.height,texture_shared:true};
                }''')
                after_state=page.evaluate('()=>({parents:uxEditor.model.topo.blocks.map(b=>[b.id,uxEditor.model.nodes.get(b.id).parent,uxEditor.model.world(b.id).toArray()]),requests:uxEditor.slicing.blocks().map(id=>uxEditor.slicing.requestFor(id))})')
                assert before_state==after_state,'标注操作影响源块／切片参数'
                picking=page.evaluate('''()=>{
                    const a=uxEditor,m=a.model,s=a.scene,id=a.selected[0];for(const n of m.nodes.values())if(n.type==='label'&&n.id!==id)m.set(n.id,'visible',false);
                    s.setMode('off');s.structure();const center=m.bounds([id]).getCenter(new THREE.Vector3());s.orbit.target.copy(center);s.camera.position.copy(center).add(new THREE.Vector3(0,-.01,20));s.orbit.update();s.render();
                    const p=s.screen(id),hit=s.pick({clientX:p.x,clientY:p.y,altKey:false});if(hit!==id)throw Error('固定文字平面未参与点击命中');return {id,point:p};
                }''')
                page.mouse.click(picking['point']['x'],picking['point']['y'])
                assert page.evaluate('()=>uxEditor.selected[0]')==picking['id']
                page.keyboard.down('Shift');page.mouse.move(picking['point']['x']-12,picking['point']['y']-12);page.mouse.down();page.mouse.move(picking['point']['x']+12,picking['point']['y']+12,steps=3);page.mouse.up();page.keyboard.up('Shift')
                assert picking['id'] in page.evaluate('()=>uxEditor.selected')
                page.evaluate('(id)=>uxEditor.select([id])',picking['id'])
                mapping=page.evaluate('async()=>uxEditor.mapping(uxEditor.selected)');assert not mapping['results'] and len(mapping['annotations'])==1
                with page.expect_download(timeout=10000) as download:
                    page.get_by_text('保存标注定义',exact=True).click()
                assert download.value.suggested_filename.startswith('annotations_')
                saved=page.evaluate('()=>uxEditor.getProject()')
                restored=browser.new_page(viewport={'width':1600,'height':1050})
                restored.add_init_script('(doc=>localStorage.setItem("snowglass.editor-ux.20261122-055413-124110.v2",JSON.stringify(doc)))('+json.dumps(saved)+')')
                restored.goto(args.url,wait_until='domcontentloaded');restored.wait_for_function('window.uxEditor?.model.nodes.get(uxEditor.selected[0])?.type==="label" && uxEditor.scene.annotationView.meshes.size===8',timeout=45000)
                assert restored.evaluate('()=>uxEditor.model.nodes.get(uxEditor.selected[0]).data.text')==next(n for n in saved['nodes'] if n['id']==interaction['id'])['data']['text']
                assert restored.evaluate('()=>uxEditor.scene.renderedSnow')==0
                restored.close();assert not starts,starts;assert not errors,errors
                cases.append({'name':'actual_annotation_controls_gumball_texture_export_restore','result':{**interaction,**view,'single_transform':single,'click_and_box_select':True,'source_unchanged':True,'no_weight_job':True}})
                browser.close()
            elif args.phase=='axes':
                browser.close()
            elif args.phase=='probe':
                diag=page.evaluate('''()=>{
                    const s=uxEditor.scene,r=s.renderer,g=r.getContext(),w=g.drawingBufferWidth,h=g.drawingBufferHeight;
                    function compare(){const on=new Uint8Array(w*h*4),off=new Uint8Array(w*h*4);s.render();g.readPixels(0,0,w,h,g.RGBA,g.UNSIGNED_BYTE,on);s.snow.visible=false;s.render();g.readPixels(0,0,w,h,g.RGBA,g.UNSIGNED_BYTE,off);s.snow.visible=true;
                        let count=0,max=0;for(let i=0;i<on.length;i+=4){if(on[i]!==off[i]||on[i+1]!==off[i+1]||on[i+2]!==off[i+2])count++;max=Math.max(max,on[i],on[i+1],on[i+2]);}return {pixels:count,max};}
                    s.drawSnow(uxEditor.results);s.fit(['L16.down']);const normal=compare();s.frames.material.needsUpdate=true;s.shells.material.needsUpdate=true;const recompiled=compare();const objects=[s.frames,s.shells,s.proxy,s.ghosts,s.highlights,s.labels,s.gumball];const old=objects.map(o=>o.visible);objects.forEach(o=>o.visible=false);const isolated=compare();objects.forEach((o,i)=>o.visible=old[i]);s.render();
                    const mesh=s.snow.children[0],mat=new THREE.Matrix4();mesh.getMatrixAt(0,mat);return {normal,recompiled,isolated,gl_error:g.getError(),lost:g.isContextLost(),buffer:[w,h],meshes:s.snow.children.length,count:s.renderedSnow,first_matrix:mat.toArray(),first_colors:Array.from(mesh.instanceColor.array.slice(0,9)),camera:s.camera.position.toArray()};
                }''')
                print(json.dumps({'render_probe':diag},ensure_ascii=False),flush=True);cases.append({'name':'render_probe','result':diag});browser.close()
            else:
                initial=page.evaluate('() => uxEditor.model.snapshot()')
                def check(name,script):
                    result=page.evaluate(script);cases.append({'name':name,'result':result});print(json.dumps({'case':name,'status':'pass'},ensure_ascii=False),flush=True)
                check('optional_channel_cache_and_convention_isolation','''async()=>{
                    const ref={file:'test',gguf:'tiny'},key='test:tiny',grid=[2,2,2];
                    const status=()=>({full:'ready',feature:'not_generated',residual:'not_generated',rowcol:'not_generated'});
                    const b={id:'test',tensors:[ref]},fullIndex={key,url:'/synthetic/full',data_sha256:'full',grid,sourceConvention:'gguf',extraDiagnostics:false,channel_status:status(),packed_sha256:'same'};
                    const d=new UXData.Data({source_run:'synthetic',blocks:[b],tensors:[fullIndex]});
                    const params={channel:'full',sourceConvention:'gguf',extraDiagnostics:false,gridX:2,gridY:2,gridZ:2,windowMode:'range',black:0,white:1,curve:CurveMath.linear(),filter:false,cutoff:0};
                    const model={resolve:(id,k)=>({value:params[k]})};
                    const window={low:0,high:1,constant:false};
                    const payload=(channels,convention='gguf')=>({key,name:'tiny',packed_sha256:'same',sourceConvention:convention,reference_white:1,
                      spectral:{method:'spectral',rank_capped:false},windows:{full:window,feature:window,residual:window,rowcol:window},
                      parts:[{name:'main',grid,counts:Array(8).fill(1),full:Array(8).fill(.3),feature:channels.includes('feature')?Array(8).fill(.2):null,residual:channels.includes('residual')?Array(8).fill(.1):null,rowcol:channels.includes('rowcol')?Array(8).fill(.8):null}]});
                    d.cache.set(fullIndex.url,payload(['full']));if(!d.fresh('test',model))throw Error('full缓存不可用');
                    params.channel='feature';if(d.fresh('test',model))throw Error('未算谱被当成已算');
                    let refused=false;try{await d.evaluate('test',model);}catch(e){refused=e.message.includes('尚未生成');}if(!refused)throw Error('未生成通道偷偷回退full');
                    const spectralIndex={...fullIndex,url:'/synthetic/spectral',data_sha256:'spectral',channel_status:{...status(),feature:'ready',residual:'ready'}};
                    d.merge({source_run:'spectral',blocks:[b],tensors:[spectralIndex]});d.cache.set(spectralIndex.url,payload(['feature','residual']));
                    const rowIndex={...fullIndex,url:'/synthetic/rowcol',data_sha256:'rowcol',channel_status:{...status(),rowcol:'ready'}};
                    d.merge({source_run:'rowcol',blocks:[b],tensors:[rowIndex]});d.cache.set(rowIndex.url,payload(['rowcol']));
                    const r=await d.evaluate('test',model);if(r.pieces[0].used!=='feature'||r.pieces[0].data_sha256!=='spectral')throw Error('补rowcol丢掉谱缓存');
                    params.sourceConvention='hf';if(d.fresh('test',model))throw Error('GGUF缓存被冒充HF');
                    const hfIndex={...fullIndex,url:'/synthetic/hf',data_sha256:'hf',sourceConvention:'hf'};
                    d.merge({source_run:'hf',blocks:[b],tensors:[hfIndex]});d.cache.set(hfIndex.url,payload(['full'],'hf'));params.channel='full';
                    if(!d.fresh('test',model))throw Error('HF缓存不可用');params.sourceConvention='gguf';if(!d.fresh('test',model))throw Error('切回GGUF缓存丢失');
                    return {missing_refused:refused,channel_preserved:true,conventions_isolated:true};
                }''')
                check('legacy_project_keeps_convention_and_new_switches_inherit','''()=>{
                    const n=new UXModel.Model(uxEditor.model.topo,uxEditor.model.provenance),before=n.world('L16.down').toArray(),old=n.snapshot();
                    const values=old.nodes.find(v=>v.id==='global').values;delete values.sourceConvention;delete values.extraDiagnostics;
                    n.load(old);if(n.resolve('global','sourceConvention').value!=='hf'||n.resolve('global','extraDiagnostics').value!==false)throw Error('旧约定被静默改变');
                    if(n.world('L16.down').toArray().some((v,i)=>Math.abs(v-before[i])>1e-9))throw Error('选项改动影响排布');
                    n.set('global','extraDiagnostics',true);n.lock('L16.down','extraDiagnostics');n.set('global','extraDiagnostics',false);
                    if(!n.resolve('L16.down','extraDiagnostics').value||n.resolve('L16.up','extraDiagnostics').value)throw Error('新增选项继承／锁失效');
                    return {legacy_hf:true,geometry_unchanged:true,sparse_override:true};
                }''')
                check('inherit_group_and_sparse_overrides','''()=>{
                    const m=uxEditor.model,ids=['L16.down','L16.up'];window.uxInitial=m.snapshot();
                    const matrices=ids.map(id=>m.world(id).toArray()),g=m.group(ids);window.testGroup=g;
                    if(Object.keys(m.nodes.get(g).overrides).length)throw Error('新组复制了参数');
                    ids.forEach((id,i)=>{if(m.world(id).toArray().some((v,j)=>Math.abs(v-matrices[i][j])>1e-9))throw Error('打组世界变换跳动');});
                    m.set('global','frameGray',.4);if(m.resolve(ids[0],'frameGray').value!==.4)throw Error('父更新未继承');
                    m.set(g,'frameGray',.3);m.set('global','frameGray',.5);
                    if(m.resolve(ids[0],'frameGray').value!==.3||m.resolve(g,'curve').source!=='global')throw Error('覆盖导致其他属性独立');
                    m.lock(g,'curve');m.set('global','curve',CurveMath.preset('reverse'));
                    if(m.resolve(ids[0],'curve').value.nodes[0].y!==0)throw Error('锁定没固定');m.inherit(g,'curve');
                    if(m.resolve(ids[0],'curve').value.nodes[0].y!==1)throw Error('恢复继承不是父当前值');
                    if(Object.keys(m.nodes.get(g).overrides).join()!=='frameGray')throw Error('不是稀疏覆盖');return {group:g,overrides:m.nodes.get(g).overrides};
                }''')
                check('fixed_mm_transform_and_reparent','''async()=>{
                    const a=uxEditor,m=a.model,g=testGroup;await a.data.evaluate('L16.down',m);const raw=a.data.evaluated.get('L16.down').pieces[0].raw.slice();
                    m.transform([g],new THREE.Matrix4().makeTranslation(2,3,4).multiply(new THREE.Matrix4().makeRotationZ(.3)).multiply(new THREE.Matrix4().makeScale(1.3,.8,1.1)));
                    a.select([g]);await a.refreshData();a.scene.drawSnow(a.results);const mesh=a.scene.snow.children[0],mat=new THREE.Matrix4();mesh.getMatrixAt(0,mat);
                    const side=m.resolve('L16.down','snowSize').value;for(let i=0;i<3;i++)if(Math.abs(new THREE.Vector3().setFromMatrixColumn(mat,i).length()-side)>1e-6)throw Error('小块随包络缩放');
                    const actual=a.results.find(r=>r.id==='L16.down');if(!actual||raw.some((v,i)=>v!==actual.pieces[0].raw[i]))throw Error('变换改了源值');
                    const next=m.group(['L00.up']);window.nextGroup=next;m.set(next,'frameGray',.7);m.set('L16.down','frameGray',.6);
                    const before=m.world('L16.down').toArray();m.commit(()=>m.move('L16.down',next));
                    if(m.world('L16.down').toArray().some((v,i)=>Math.abs(v-before[i])>1e-8))throw Error('迁组丢世界变换');
                    if(m.resolve('L16.down','frameGray').value!==.6)throw Error('迁组盖过成员覆盖');return {side,retained_raw:raw.length};
                }''')
                check('ungroup_two_modes_and_undo','''()=>{
                    const m=uxEditor.model,before=m.world('L16.up').toArray();m.ungroup(testGroup,false);
                    if(m.resolve('L16.up','frameGray').value!==.5||Object.hasOwn(m.nodes.get('L16.up').overrides,'frameGray'))throw Error('默认解组偷偷下放');
                    if(m.world('L16.up').toArray().some((v,i)=>Math.abs(v-before[i])>1e-8))throw Error('解组丢变换');
                    m.undo();if(!m.nodes.has(testGroup)||m.nodes.get('L16.up').parent!==testGroup)throw Error('撤销没恢复关系');m.redo();
                    m.ungroup(nextGroup,true);if(m.resolve('L16.down','frameGray').value!==.6||m.resolve('L00.up','frameGray').value!==.7)throw Error('保留模式覆盖优先级错');
                    if(Object.keys(m.nodes.get('L00.up').overrides).join()!=='frameGray')throw Error('复制了整套继承参数');return true;
                }''')
                check('ghosts_and_global_only_fields','''()=>{
                    const m=uxEditor.model,before=m.world('L16.down').toArray(),g=m.newGhost('cylinder');m.ghostField(g,'radius',14);m.ghostField(g,'margin',1);
                    m.transform([g],new THREE.Matrix4().makeTranslation(5,6,7));if(m.world('L16.down').toArray().some((v,i)=>v!==before[i]))throw Error('毛坯改了模型');
                    let blocked=false;try{m.set('L16.down','pitch',.2);}catch(e){blocked=true;}if(!blocked)throw Error('机台可局部');
                    const s=JSON.stringify(m.snapshot());try{m.group([g,'L16.down']);}catch(e){}if(JSON.stringify(m.snapshot())!==s)throw Error('失败打组未回滚');return {ghost:g};
                }''')
                check('project_roundtrip_and_invalid_trees','''()=>{
                    const m=uxEditor.model,s=m.snapshot();m.validate(s);m.restore(s);if(JSON.stringify(m.snapshot())!==JSON.stringify(s))throw Error('工程往返改覆盖');
                    const bad=JSON.parse(JSON.stringify(s));bad.nodes.find(n=>n.id==='L16.down').parent='L16.down';let rejected=false;try{m.load(bad);}catch(e){rejected=true;}if(!rejected)throw Error('循环树未拒绝');
                    const corrupt=JSON.parse(JSON.stringify(s));corrupt.nodes.find(n=>n.id==='L16.down').local[0]=NaN;rejected=false;try{m.load(corrupt);}catch(e){rejected=true;}if(!rejected)throw Error('非法矩阵未拒绝');return true;
                }''')
                page.evaluate('(s)=>{uxEditor.model.load(s);uxEditor.select(["L16.down"]);}',initial)
                check('curve_math_insert_inverse_and_lut','''()=>{
                    const c=CurveMath.preset('s'),r=CurveMath.insert(c,.45),lut=CurveMath.table(c);let splitError=0,lutError=0;
                    for(let i=0;i<=2000;i++){const x=i/2000,v=CurveMath.value(c,x);splitError=Math.max(splitError,Math.abs(v-CurveMath.value(r.curve,x)));lutError=Math.max(lutError,Math.abs(v-CurveMath.lookup(lut,x)));}
                    if(splitError>1e-5||lutError>1e-3)throw Error('曲线分段／查表误差过大');
                    if(CurveMath.value(CurveMath.preset('reverse'),0)!==1||CurveMath.value(CurveMath.preset('reverse'),1)!==0)throw Error('反转不自由');return {splitError,lutError,lut_size:lut.length};
                }''')
                page.locator('svg[aria-label="多点灰度曲线"]').scroll_into_view_if_needed()
                history=page.evaluate('() => uxEditor.model.history.length')
                page.locator('.curve-node[data-index="0"]').click()
                assert page.evaluate('() => Object.keys(uxEditor.model.nodes.get("L16.down").overrides).length')==0
                assert page.evaluate('() => uxEditor.model.history.length')==history
                page.locator('#curve-add').click();page.wait_for_function('uxEditor.model.resolve("L16.down","curve").value.nodes.length===3')
                box=page.locator('.curve-node[data-index="1"]').bounding_box();page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);history=page.evaluate('() => uxEditor.model.history.length')
                page.mouse.down();page.mouse.move(box['x']+35,box['y']-30,steps=8);page.mouse.up()
                page.wait_for_function('uxEditor.results[0]?.settings.curve.nodes.length===3')
                assert page.evaluate('() => uxEditor.model.history.length')==history+1
                cases.append({'name':'actual_curve_click_add_drag_single_undo','result':True})
                page.locator('#curve-inherit').click();page.wait_for_function('!Object.hasOwn(uxEditor.model.nodes.get("L16.down").overrides,"curve")')
                check('gray_export_same_as_preview_no_mutation','''async()=>{
                    const a=uxEditor;await a.refreshData();const r=a.results[0],old=r.pieces[0].gray.slice();a.scene.exposure=2;a.scene.drawSnow(a.results);
                    if(old.some((v,i)=>v!==r.pieces[0].gray[i]))throw Error('屏幕曝光改变输出');const saved=await a.mapping(['L16.down']);
                    if(saved.results[0].pieces[0].gray.some((v,i)=>v!==r.pieces[0].gray[i]))throw Error('保存与预览灰度不一致');
                    a.scene.exposure=1;a.scene.drawSnow([]);return {saved_count:saved.results[0].pieces[0].gray.length};
                }''')
                page.get_by_text('框、壳与雪花几何',exact=True).click();page.locator('#field-frameGray').fill('0.27');page.locator('#field-frameGray').press('Tab')
                page.wait_for_function('uxEditor.model.resolve("L16.down","frameGray").value===.27')
                assert page.evaluate('() => Object.keys(uxEditor.model.nodes.get("L16.down").overrides).join()')=='frameGray'
                page.evaluate('() => uxEditor.tree.revealTo(["global"])')
                page.locator('[data-id="global"]').click();assert page.locator('#property-kind').inner_text()=='全局配置'
                assert not page.locator('[data-trs]').count()
                page.evaluate('() => uxEditor.tree.revealTo(["ghost-1"])')
                page.locator('[data-id="ghost-1"]').click();assert not page.locator('#curve-add').count()
                page.get_by_text('毛坯基本特征与参照',exact=True).click() if not page.locator('[data-ghost-key="0"]').is_visible() else None
                page.locator('[data-ghost-key="0"]').fill('30');page.locator('[data-ghost-key="0"]').press('Tab')
                assert page.evaluate('() => uxEditor.model.nodes.get("ghost-1").data.dims[0]')==30
                cases.append({'name':'actual_inspector_global_ghost_sparse_edit','result':True})
                check('all_cached_types_and_missing_layers','''async()=>{
                    const a=uxEditor,rows=[];for(const b of a.data.manifest.blocks){const r=await a.data.evaluate(b.id,a.model);if(!r.pieces.length||r.pieces.some(p=>p.raw.length!==p.gray.length))throw Error('真实缓存缺块');rows.push({id:b.id,pieces:r.pieces.length,count:r.count});}
                    const absent=await a.data.evaluate('L01.down',a.model),mtp=await a.data.evaluate('mtp',a.model);
                    if(absent.count||mtp.count)throw Error('未计算块填了模拟');return {groups:rows.length,tensors:a.data.cache.size,missing:absent.status,mtp:mtp.status};
                }''')
                page.evaluate('() => uxEditor.select(["L16.down"])');page.wait_for_function('uxEditor.results[0]?.id==="L16.down"')
                check('rendered_snow_contributes_pixels','''()=>{
                    const s=uxEditor.scene,r=s.renderer,g=r.getContext(),w=g.drawingBufferWidth,h=g.drawingBufferHeight,on=new Uint8Array(w*h*4),off=new Uint8Array(w*h*4);
                    s.drawSnow(uxEditor.results);s.fit(['L16.down']);s.render();g.readPixels(0,0,w,h,g.RGBA,g.UNSIGNED_BYTE,on);s.snow.visible=false;s.render();g.readPixels(0,0,w,h,g.RGBA,g.UNSIGNED_BYTE,off);s.snow.visible=true;s.render();
                    let count=0;for(let i=0;i<on.length;i+=4)if(on[i]!==off[i]||on[i+1]!==off[i+1]||on[i+2]!==off[i+2])count++;if(!count)throw Error('真实雪花未贡献像素');const instances=s.renderedSnow;s.drawSnow([]);return {pixels:count,instances};
                }''')
                page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(250)
                mobile=page.evaluate('() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,tree:document.querySelector(".tree-panel").getBoundingClientRect().height,props:document.querySelector(".property-panel").getBoundingClientRect().height})')
                assert mobile['scroll']<=mobile['width'] and mobile['tree']>0 and mobile['props']>0,mobile
                cases.append({'name':'mobile_panels_no_overflow','result':mobile})
                page.set_viewport_size({'width':1600,'height':1050});page.wait_for_timeout(100)
                page.evaluate('(s)=>{uxEditor.model.load(s);uxEditor.select(["L16.down"]);}',initial)
                check('visual_tree_identity_and_invalid_window','''()=>{
                    const m=uxEditor.model;if(m.children('vlayer-0').length!==4||m.nodes.get('V00.attn').parent!=='vlayer-0')throw Error('视觉层树组织错误');
                    const s=JSON.stringify(m.snapshot());try{m.set('L16.down','black',2);}catch(e){}if(JSON.stringify(m.snapshot())!==s)throw Error('无效窗口修改了状态');
                    const d=m.snapshot();d.nodes.find(n=>n.id==='global').overrides={pitch:.1};let rejected=false;try{m.load(d);}catch(e){rejected=true;}if(!rejected)throw Error('非法全局覆盖未拒绝');return true;
                }''')
                check('geometry_recipe_change_during_reparent_preserves_world','''()=>{
                    const a=uxEditor,m=a.model,g=m.group(['L16.gate','L16.up','L16.down']),target=m.group(['L00.up']);m.set(target,'gap',.1);m.set(target,'widthMode','params');
                    const ids=m.children(g).map(n=>n.id),before=ids.map(id=>m.world(id).toArray());m.commit(()=>ids.forEach(id=>m.move(id,target)),true);
                    ids.forEach((id,i)=>{if(m.world(id).toArray().some((v,k)=>Math.abs(v-before[i][k])>1e-8))throw Error('配方切换时迁组世界变换不稳');});return true;
                }''')
                page.evaluate('(s)=>{uxEditor.model.load(s);uxEditor.select(["L16.down"]);}',initial)
                page.evaluate('() => uxEditor.tree.revealTo(["L16.up","L16.down","L16.gate"])')
                page.locator('[data-id="L16.up"]').click();page.locator('[data-id="L16.down"]').click(modifiers=['Shift'])
                page.wait_for_function('uxEditor.selected.length===2')
                page.locator('#group').click();page.wait_for_function('uxEditor.selected.length===1&&uxEditor.model.nodes.get(uxEditor.selected[0]).type==="group"')
                gid=page.evaluate('() => uxEditor.selected[0]')
                page.get_by_text('框、壳与雪花几何',exact=True).click() if not page.locator('#field-frameGray').is_visible() else None
                page.locator('#field-frameGray').fill('0.33');page.locator('#field-frameGray').press('Tab')
                page.locator('#ungroup').click();page.locator('#confirm-ok').click();page.wait_for_function('(id)=>!uxEditor.model.nodes.has(id)',arg=gid)
                assert not page.evaluate('() => Object.hasOwn(uxEditor.model.nodes.get("L16.down").overrides,"frameGray")')
                cases.append({'name':'actual_tree_shift_group_default_ungroup','result':True})
                page.evaluate('() => uxEditor.select(["L16.down"])');page.wait_for_function('uxEditor.results[0]?.id==="L16.down"')
                page.evaluate('() => uxEditor.tree.revealTo(["global"])')
                page.locator('[data-id="global"]').click();page.wait_for_function('uxEditor.selected[0]==="global"&&uxEditor.results[0]?.id==="L16.down"')
                before_gray=page.evaluate('() => Array.from(uxEditor.results[0].pieces[0].gray.slice(0,10))')
                page.locator('#curve-preset').select_option('reverse');page.locator('#apply-preset').click();page.wait_for_function('uxEditor.results[0].settings.curve.nodes[0].y===1')
                assert page.evaluate('() => Array.from(uxEditor.results[0].pieces[0].gray.slice(0,10))')!=before_gray
                assert not page.evaluate('() => Object.hasOwn(uxEditor.model.nodes.get("L16.down").overrides,"curve")')
                cases.append({'name':'actual_global_curve_keeps_reference_feedback','result':True})
                check('save_buttons_capture_matching_payload','''async()=>{
                    const a=uxEditor;let payload;const oldCreate=URL.createObjectURL,oldClick=HTMLAnchorElement.prototype.click;
                    try{URL.createObjectURL=b=>{payload=b;return 'blob:verify';};HTMLAnchorElement.prototype.click=function(){};
                        document.getElementById('save-project').click();const project=JSON.parse(await payload.text());a.model.validate(project);
                        a.select(['L16.down']);await a.refreshData();document.getElementById('save-mapping').click();
                        for(let i=0;i<100&&!document.getElementById('save-mapping').disabled;i++)await new Promise(r=>setTimeout(r,10));
                        for(let i=0;i<100&&document.getElementById('save-mapping').disabled;i++)await new Promise(r=>setTimeout(r,10));
                        const mapping=JSON.parse(await payload.text());if(mapping.kind!=='snowglass.ux-gray-mapping.v1'||mapping.results[0].pieces[0].gray.some((v,i)=>v!==a.results[0].pieces[0].gray[i]))throw Error('按钮保存与预览不同');
                        return {project_kind:project.kind,mapping_kind:mapping.kind,count:mapping.results[0].pieces[0].gray.length};
                    }finally{URL.createObjectURL=oldCreate;HTMLAnchorElement.prototype.click=oldClick;}
                }''')
                with page.expect_file_chooser() as chooser:page.locator('#open-project').click()
                saved=page.evaluate('() => uxEditor.getProject()')
                chooser.value.set_files({'name':'roundtrip.json','mimeType':'application/json','buffer':json.dumps(saved,ensure_ascii=False).encode('utf-8')})
                page.wait_for_function('document.getElementById("status").textContent.includes("新版工程已恢复")')
                cases.append({'name':'actual_open_project_roundtrip','result':True})
                check('four_cached_channels_and_independent_mask','''async()=>{
                    const a=uxEditor,m=new UXModel.Model(a.model.topo,a.model.provenance);m.nodes.get('global').values.sourceConvention='hf';let channels=0;
                    for(const channel of ['full','feature','rowcol','residual']){m.nodes.get('global').values.channel=channel;for(const b of a.data.manifest.blocks){const r=await a.data.evaluate(b.id,m);if(r.count<=0||r.pieces.some(p=>p.gray.some(v=>!Number.isFinite(v))))throw Error('统计通道无效');channels++;}}
                    m.nodes.get('global').values.channel='full';m.nodes.get('global').values.filter=true;const one=await a.data.evaluate('L16.down',m),mask=Array.from(one.pieces[0].mask);
                    m.nodes.get('global').values.curve=CurveMath.preset('reverse');const two=await a.data.evaluate('L16.down',m);if(mask.some((v,i)=>v!==two.pieces[0].mask[i]))throw Error('曲线改变筛选位置');
                    return {group_channel_cases:channels,mask_independent:true};
                }''')
                page.evaluate('(s)=>{uxEditor.model.load(s);uxEditor.select(["L16.down"]);}',initial)
                check('gumball_events_update_shared_numeric_state','''()=>{
                    const a=uxEditor,s=a.scene,m=a.model,before=m.bounds(['L16.down']).getCenter(new THREE.Vector3()).x,count=m.history.length;
                    s.syncPivot();s.pivot.updateMatrixWorld(true);s.gumball.dispatchEvent({type:'dragging-changed',value:true});s.gumball.dragging=true;
                    s.pivot.position.x+=.7;s.pivot.updateMatrixWorld(true);s.gumball.dispatchEvent({type:'objectChange'});s.gumball.dragging=false;s.gumball.dispatchEvent({type:'dragging-changed',value:false});
                    const after=m.bounds(['L16.down']).getCenter(new THREE.Vector3()).x,input=document.querySelector('[data-trs="t"][data-axis="0"]'),stored=m.localTRS('L16.down').t[0];
                    if(Math.abs(after-before-.7)>1e-8||Math.abs(+input.value-stored)>1e-4||m.history.length!==count+1)throw Error('手柄和数值未共用状态／撤销不是单步');return {delta:after-before,numeric:+input.value,stored};
                }''')
                page.get_by_text('变换 · 相对默认位置',exact=True).click() if not page.locator('[data-trs="t"][data-axis="0"]').is_visible() else None
                x=page.evaluate('() => uxEditor.model.localTRS("L16.down").t[0]')
                page.locator('[data-trs="t"][data-axis="0"]').fill(str(x+1));page.locator('[data-trs="t"][data-axis="0"]').press('Tab')
                actual=page.evaluate('() => uxEditor.model.localTRS("L16.down").t[0]')
                assert abs(actual-x-1)<1e-6
                cases.append({'name':'actual_numeric_transform_input','result':{'delta':actual-x}})
                check('compact_toolbar_and_help_popover','''()=>{
                    const top=[...document.querySelectorAll('.view-tools > button, .view-tools .seg button')];
                    if(top.length>8)throw Error('工具条仍有过多常驻按钮：'+top.length);
                    const menu=document.getElementById('view-menu-list'),keys=document.getElementById('keys-pop');
                    if(!menu.hidden||!keys.hidden)throw Error('菜单／弹层默认应关闭');
                    document.getElementById('view-menu-button').click();
                    if(menu.hidden)throw Error('视图菜单打不开');
                    document.getElementById('keys-button').click();
                    if(!menu.hidden||keys.hidden)throw Error('两个面板没有互斥');
                    if(!keys.textContent.includes('跳选'))throw Error('键位表内容缺失');
                    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));
                    if(!keys.hidden)throw Error('Esc 没关闭弹层');
                    const treeTools=document.querySelectorAll('.tree-tools button').length;
                    if(treeTools<3)throw Error('选择操作没有移到树面板');
                    return {top_buttons:top.length,tree_tools:treeTools};
                }''')
                page.evaluate('() => document.getElementById("view-preview").click()')
                page.wait_for_function('document.getElementById("view-preview").getAttribute("aria-selected")==="true"',timeout=180000)
                prev=page.evaluate('() => ({snow:uxEditor.scene.renderedSnow,blocks:uxEditor.results.length,meshes:uxEditor.scene.snowMeshes.size,hidden:document.getElementById("progress").hidden,badge:document.getElementById("preview-state").textContent,positive:uxEditor.results.reduce((n,r)=>n+r.positive,0)})')
                assert prev['snow']>0 and prev['hidden'],prev
                assert prev['blocks']==65 and prev['meshes']>=65,prev
                assert prev['snow']>=prev['positive']>0,prev
                cases.append({'name':'preview_shows_all_cached_snow','result':prev})
                page.evaluate('() => uxEditor.model.set("L16.down","white",0.8)')
                page.wait_for_timeout(1500)
                after_gray=page.evaluate('() => uxEditor.scene.renderedSnow')
                assert after_gray>0,after_gray
                page.evaluate('() => document.getElementById("view-prepare").click()')
                page.wait_for_function('uxEditor.scene.renderedSnow===0',timeout=30000)
                assert page.evaluate('() => uxEditor.scene.snowMeshes.size')==0
                cases.append({'name':'preview_edit_and_return_to_prepare','result':{'preview_snow':prev['snow'],'after_gray':after_gray,'prepare_snow':0}})
                page.evaluate('(s)=>{uxEditor.model.load(s);uxEditor.select(["L16.down"]);}',initial)
                page.wait_for_function('uxEditor.selected[0]==="L16.down"')
                check('param_slider_and_number_are_paired','''()=>{
                    const m=uxEditor.model;
                    const el=document.getElementById('field-frameT'),wrap=el.closest('.prop-inputs');
                    if(!wrap)throw Error('数值参数没有滑块');
                    const rng=wrap.querySelector('input[type=range]');if(!rng)throw Error('缺滑块');
                    rng.value='0.2';rng.dispatchEvent(new Event('input',{bubbles:true}));
                    if(Math.abs(m.resolve('L16.down','frameT').value-.2)>1e-9)throw Error('滑块未改参数');
                    if(Math.abs(+document.getElementById('field-frameT').value-.2)>1e-6)throw Error('数字框未跟随滑块');
                    const num=document.getElementById('field-frameT');num.value='0.05';num.dispatchEvent(new Event('change',{bubbles:true}));
                    if(Math.abs(m.resolve('L16.down','frameT').value-.05)>1e-9)throw Error('数字框未改参数');
                    const rng2=document.getElementById('field-frameT').closest('.prop-inputs').querySelector('input[type=range]');
                    if(Math.abs(+rng2.value-.05)>1e-6)throw Error('滑块未跟随数字框');
                    return {frameT:m.resolve('L16.down','frameT').value};
                }''')
                check('zero_thickness_means_no_structure','''()=>{
                    const m=uxEditor.model,s=uxEditor.scene;
                    m.set('L16.down','frameT',.04);m.set('L16.down','shellT',.02);s.structure();const f0=s.frames.count,h0=s.shells.count;
                    m.set('L16.down','frameT',0);s.structure();const f1=s.frames.count;
                    m.set('L16.down','shellT',0);s.structure();const h1=s.shells.count;
                    if(f0-f1!==12)throw Error('框厚0没有移除12根方梁');
                    if(h0-h1!==6)throw Error('壳厚0没有移除6块板');
                    let rejected=false;try{m.set('L16.down','frameT',-.1);}catch(e){rejected=true;}if(!rejected)throw Error('负厚度未拒绝');return {frames:[f0,f1],shells:[h0,h1]};
                }''')
                check('label_text_is_per_object','''()=>{
                    const m=uxEditor.model,s=uxEditor.scene;
                    m.set('L16.down','labels',true);m.set('L16.down','labelText','自定义标签');s.structure();
                    if(s.labels.children.length<1)throw Error('标签未绘制');
                    const own=m.resolve('L16.down','labelText').own;
                    if(!own)throw Error('文字未建立局部覆盖');
                    if(m.resolve('L16.up','labelText').value!=='')throw Error('其他对象不应该跟着改');return {labels:s.labels.children.length};
                }''')
                check('label_is_part_of_output_contract','''async()=>{
                    const m=uxEditor.model;m.set('L16.down','labelText','冻结的模型');m.set('L16.down','labelOutput',true);
                    const doc=await uxEditor.mapping(['L16.down']),r=doc.results.find(x=>x.id==='L16.down');
                    if(!r.label||r.label.text!=='冻结的模型'||r.label.output!==true)throw Error('文字未进入导出定义');
                    if(!Array.isArray(r.label.anchor_world_mm)||r.label.anchor_world_mm.length!==3)throw Error('缺锚点位置');
                    if(!Array.isArray(r.label.offset_mm)||r.label.offset_mm.length!==3)throw Error('缺偏移');
                    if(!doc.label_pipeline)throw Error('缺管线边界说明');
                    m.set('L16.down','labelOutput',false);const off=await uxEditor.mapping(['L16.down']);
                    if(off.results[0].label.output!==false||off.results[0].label.screen_only!==true)throw Error('关闭输出未生效');
                    return {text:r.label.text,font:r.label.font,size_mm:r.label.size_mm,output:r.label.output};
                }''')
                page.evaluate('(s)=>{uxEditor.model.load(s);uxEditor.select(["L16.down"]);}',initial)
                page.wait_for_function('uxEditor.selected[0]==="L16.down"')
                page.evaluate('() => uxEditor.tree.revealTo(["L16.up","L16.down","L16.gate"])')
                page.locator('[data-id="L16.up"]').click();page.locator('[data-id="L16.down"]').click(modifiers=['Control'])
                page.wait_for_function('uxEditor.selected.length===2')
                page.locator('[data-id="L16.gate"]').click(modifiers=['Shift'])
                span=page.evaluate('() => uxEditor.selected.slice().sort()')
                assert span==['L16.down','L16.gate','L16.up'],span
                page.locator('[data-id="L16.up"]').click(modifiers=['Control'])
                assert page.evaluate('() => uxEditor.selected.includes("L16.up")') is False
                cases.append({'name':'tree_ctrl_toggle_and_shift_range','result':span})
                before_w=page.evaluate('() => document.getElementById("sidebar").getBoundingClientRect().width')
                page.locator('#sidebar-resizer').focus();page.keyboard.press('ArrowRight');page.keyboard.press('ArrowRight')
                after_w=page.evaluate('() => document.getElementById("sidebar").getBoundingClientRect().width')
                assert after_w>before_w+30,(before_w,after_w)
                cases.append({'name':'sidebar_width_keyboard_resize','result':{'before':before_w,'after':after_w}})
                page.evaluate('() => {document.documentElement.style.removeProperty("--sidebar-width");uxEditor.scene.resize();}')
                prop_before=page.evaluate('() => {const r=document.querySelector(".property-panel").getBoundingClientRect();return [r.x,r.y,r.width];}')
                page.locator('[data-id="L16.down"]').click()
                prop_after=page.evaluate('() => {const r=document.querySelector(".property-panel").getBoundingClientRect();return [r.x,r.y,r.width];}')
                assert prop_before==prop_after,(prop_before,prop_after)
                cases.append({'name':'property_panel_fixed_position','result':prop_after})
                check('gumball_follows_object_orientation_and_survives_camera','''()=>{
                    const m=uxEditor.model,s=uxEditor.scene;m.setLocalTRS('L16.down',{t:[0,0,0],r:[0,0,.7],s:[1,1,1]});
                    s.select(['L16.down']);s.syncPivot();const q=new THREE.Quaternion();m.objectFrame('L16.down').decompose(new THREE.Vector3(),q,new THREE.Vector3());
                    if(s.pivot.quaternion.angleTo(q)>1e-6)throw Error('手柄姿态没有跟随对象旋转');
                    const pos=s.pivot.position.clone();s.camera.position.x+=6;s.orbit.update();s.render();
                    if(s.pivot.position.distanceTo(pos)>1e-9||s.pivot.quaternion.angleTo(q)>1e-6)throw Error('视角变化重置了手柄');
                    s.structure();if(s.highlights.children.length!==3)throw Error('选中高亮层数不对');return {angle:s.pivot.quaternion.angleTo(q),highlights:s.highlights.children.length};
                }''')
                page.evaluate('(s)=>{uxEditor.model.load(s);uxEditor.select(["L16.down"]);uxEditor.scene.fit(["L16.down"]);}',initial)
                page.wait_for_timeout(150)
                vb=page.locator('#view').bounding_box()
                page.mouse.move(vb['x']+vb['width']*.40,vb['y']+vb['height']*.30)
                page.keyboard.down('Shift');page.mouse.down();page.mouse.move(vb['x']+vb['width']*.96,vb['y']+vb['height']*.94,steps=10);page.mouse.up();page.keyboard.up('Shift')
                page.wait_for_timeout(120)
                boxed=page.evaluate('() => uxEditor.selected.slice()')
                assert 'L16.down' in boxed,boxed
                cases.append({'name':'actual_shift_drag_box_select','result':boxed})
                filepage=browser.new_page(viewport={'width':1200,'height':800})
                filepage.goto((bundle/'index.html').as_uri(),wait_until='domcontentloaded',timeout=15000)
                filepage.wait_for_selector('#boot-error:not([hidden])',timeout=5000)
                boot=filepage.locator('#boot-error').inner_text()
                assert '本地服务' in boot and 'http://127.0.0.1:8128/' in boot,boot
                assert 'file://' in boot
                cases.append({'name':'file_protocol_shows_actionable_banner','result':boot.splitlines()[0]})
                filepage.close()
                assert not errors,errors;browser.close()
    except Exception as e:
        failure=str(e)
    after={name:sha(source_path(name)) for name in provenance['source_hashes']};assert before==after,'旧文件被修改'
    assert frozen_math=={name:sha(ROOT/'scripts'/name) for name in frozen_math},'验证期间科学核心被修改'
    assert asset_hashes=={str(p.relative_to(bundle)):sha(p) for p in assets},'测试期间新版代码被修改'
    report={'phase':args.phase,'passed':failure is None,'failure':failure,'page_errors':errors,'diagnostic':diagnostic,'cases':cases,'source_unchanged':True,'frozen_math_sha256':frozen_math,'assets_sha256':asset_hashes,'test_sha256':sha(Path(__file__)),'seconds':time.monotonic()-start}
    with (output/'checks.json').open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,allow_nan=False,indent=2)
    print(json.dumps({'passed':report['passed'],'cases':len(cases),'failure':failure,'report':str(output/'checks.json'),'source_unchanged':True},ensure_ascii=False),flush=True)
    if failure:raise SystemExit(1)


if __name__=='__main__':main()

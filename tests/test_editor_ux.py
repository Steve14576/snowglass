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
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--folder',type=Path,required=True);parser.add_argument('--phase',choices=['probe','full'],default='full');args=parser.parse_args()
    bundle=args.folder.resolve();provenance=json.loads((bundle/'provenance.json').read_text(encoding='utf-8'))
    before={name:sha(ROOT/name) for name in provenance['source_hashes']};assert before==provenance['source_hashes']
    output=bundle/('verification-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));output.mkdir(exist_ok=False)
    assets=[bundle/'index.html',*list((bundle/'assets').glob('*'))];asset_hashes={str(p.relative_to(bundle)):sha(p) for p in assets}
    cases=[];errors=[];pending=set();diagnostic={};start=time.monotonic();failure=None
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True,args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'])
            page=browser.new_page(viewport={'width':1600,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:pending.add(r.url));page.on('requestfinished',lambda r:pending.discard(r.url));page.on('requestfailed',lambda r:pending.discard(r.url))
            try:
                page.goto('http://127.0.0.1:8128/',wait_until='domcontentloaded',timeout=15000)
                page.wait_for_function('window.uxEditor && uxEditor.results.length && uxEditor.scene.renderedSnow>0',timeout=45000)
            except Exception:
                diagnostic={'status':page.locator('#status').inner_text(timeout=1000),'pending':sorted(pending)}
                raise
            baseline=page.evaluate('''()=>{
                const a=uxEditor,m=a.model,size=m.bounds(['work']).getSize(new THREE.Vector3()).toArray(),old=SnowLayout(m.topo).bounds.getSize(new THREE.Vector3()).toArray();
                if(size.some((v,i)=>Math.abs(v-old[i])>1e-9))throw Error('未保持4.2默认排布');
                if(a.results[0].count!==8192||a.scene.renderedSnow!==8192)throw Error('真实格数错误');
                const t=document.querySelector('.tree-panel').getBoundingClientRect(),p=document.querySelector('.property-panel').getBoundingClientRect();
                if(t.x<innerWidth/2||p.y<t.bottom-1)throw Error('不是右上树／右下属性');
                return {nodes:m.nodes.size,blocks:[...m.nodes.values()].filter(n=>n.type==='block').length,real_count:a.results[0].count,dimensions:size,tree_y:t.y,properties_y:p.y};
            }''')
            cases.append({'name':'startup_real_geometry_and_layout','result':baseline})
            print(json.dumps({'baseline':baseline,'errors':errors},ensure_ascii=False),flush=True)
            if errors:raise AssertionError(errors)
            if args.phase=='probe':
                diag=page.evaluate('''()=>{
                    const s=uxEditor.scene,r=s.renderer,g=r.getContext(),w=g.drawingBufferWidth,h=g.drawingBufferHeight;
                    function compare(){const on=new Uint8Array(w*h*4),off=new Uint8Array(w*h*4);s.render();g.readPixels(0,0,w,h,g.RGBA,g.UNSIGNED_BYTE,on);s.snow.visible=false;s.render();g.readPixels(0,0,w,h,g.RGBA,g.UNSIGNED_BYTE,off);s.snow.visible=true;
                        let count=0,max=0;for(let i=0;i<on.length;i+=4){if(on[i]!==off[i]||on[i+1]!==off[i+1]||on[i+2]!==off[i+2])count++;max=Math.max(max,on[i],on[i+1],on[i+2]);}return {pixels:count,max};}
                    s.fit(['L16.down']);const normal=compare();s.frames.material.needsUpdate=true;s.shells.material.needsUpdate=true;const recompiled=compare();const objects=[s.frames,s.shells,s.proxy,s.ghosts,s.highlights,s.labels,s.gumball];const old=objects.map(o=>o.visible);objects.forEach(o=>o.visible=false);const isolated=compare();objects.forEach((o,i)=>o.visible=old[i]);s.render();
                    const mesh=s.snow.children[0],mat=new THREE.Matrix4();mesh.getMatrixAt(0,mat);return {normal,recompiled,isolated,gl_error:g.getError(),lost:g.isContextLost(),buffer:[w,h],meshes:s.snow.children.length,count:s.renderedSnow,first_matrix:mat.toArray(),first_colors:Array.from(mesh.instanceColor.array.slice(0,9)),camera:s.camera.position.toArray()};
                }''')
                print(json.dumps({'render_probe':diag},ensure_ascii=False),flush=True);cases.append({'name':'render_probe','result':diag});browser.close()
            else:
                initial=page.evaluate('() => uxEditor.model.snapshot()')
                def check(name,script):
                    result=page.evaluate(script);cases.append({'name':name,'result':result});print(json.dumps({'case':name,'status':'pass'},ensure_ascii=False),flush=True)
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
                    a.select([g]);await a.refreshData();const mesh=a.scene.snow.children[0],mat=new THREE.Matrix4();mesh.getMatrixAt(0,mat);
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
                    a.scene.exposure=1;a.scene.drawSnow(a.results);return {saved_count:saved.results[0].pieces[0].gray.length};
                }''')
                page.get_by_text('框、壳与雪花几何',exact=True).click();page.locator('#field-frameGray').fill('0.27');page.locator('#field-frameGray').press('Tab')
                page.wait_for_function('uxEditor.model.resolve("L16.down","frameGray").value===.27')
                assert page.evaluate('() => Object.keys(uxEditor.model.nodes.get("L16.down").overrides).join()')=='frameGray'
                page.locator('[data-id="global"]').click();assert page.locator('#property-kind').inner_text()=='全局配置'
                assert not page.locator('[data-transform]').count()
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
                    s.fit(['L16.down']);s.render();g.readPixels(0,0,w,h,g.RGBA,g.UNSIGNED_BYTE,on);s.snow.visible=false;s.render();g.readPixels(0,0,w,h,g.RGBA,g.UNSIGNED_BYTE,off);s.snow.visible=true;s.render();
                    let count=0;for(let i=0;i<on.length;i+=4)if(on[i]!==off[i]||on[i+1]!==off[i+1]||on[i+2]!==off[i+2])count++;if(!count)throw Error('真实雪花未贡献像素');return {pixels:count,instances:s.renderedSnow};
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
                page.locator('[data-id="L16.up"]').click();page.locator('[data-id="L16.down"]').click(modifiers=['Shift'])
                page.locator('#group').click();page.wait_for_function('uxEditor.selected.length===1&&uxEditor.model.nodes.get(uxEditor.selected[0]).type==="group"')
                gid=page.evaluate('() => uxEditor.selected[0]')
                page.get_by_text('框、壳与雪花几何',exact=True).click() if not page.locator('#field-frameGray').is_visible() else None
                page.locator('#field-frameGray').fill('0.33');page.locator('#field-frameGray').press('Tab')
                page.locator('#ungroup').click();page.locator('#confirm-ok').click();page.wait_for_function('(id)=>!uxEditor.model.nodes.has(id)',arg=gid)
                assert not page.evaluate('() => Object.hasOwn(uxEditor.model.nodes.get("L16.down").overrides,"frameGray")')
                cases.append({'name':'actual_tree_shift_group_default_ungroup','result':True})
                page.evaluate('() => uxEditor.select(["L16.down"])');page.wait_for_function('uxEditor.results[0]?.id==="L16.down"')
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
                    const a=uxEditor,m=new UXModel.Model(a.model.topo,a.model.provenance);let channels=0;
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
                    const after=m.bounds(['L16.down']).getCenter(new THREE.Vector3()).x,input=document.querySelector('[data-transform="position"][data-axis="0"]');
                    if(Math.abs(after-before-.7)>1e-8||Math.abs(+input.value-after)>1e-4||m.history.length!==count+1)throw Error('手柄和数值未共用状态／撤销不是单步');return {delta:after-before,numeric:+input.value};
                }''')
                page.get_by_text('变换与实际尺寸',exact=True).click() if not page.locator('[data-transform="position"][data-axis="0"]').is_visible() else None
                x=page.evaluate('() => uxEditor.model.bounds(["L16.down"]).getCenter(new THREE.Vector3()).x')
                page.locator('[data-transform="position"][data-axis="0"]').fill(str(x+1));page.locator('[data-transform="position"][data-axis="0"]').press('Tab')
                actual=page.evaluate('() => uxEditor.model.bounds(["L16.down"]).getCenter(new THREE.Vector3()).x')
                assert abs(actual-x-1)<1e-6
                cases.append({'name':'actual_numeric_transform_input','result':{'delta':actual-x}})
                assert not errors,errors;browser.close()
    except Exception as e:
        failure=str(e)
    after={name:sha(ROOT/name) for name in provenance['source_hashes']};assert before==after,'旧文件被修改'
    assert asset_hashes=={str(p.relative_to(bundle)):sha(p) for p in assets},'测试期间新版代码被修改'
    report={'phase':args.phase,'passed':failure is None,'failure':failure,'page_errors':errors,'diagnostic':diagnostic,'cases':cases,'source_unchanged':True,'assets_sha256':asset_hashes,'test_sha256':sha(Path(__file__)),'seconds':time.monotonic()-start}
    with (output/'checks.json').open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,allow_nan=False,indent=2)
    print(json.dumps({'passed':report['passed'],'cases':len(cases),'failure':failure,'report':str(output/'checks.json'),'source_unchanged':True},ensure_ascii=False),flush=True)
    if failure:raise SystemExit(1)


if __name__=='__main__':main()

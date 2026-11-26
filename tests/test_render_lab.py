# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.50,<2"]
# ///
"""静态画质对照的只读工程、真实缓存、实际控件与主文件冻结核验；不截图、不读原权重。"""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'prototype/editor_ux/20261122-055413-124110'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8128/render_lab/')
    parser.add_argument('--probe', action='store_true', help='仅检查布局稳定性，不操作工程')
    args = parser.parse_args()
    frozen = [BUNDLE/'index.html', *list((BUNDLE/'assets').glob('*')), *list((ROOT/'scripts').glob('*.py'))]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in frozen}
    lab_files=list((BUNDLE/'render_lab').glob('*.js'))+[BUNDLE/'render_lab/index.html',BUNDLE/'render_lab/lab.css',Path(__file__),ROOT/'tests/layered_checks.js']
    lab_hashes={str(p.relative_to(ROOT)):sha(p) for p in lab_files}
    cases, errors, posts, http_errors = [], [], [], []
    failure = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True, args=['--disable-background-timer-throttling', '--disable-renderer-backgrounding'])
            context = browser.new_context(viewport={'width':1440,'height':1050}, device_scale_factor=2)
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
            page.on('request', lambda r: posts.append(r.url) if r.method != 'GET' else None)
            page.on('response',lambda r:http_errors.append({'url':r.url,'status':r.status}) if r.status>=400 else None)
            page.goto(args.url + '?scope=none&comparison=resolution', wait_until='domcontentloaded', timeout=20000)
            page.wait_for_function('window.renderLab && !renderLab.busy', timeout=90000)
            initial = page.evaluate('()=>{const gl=renderLab.view.scene.renderer.getContext(),ext=gl.getExtension("WEBGL_debug_renderer_info");return {...renderLab.evidence(),stored:localStorage.length,autoTask:renderLab.state.autoTask,tasks:renderLab.state.tasks,groups:renderLab.state.data.groups.size,noticeHidden:document.getElementById("lab-notice").hidden,notice:document.getElementById("lab-notice").textContent,renderer:ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):"未公开"};}')
            assert initial['stored'] == 0 and initial['labels'] == 0
            assert initial['autoTask'] == 'slice-20261123-015539-615436', initial['autoTask']
            assert initial['tasks'] == ['slice-20261123-015539-615436'] and initial['groups'] == 369
            assert initial['noticeHidden'] is False and '没有读到主工程' in initial['notice']
            if args.probe:
                for _ in range(5):
                    print(json.dumps(page.evaluate('()=>({box:document.getElementById("read-project").getBoundingClientRect().toJSON(),view:document.getElementById("view").getBoundingClientRect().toJSON(),disabled:document.getElementById("read-project").disabled,status:document.getElementById("status").textContent})'),ensure_ascii=False),flush=True)
                    page.wait_for_timeout(300)
                browser.close()
                return
            cases.append({'name':'no_project_reads_completed_full_slice_and_says_labels_are_missing','result':{k:initial[k] for k in ('autoTask','groups','notice','ratio','renderer')}})
            full = page.evaluate('''async()=>{const r=await renderLab.source.evaluate(renderLab.state,'all',()=>{});
                return {requested:r.requested,blocks:r.results.length,cells:r.results.reduce((s,x)=>s+x.count,0),failures:r.failures.slice(0,3)};}''')
            assert full['blocks'] == 369 and full['cells'] == 3620608 and not full['failures'], full
            cases.append({'name':'full_range_slice_matches_369_blocks_and_3620608_cells','result':full})
            # 标签只在隔离测试模型中生成，绝非用户工程；经主生成器和主状态模型保存。
            fixture = page.evaluate('''()=>{
                const lab=renderLab,m=new UXModel.Model(lab.source.topo,lab.source.provenance);
                m.set('global','sourceConvention','hf');m.set('L16.down','frameT',.08);
                const group=m.createLabels(m.planLabels('L16.down')),ids=m.children(group).map(n=>n.id);
                m.setLabelText(ids[0],'同一主工程 · 长中文标签');m.set(group,'labelSize',.9);
                m.setLabelAlignment(group,'left');m.setLabelCenter(group,'individual');m.set(ids[1],'labelEnabled',false);
                m.set(ids[2],'labelSize',.45);m.setLocalTRS(group,{t:[.3,.2,0],r:[0,.08,0],s:[1,1,1]});
                return {...m.snapshot(),slice:{tasks:[]},view:{selected:['L16.down'],preview:['L16.down'],isolate:false,
                    exposure:1.3,camera:[13,-64,12],target:[3,0,0],open:[]}};
            }''')
            text = json.dumps(fixture, ensure_ascii=False)
            page.evaluate('(text)=>localStorage.setItem(RenderLabIO.storageKeys[0],text)', text)
            page.locator('#scope').select_option('selected')
            page.wait_for_function('!renderLab.busy', timeout=60000)
            page.locator('#read-project').click(timeout=60000)
            page.wait_for_function('!renderLab.busy && renderLab.state.doc?.nodes.some(n=>n.type==="label")', timeout=90000)
            restored = page.evaluate('''()=>{
                const lab=renderLab,m=lab.state.model;
                return {labels:m.annotations(['project']),evidence:lab.evidence(),stored:localStorage.getItem(RenderLabIO.storageKeys[0]),
                    model:JSON.stringify(m.snapshot()),camera:lab.view.scene.camera.position.toArray(),target:lab.view.scene.orbit.target.toArray()};
            }''')
            assert restored['stored'] == text and restored['evidence']['enabled'] == 31
            assert all(abs(a-b)<1e-8 for a,b in zip(restored['camera'],fixture['view']['camera']))
            assert all(abs(a-b)<1e-8 for a,b in zip(restored['target'],fixture['view']['target']))
            assert restored['labels'][0]['text'] == '同一主工程 · 长中文标签'
            cases.append({'name':'actual_main_storage_import_preserves_labels_layout_and_camera','result':{'labels':32,'enabled':31,'storage_unchanged':True}})
            page.locator('#scope').select_option('selected')
            page.wait_for_function('!renderLab.busy && renderLab.state.results.length===1', timeout=45000)
            invariant = '''async()=>{
                const lab=renderLab,hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new Uint8Array(a.buffer,a.byteOffset,a.byteLength)))).map(v=>v.toString(16).padStart(2,'0')).join('');
                const snow=[];for(const [key,m] of lab.view.scene.snowMeshes)snow.push([key,m.count,await hash(m.instanceMatrix.array),await hash(m.instanceColor.array)]);
                const gray=[];for(const r of lab.state.results)for(const p of r.pieces)gray.push([r.id,p.name,await hash(p.gray),await hash(p.mask)]);
                return {model:JSON.stringify(lab.state.model.snapshot()),labels:lab.state.model.annotations(['project']),snow,gray,
                    camera:lab.view.scene.camera.position.toArray().map(v=>Math.round(v*1e10)/1e10),target:lab.view.scene.orbit.target.toArray().map(v=>Math.round(v*1e10)/1e10),stored:localStorage.getItem(RenderLabIO.storageKeys[0])};
            }'''
            baseline = page.evaluate(invariant)
            page.locator('#profile-b').click()
            b = page.evaluate('()=>renderLab.evidence()')
            assert b['ratio'] == 1.75 and b['applied']['filter'] == 'linear'
            assert page.evaluate(invariant) == baseline
            page.locator('#profile-a').click()
            assert page.evaluate('()=>renderLab.evidence().ratio') == 1.25
            assert page.evaluate(invariant) == baseline
            cases.append({'name':'resolution_switch_preserves_all_gray_instance_and_label_bytes','result':{'a':1.25,'b':1.75,'snow':b['snow'],'one_webgl_canvas':page.locator('#view>canvas').count()==1}})
            page.locator('#comparison').select_option('filter');page.locator('#profile-b').click()
            filtered = page.evaluate('''()=>{
                const v=renderLab.view;return {evidence:v.evidence(),textures:[...v.scene.annotationView.textures.values()].map(i=>({mip:i.texture.generateMipmaps,min:i.texture.minFilter,aniso:i.texture.anisotropy}))};
            }''')
            assert filtered['evidence']['ratio'] == 1.25
            if filtered['evidence']['webgl2']:
                assert all(t['mip'] and t['aniso'] >= 1 for t in filtered['textures'])
            else:
                assert filtered['evidence']['applied']['warning']
            assert page.evaluate(invariant) == baseline
            cases.append({'name':'filter_only_changes_sampling_not_text_size_or_snow','result':filtered['evidence']['applied']})
            page.locator('#filter-b').select_option('mipmap')
            assert page.locator('#comparison').input_value() == 'custom'
            assert page.evaluate(invariant) == baseline
            page.locator('#profile-a').click()
            assert page.evaluate('()=>[...renderLab.view.scene.annotationView.textures.values()].every(i=>!i.texture.generateMipmaps)')
            page.locator('#benchmark').click()
            page.wait_for_function('!renderLab.busy && renderLab.lastReport', timeout=90000)
            report = page.evaluate('()=>renderLab.lastReport')
            assert all(len(report['profiles'][k]['samples']) == 5 for k in ('a','b'))
            assert page.evaluate(invariant) == baseline
            cases.append({'name':'actual_benchmark_controls_preserve_scene_and_storage','result':report})
            page.locator('#comparison').select_option('layered')
            page.locator('#profile-a').click()
            a=page.evaluate('()=>renderLab.evidence()')
            page.locator('#profile-b').click()
            split=page.evaluate('()=>renderLab.evidence()')
            assert split['ratio']==a['ratio']==2
            assert split['applied']['sceneRatio']==1.25 and split['layered']['passes']==3
            assert split['layered']['sceneBuffer'][0]<split['buffer'][0] and split['layered']['sceneBuffer'][1]<split['buffer'][1]
            assert page.evaluate(invariant)==baseline
            cases.append({'name':'actual_layered_controls_share_final_resolution_and_preserve_instances','result':{'a':a['applied'],'b':split['applied'],'sceneBuffer':split['layered']['sceneBuffer'],'finalBuffer':split['buffer']}})
            pixel=page.evaluate('(source)=>{(0,eval)(source);return LayeredTests.run();}',(ROOT/'tests/layered_checks.js').read_text(encoding='utf-8'))
            assert pixel['supported'] and pixel['depthPreserved'],pixel
            assert page.evaluate(invariant)==baseline
            cases.append({'name':'layered_pixel_readback_preserves_front_back_depth_and_glyphs','result':pixel})
            page.locator('#benchmark').click()
            page.wait_for_function('!renderLab.busy && renderLab.lastReport',timeout=90000)
            split_report=page.evaluate('()=>renderLab.lastReport')
            assert split_report['profiles']['a']['pipeline']=='uniform' and split_report['profiles']['b']['pipeline']=='layered'
            assert split_report['profiles']['a']['ratio']==split_report['profiles']['b']['ratio']==2
            assert page.evaluate(invariant)==baseline
            cases.append({'name':'layered_benchmark_measures_all_passes','result':split_report})
            # 验证切片恢复只读取已经存在的取消任务产物，不续跑、不生成结果。
            task = page.evaluate('''async(doc)=>{
                const next=await renderLab.source.open({...doc,slice:{tasks:['slice-20261123-015006-356543']}},'只读测试任务',()=>{});
                return {tasks:next.tasks,warnings:next.warnings,groups:next.data.groups.size};
            }''', fixture)
            assert task['tasks'] == ['slice-20261123-015006-356543'] and not task['warnings']
            cases.append({'name':'existing_slice_task_manifest_is_restored_without_computation','result':task})
            page.locator('#project-file').set_input_files({'name':'main-project.json','mimeType':'application/json','buffer':text.encode('utf-8')})
            page.wait_for_function('!renderLab.busy && renderLab.state.name==="工程文件：main-project.json"', timeout=45000)
            assert page.evaluate(invariant) == baseline
            page.locator('#project-file').set_input_files({'name':'bad.json','mimeType':'application/json','buffer':b'{}'})
            page.wait_for_function('!renderLab.busy && document.getElementById("status").classList.contains("lab-error")')
            assert page.evaluate(invariant) == baseline
            cases.append({'name':'actual_file_import_and_invalid_file_keep_previous_scene','result':True})
            page.locator('#front').click();page.locator('#source-camera').click()
            assert page.evaluate(invariant) == baseline
            cases.append({'name':'restore_source_camera_after_view_only_navigation','result':True})
            page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(150)
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
            resize=page.evaluate('()=>{const v=renderLab.view,e=v.evidence();return {buffer:e.buffer,scene:e.layered.sceneBuffer,expected:[Math.floor(v.scene.renderer.getSize(new THREE.Vector2()).x*1.25),Math.floor(v.scene.renderer.getSize(new THREE.Vector2()).y*1.25)],valid:v.scene.renderer.getContext().getError()===0};}')
            assert resize['scene']==resize['expected'] and resize['valid'],resize
            cases.append({'name':'mobile_layout_and_layered_buffers_resize_together','result':resize})
            page.set_viewport_size({'width':1440,'height':1050});page.wait_for_timeout(150)
            page.locator('#scope').select_option('all')
            page.wait_for_function('!renderLab.busy && renderLab.evidence().snow===3620608',timeout=120000)
            full_scene=page.evaluate('()=>{renderLab.view.scene.render();const e=renderLab.evidence();if(renderLab.view.scene.renderer.getContext().getError()!==0)throw Error("全量分层GL错误");return e;}')
            assert full_scene['applied']['pipeline']=='layered' and full_scene['enabled']==31
            page.on('dialog',lambda d:d.accept())
            page.locator('#benchmark').click()
            page.wait_for_function('!renderLab.busy && renderLab.lastReport',timeout=120000)
            full_report=page.evaluate('()=>renderLab.lastReport')
            assert full_report['profiles']['a']['ratio']==full_report['profiles']['b']['ratio']==2
            cases.append({'name':'full_real_snow_layered_vs_uniform_render_and_short_measurement','result':{'snow':full_scene['snow'],'labels':full_scene['enabled'],'passes':full_scene['layered']['passes'],'renderer':initial['renderer'],'measurement':full_report}})
            assert not posts, posts
            assert not errors, errors
            assert not http_errors,http_errors
            assert page.evaluate('()=>localStorage.getItem(RenderLabIO.storageKeys[0])') == text
            browser.close()
    except Exception as e:
        failure = str(e)
    after = {str(p.relative_to(ROOT)):sha(p) for p in frozen}
    if hashes != after:
        failure = '主编辑器或科学脚本在验证期间被修改'
    lab_after={str(p.relative_to(ROOT)):sha(p) for p in lab_files}
    if lab_hashes!=lab_after:
        failure='验证期间对照页或测试代码被修改'
    report = {'passed':failure is None,'failure':failure,'cases':cases,'page_errors':errors,'non_get_requests':posts,'http_errors':http_errors,'main_files_unchanged':hashes==after,'main_sha256':hashes,'lab_sha256':lab_hashes,'lab_unchanged':lab_hashes==lab_after,'note':'隔离的Edge WebGL功能核验，实际后端见首项renderer；不截图、不读取原权重。短测不冒称完整编辑器FPS'}
    out = BUNDLE/'render_lab/verification'/('run-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True,exist_ok=False)
    with (out/'checks.json').open('x',encoding='utf-8') as f:
        json.dump(report,f,ensure_ascii=False,allow_nan=False,indent=2)
    print(json.dumps({'passed':report['passed'],'cases':len(cases),'failure':failure,'report':str(out/'checks.json')},ensure_ascii=False),flush=True)
    if failure:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

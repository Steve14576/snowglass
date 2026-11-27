# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.50,<2"]
# ///
"""主预览分批显示、真实数据不变、实际拖动和暂停恢复；不截图、不读原权重。"""
import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=ROOT/'prototype/editor_ux/20261122-055413-124110'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8128/')
    args=parser.parse_args()
    files=[BUNDLE/'index.html',*list((BUNDLE/'assets').glob('*')),Path(__file__)]
    before={str(p.relative_to(ROOT)):sha(p) for p in files}
    cases,errors,posts=[],[],[]
    failure=None
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1050},device_scale_factor=2)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
        page.context.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        try:
            page.goto(args.url,wait_until='domcontentloaded',timeout=20000)
            page.wait_for_function('window.uxEditor && uxEditor.results[0]?.count===8192',timeout=45000)
            baseline=page.evaluate('()=>({ratio:uxEditor.scene.renderer.getPixelRatio(),snow:uxEditor.scene.renderedSnow,prepared:uxEditor.viewMode})')
            assert baseline=={'ratio':2,'snow':0,'prepared':'prepare'},baseline
            cases.append({'name':'main_high_resolution_prepare_without_snow','result':baseline})
            fixture=page.evaluate('''()=>{
                const a=uxEditor,m=new UXModel.Model(a.model.topo,a.model.provenance);m.set('global','sourceConvention','hf');
                const g=m.createLabels(m.planLabels('L16.down'));m.setLabelAlignment(g,'right');m.setLabelCenter(g,'individual');
                return {...m.snapshot(),slice:{tasks:['slice-20261123-015539-615436']},view:{selected:['L16.down'],preview:['L16.down'],isolate:false,exposure:1,camera:[13,-64,12],target:[3,0,0],open:[]}};
            }''')
            page.evaluate('async doc=>{await uxEditor.loadProject(doc);uxEditor.select(["L16.down"]);}',fixture)
            page.wait_for_function('uxEditor.scene.annotationView.meshes.size===32 && uxEditor.results[0]?.id==="L16.down"',timeout=45000)
            fixed=page.evaluate('()=>JSON.stringify(uxEditor.model.snapshot())')
            page.evaluate('''()=>{window.previewStarted=performance.now();window.uiTicks=0;window.tickTimer=setInterval(()=>uiTicks++,10);document.getElementById('view-preview').click();document.getElementById('preview-pause').click();}''')
            paused=page.evaluate('()=>({view:uxEditor.viewMode,paused:uxEditor.previewStatus.paused,modal:document.getElementById("progress").hidden,elapsed:performance.now()-previewStarted})')
            assert paused['view']=='preview' and paused['paused'] and paused['modal'],paused
            cases.append({'name':'preview_entry_immediate_and_pause_without_modal','result':paused})
            page.locator('#view-prepare').click()
            page.wait_for_function('uxEditor.viewMode==="prepare" && uxEditor.scene.renderedSnow===0')
            assert page.evaluate('()=>uxEditor.scene.snowMeshes.size')==0
            cases.append({'name':'return_prepare_cancels_loading_and_keeps_slice','result':page.evaluate('()=>uxEditor.slicing.snapshot()')})
            page.locator('#view-preview').click()
            page.wait_for_function('uxEditor.previewStatus.settled && uxEditor.results.length===369 && uxEditor.scene.renderedSnow===3620608',timeout=180000)
            ready=page.evaluate('()=>({status:uxEditor.previewStatus,ratio:uxEditor.scene.pixelLayers.last,labels:uxEditor.scene.annotationView.meshes.size,ticks:uiTicks})')
            assert ready['labels']==32 and ready['ticks']>0 and ready['status']['allocated']<=ready['status']['limits']['detailCells'],ready
            assert page.evaluate('()=>JSON.stringify(uxEditor.model.snapshot())')==fixed
            cases.append({'name':'full_real_statistics_progressively_built_with_ui_ticks','result':ready})
            invariant='''async()=>{const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer))).map(v=>v.toString(16).padStart(2,'0')).join('');return {model:JSON.stringify(uxEditor.model.snapshot()),gray:await Promise.all(uxEditor.results.flatMap(r=>r.pieces.map(async p=>[r.id,p.key,p.name,await hash(p.gray),await hash(p.mask)]))),allocated:uxEditor.previewStatus.allocated};}'''
            data=page.evaluate(invariant)
            buffers=page.evaluate('''()=>{
                const s=uxEditor.scene,r=s.renderer,gl=r.getContext(),hooks=[],seen=new Set();let bytes=0,positive=0;
                try{
                    for(const mesh of s.snowMeshes.values()){
                        const color=mesh.instanceColor;if(!color||color.array.length!==mesh.instanceMatrix.count*3)throw Error('实例颜色容量错误');
                        for(const v of color.array){if(!Number.isFinite(v))throw Error('颜色非有限');if(v>0)positive++;}
                        const previous=mesh.onAfterRender;hooks.push([mesh,previous]);
                        mesh.onAfterRender=function(...args){
                            const location=gl.getAttribLocation(gl.getParameter(gl.CURRENT_PROGRAM),'instanceColor');
                            if(location<0||!gl.getVertexAttrib(location,gl.VERTEX_ATTRIB_ARRAY_ENABLED))throw Error('GPU实例颜色属性未启用');
                            const buffer=gl.getVertexAttrib(location,gl.VERTEX_ATTRIB_ARRAY_BUFFER_BINDING),bound=gl.getParameter(gl.ARRAY_BUFFER_BINDING);
                            if(!buffer)throw Error('GPU颜色缓冲未绑定');
                            try{gl.bindBuffer(gl.ARRAY_BUFFER,buffer);const size=gl.getBufferParameter(gl.ARRAY_BUFFER,gl.BUFFER_SIZE);
                                if(size!==color.array.byteLength||size===0)throw Error('GPU颜色缓冲为空或长度不符');
                                if(!seen.has(mesh)){bytes+=size;seen.add(mesh);}
                            }finally{gl.bindBuffer(gl.ARRAY_BUFFER,bound);}
                            previous.apply(this,args);
                        };
                    }
                    s.render();gl.finish();if(seen.size!==hooks.length)throw Error('并非全部细节网格已绘制');
                }finally{for(const [mesh,hook] of hooks)mesh.onAfterRender=hook;}
                if(gl.getError()!==0)throw Error('GPU颜色检查发生GL错误');return {meshes:seen.size,bytes,positive};
            }''')
            assert buffers['meshes']>0 and buffers['positive']>0,buffers
            cases.append({'name':'all_detail_gpu_color_buffers_have_correct_capacity','result':buffers})
            # 静止实际像素必须贡献亮度；同数据、相机和尺寸对照原同步绘制路径。
            pixel_probe='''()=>{
                const s=uxEditor.scene,r=s.renderer,gl=r.getContext(),w=gl.drawingBufferWidth,h=gl.drawingBufferHeight;
                const read=()=>{s.render();const a=new Uint8Array(w*h*4);gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,a);return a;};
                const visible=s.snow.visible;s.snow.visible=false;const off=read();s.snow.visible=true;const on=read();s.snow.visible=visible;
                let affected=0,delta=0,bright=0;for(let i=0;i<on.length;i+=4){let diff=0;for(let c=0;c<3;c++){diff+=on[i+c]-off[i+c];delta+=on[i+c]-off[i+c];}if(diff!==0)affected++;if(diff>0)bright++;}
                if(gl.getError()!==0)throw Error('静止像素读回GL错误');return {affected,delta,bright};
            }'''
            fine=page.evaluate(pixel_probe)
            legacy=page.evaluate('''probe=>{
                const s=uxEditor.scene,p=s.progressive,old={snow:s.snow,meshes:s.snowMeshes,count:s.renderedSnow,enabled:p.enabled};
                s.scene.remove(old.snow);s.snow=new THREE.Group();s.snowMeshes=new Map();s.scene.add(s.snow);p.enabled=false;
                try{s.drawSnow(uxEditor.results);return (0,eval)('('+probe+')')();}
                finally{s.drawSnow([]);s.scene.remove(s.snow);s.snow=old.snow;s.snowMeshes=old.meshes;p.enabled=old.enabled;s.renderedSnow=old.count;s.scene.add(old.snow);s.render();}
            }''',pixel_probe)
            assert fine['delta']>0 and fine['bright']>0 and legacy['delta']>0,(fine,legacy)
            assert abs(fine['delta']-legacy['delta'])<max(100,legacy['delta']*.1),(fine,legacy)
            assert page.evaluate(invariant)==data
            cases.append({'name':'stationary_pixels_match_original_normal_snow_rendering','result':{'progressive':fine,'legacy':legacy}})
            # 实际鼠标转动，停住后回到相同数据；不要求每次重新建立全部实例。
            page.evaluate('()=>uxEditor.scene.setMode("off")')
            box=page.locator('#view').bounding_box()
            page.mouse.move(box['x']+box['width']*.6,box['y']+box['height']*.45)
            page.mouse.down();page.mouse.move(box['x']+box['width']*.68,box['y']+box['height']*.49,steps=8)
            during=page.evaluate('()=>({motion:uxEditor.previewStatus.interacting,snow:uxEditor.scene.renderedSnow,points:uxEditor.previewStatus.overviewPoints,labelRatio:uxEditor.scene.renderer.getPixelRatio()})')
            assert during['motion'] and during['snow']==0 and 60000<during['points']<=128000 and during['labelRatio']==2,during
            page.mouse.up();page.wait_for_function('!uxEditor.previewStatus.interacting && uxEditor.scene.renderedSnow===3620608',timeout=45000)
            assert page.evaluate(invariant)==data
            restored_pixels=page.evaluate(pixel_probe)
            assert restored_pixels['bright']>0 and restored_pixels['delta']>0,restored_pixels
            cases.append({'name':'actual_camera_drag_uses_real_overview_and_retains_detail','result':{**during,'after_release_pixels':restored_pixels}})
            page.locator('#preview-pause').click()
            hold=page.evaluate('()=>({paused:uxEditor.previewStatus.paused,snow:uxEditor.scene.renderedSnow,allocated:uxEditor.previewStatus.allocated})')
            assert hold['paused'] and hold['snow']==0
            page.wait_for_timeout(150)
            page.locator('#preview-pause').click();page.wait_for_function('uxEditor.scene.renderedSnow===3620608')
            assert page.evaluate(invariant)==data
            cases.append({'name':'actual_pause_keeps_overview_resume_reuses_detail','result':hold})
            # 核对分批建出的每个矩阵／灰度仍使用原主绘制规则。
            sample=page.evaluate('''()=>{const s=uxEditor.scene,m=uxEditor.model;
                for(const r of s.progressive.records.values())for(const mesh of r.chunks){
                    const from=Number(mesh.userData.chunkKey.split('#').pop()),i=Array.from(r.p.mask).findIndex((v,k)=>k>=from&&v);
                    if(i<0||!mesh.count)continue;
                    const pos=new THREE.Vector3(...UXData.position(r.p,i)).applyMatrix4(m.world(r.id)),actual=new THREE.Matrix4();mesh.getMatrixAt(0,actual);
                    const q=new THREE.Quaternion();m.world(r.id).decompose(new THREE.Vector3(),q,new THREE.Vector3());const side=m.resolve(r.id,'snowSize').value;
                    const expected=new THREE.Matrix4().compose(pos,q,new THREE.Vector3(side,side,side));
                    if(actual.elements.some((v,k)=>Math.abs(v-expected.elements[k])>1e-5))throw Error('分批实例位置不同');
                    if(mesh.instanceColor.array.length!==mesh.instanceMatrix.count*3)throw Error('颜色数组容量错误');
                    if(Math.abs(mesh.instanceColor.array[0]-r.p.gray[i])>1e-6)throw Error('分批实例灰度不同');
                    return {source:r.id,from,count:mesh.count};
                }throw Error('没有可核验实例');}''')
            cases.append({'name':'chunk_matrix_and_gray_match_original_drawing_rule','result':sample})
            # 取景基准：焦点固定世界原点，原点恒在画面正中；平移关闭；放大也不漂。
            anchor=page.evaluate('''()=>{const s=uxEditor.scene;s.fit(['work']);s.render();
                const p=new THREE.Vector3(0,0,0).project(s.camera);
                return {target:s.orbit.target.toArray(),pan:s.orbit.enablePan,ndc:[p.x,p.y],distance:s.camera.position.length()};}''')
            assert anchor['target']==[0,0,0] and anchor['pan'] is False,anchor
            assert abs(anchor['ndc'][0])<1e-6 and abs(anchor['ndc'][1])<1e-6,anchor
            view=page.locator('#view').bounding_box()
            page.mouse.move(view['x']+view['width']/2,view['y']+view['height']/2)
            page.mouse.wheel(0,-600);page.wait_for_timeout(200)
            zoomed=page.evaluate('''()=>{const s=uxEditor.scene;s.render();
                const p=new THREE.Vector3(0,0,0).project(s.camera);
                return {ndc:[p.x,p.y],target:s.orbit.target.toArray(),distance:s.camera.position.length()};}''')
            assert zoomed['target']==[0,0,0] and zoomed['distance']<anchor['distance'],(anchor,zoomed)
            assert abs(zoomed['ndc'][0])<1e-6 and abs(zoomed['ndc'][1])<1e-6,zoomed
            cases.append({'name':'world_origin_stays_centered_when_zooming','result':{'fit':anchor,'zoomed':zoomed}})
            page.locator('#view-prepare').click();page.wait_for_function('uxEditor.viewMode==="prepare" && uxEditor.scene.snowMeshes.size===0')
            assert page.evaluate('()=>JSON.stringify(uxEditor.model.snapshot())')==fixed
            page.evaluate('()=>clearInterval(tickTimer)')
            assert not posts,posts
            assert not errors,errors
        except Exception as e:
            failure=str(e)
            try:
                print(page.locator('#status').inner_text(),flush=True)
            except Exception:
                pass
        finally:
            browser.close()
    after={str(p.relative_to(ROOT)):sha(p) for p in files}
    if before!=after:
        failure='测试期间实现被修改'
    out=BUNDLE/'verification'/('progressive-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True,exist_ok=False)
    with (out/'checks.json').open('x',encoding='utf-8') as f:
        json.dump({'passed':failure is None,'failure':failure,'cases':cases,'errors':errors,'posts':posts,'code_unchanged':before==after,'sha256':before},f,ensure_ascii=False,indent=2)
    print(json.dumps({'passed':failure is None,'cases':len(cases),'failure':failure,'report':str(out/'checks.json')},ensure_ascii=False),flush=True)
    if failure:
        raise SystemExit(1)


if __name__=='__main__':
    main()

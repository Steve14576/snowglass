# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.50,<2", "numpy>=2,<3", "gguf==0.19.0"]
# ///
"""一键切片实际链路核验。--real 仅计算 L00.attn_norm 一个4096元素F32张量。"""
import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

import numpy as np
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=ROOT / 'prototype/editor_ux/20261122-055413-124110'
KEY='text:blk.0.attn_norm.weight'
sys.path.insert(0,str(ROOT / 'scripts'))



def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8129/')
    parser.add_argument('--real',action='store_true')
    parser.add_argument('--report',type=Path)
    parser.add_argument('--restore-tasks',nargs='+',help='只核验既有任务的缓存与工程恢复，不计算权重')
    args=parser.parse_args()
    report_dir=args.report or (ROOT / 'out/slices/verification' / ('flow-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
    report_dir.mkdir(parents=True,exist_ok=False)
    frozen=[ROOT / 'scripts'/n for n in ('survey_data.py','survey_math.py','run_type_survey.py')]
    frozen += [BUNDLE / 'data/manifest.json',BUNDLE / 'data/tensors/text__blk.0.attn_norm.weight.json']
    before={str(p.relative_to(ROOT)):sha(p) for p in frozen}
    cases=[];errors=[];failure=None;start=time.monotonic()
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1600,'height':1050})
        page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            page.goto(args.url,wait_until='domcontentloaded',timeout=15000)
            page.wait_for_function('window.uxEditor?.slicing.online && uxEditor.results.length',timeout=45000)
            page.evaluate('() => {uxEditor.select(["L00.attn_norm"]);document.getElementById("slice-scope").value="selected";uxEditor.slicing.render();}')
            page.wait_for_function('uxEditor.results[0]?.id==="L00.attn_norm"')
            assert page.evaluate('() => uxEditor.scene.renderedSnow')==0
            assert page.evaluate('()=>uxEditor.model.resolve("global","sourceConvention").value')=='gguf'
            assert page.evaluate('()=>uxEditor.model.resolve("global","extraDiagnostics").value') is False
            cases.append({'name':'new_project_defaults_to_raw_and_no_diagnostics','passed':True})
            plan=page.evaluate('async()=>uxEditor.slicing.api("plan",{blocks:uxEditor.slicing.blocks().map(id=>({id,grid:uxEditor.slicing.grid(id)}))})')
            assert (plan['block_count'],plan['tensor_count'])==(369,761),plan
            cases.append({'name':'whole_model_plan_without_computation','blocks':369,'tensors':761})
            page.locator('#slice-1').click()
            page.wait_for_function('document.getElementById("confirm-dialog").open')
            assert '1 个块，1 个张量' in page.locator('#confirm-body').inner_text()
            page.locator('#confirm-dialog button[value="cancel"]').click()
            assert page.evaluate('()=>uxEditor.slicing.active') is None
            cases.append({'name':'confirmation_cancel_starts_no_job','passed':True})
            page.evaluate('()=>{document.getElementById("exposure").value="1.5";document.getElementById("exposure").dispatchEvent(new Event("input"));}')
            assert page.evaluate('()=>uxEditor.scene.renderedSnow')==0
            cases.append({'name':'prepare_exposure_never_draws_snow','passed':True})
            if args.restore_tasks:
                page.evaluate('async(tasks)=>{await uxEditor.slicing.restore({slice:{tasks}});uxEditor.model.set("L00.attn_norm","gridX",8);await uxEditor.refreshData();}',args.restore_tasks)
                assert page.evaluate('()=>uxEditor.slicing.fresh("L00.attn_norm")') is True,'原值8轴缓存未恢复'
                channels=page.evaluate('''async()=>{const a=uxEditor,m=new UXModel.Model(a.model.topo,a.model.provenance);m.nodes.get('global').values.sourceConvention='hf';let n=0;
                    for(const c of ['full','feature','rowcol','residual']){m.nodes.get('global').values.channel=c;for(const b of a.data.manifest.blocks){const r=await a.data.evaluate(b.id,m);if(!r.count||r.pieces.some(p=>p.gray.some(v=>!Number.isFinite(v))))throw Error('旧通道回归失败');n++;}}return n;}''')
                assert channels==260,f'旧通道组合数错误：{channels}'
                cases.append({'name':'old_channels_after_variant_install','channels':channels,'passed':True})
                saved=page.evaluate('()=>uxEditor.getProject()')
                restored=browser.new_page(viewport={'width':1600,'height':1050})
                restored.add_init_script('(doc=>localStorage.setItem("snowglass.editor-ux.20261122-055413-124110.v2",JSON.stringify(doc)))('+json.dumps(saved)+')')
                restored.goto(args.url,wait_until='domcontentloaded')
                restored.wait_for_function('window.uxEditor?.slicing.tasks.length===4 && uxEditor.slicing.fresh("L00.attn_norm") && typeof uxEditor.scene.renderedSnow==="number"',timeout=45000)
                state=restored.evaluate('()=>({snow:uxEditor.scene.renderedSnow,active:uxEditor.slicing.active,mode:uxEditor.viewMode,tasks:uxEditor.slicing.tasks.length})')
                assert state['snow']==0 and state['active'] is None,state
                restored.close()
                cases.append({'name':'focused_old_channels_and_restored_variants_without_compute','channels':channels,'passed':True})
            if args.real:
                def cut():
                    previous=page.evaluate('()=>uxEditor.slicing.last?.id||null')
                    button=page.locator('#slice-1').bounding_box()
                    page.mouse.click(button['x']+button['width']/2,button['y']+button['height']/2)
                    page.wait_for_function('document.getElementById("confirm-dialog").open')
                    button=page.locator('#confirm-ok').bounding_box()
                    page.mouse.click(button['x']+button['width']/2,button['y']+button['height']/2)
                    page.wait_for_function('(id)=>uxEditor.slicing.last?.id && uxEditor.slicing.last.id!==id',arg=previous,timeout=10000)
                    page.wait_for_function('uxEditor.slicing.last && !["running","queued"].includes(uxEditor.slicing.last.state)',timeout=45000)
                    status=page.evaluate('()=>uxEditor.slicing.last')
                    assert status['state']=='complete',status
                    page.wait_for_function('!uxEditor.slicing.active && uxEditor.viewMode==="preview" && uxEditor.scene.renderedSnow>0 && document.getElementById("progress").hidden',timeout=90000)
                    return status
                first=cut()
                with urlopen(args.url.rstrip('/')+first['manifest_url']) as response:
                    manifest=json.load(response)
                entry=manifest['tensors'][0]
                with urlopen(args.url.rstrip('/')+entry['url']) as response:
                    actual=json.load(response)
                old=json.loads(frozen[-1].read_text(encoding='utf-8'))
                assert actual['packed_sha256']==old['packed_sha256']
                assert actual['shape']==[4096]
                from gguf import GGUFReader
                import survey_data as sd
                reader=GGUFReader(str(sd.FILES['text']),'r');ref={'shape':[4096],'qtype':'F32','restore':None}
                raw=sd.TensorSource(next(t for t in reader.tensors if t.name=='blk.0.attn_norm.weight'),ref).decode()
                expected=sd.pack_parts(raw,ref)
                for a,b in zip(actual['parts'],expected):
                    for channel in ('full','counts'):np.testing.assert_array_equal(a[channel],b[channel])
                    for channel in ('feature','residual','rowcol','signed'):assert a[channel] is None
                assert actual['sourceConvention']=='gguf' and actual['restore'] is None
                assert first['svd_enabled'] is False and first['diagnostics'] is False
                cases.append({'name':'real_raw_norm_full_only_without_optional_work','task':first['id'],'elements':4096,
                              'grid':actual['parts'][0]['grid'],'seconds':first['elapsed_seconds']})
                assert page.locator('#slice-1').is_disabled()
                tabs=page.evaluate('()=>["view-prepare","view-preview"].map(id=>{const el=document.getElementById(id),r=el.getBoundingClientRect(),c=getComputedStyle(el);return {id,rect:[r.x,r.y,r.width,r.height],display:c.display,visibility:c.visibility,disabled:el.disabled};})')
                cases.append({'name':'tab_geometry_after_slice','tabs':tabs})
                print(json.dumps({'tabs':tabs},ensure_ascii=False),flush=True)
                # 全量软件WebGL下 RAF 可能迟迟不给 actionability 采样；用真实指针点击并核验状态，不卡在截图／稳定性等待。
                tab=page.locator('#view-prepare').bounding_box()
                page.mouse.click(tab['x']+tab['width']/2,tab['y']+tab['height']/2)
                page.wait_for_function('uxEditor.viewMode==="prepare" && uxEditor.scene.renderedSnow===0')
                second=cut()
                assert second['reused']==1,second
                cases.append({'name':'second_click_reuses_completed_tensor','task':second['id'],'reused':1})
                page.evaluate('()=>uxEditor.model.set("L00.attn_norm","gridX",8)')
                assert not page.evaluate('()=>uxEditor.slicing.fresh("L00.attn_norm")')
                assert not page.locator('#slice-1').is_disabled()
                third=cut()
                assert third['signature']!=first['signature'],third  # 已有同一新网格的完成结果可以合法复用。
                current=page.evaluate('()=>({grid:uxEditor.results.find(r=>r.id==="L00.attn_norm").pieces[0].grid,ready:uxEditor.slicing.fresh("L00.attn_norm"),meshes:uxEditor.scene.snowMeshes.size})')
                assert current['grid'][0]==8 and current['ready'],current
                cases.append({'name':'changed_grid_uses_matching_result_then_disables_button','task':third['id'],'reused':third['reused'],**current})
                assert page.locator('#slice-1').is_disabled()
                page.evaluate('()=>{uxEditor.model.set("L00.attn_norm","gap",-.05);uxEditor.model.set("L00.attn_norm","white",.8);uxEditor.model.set("L00.attn_norm","snowSize",.018);}')
                page.wait_for_function('uxEditor.results.find(r=>r.id==="L00.attn_norm")?.settings.white===.8')
                assert page.locator('#slice-1').is_disabled()
                assert page.evaluate('()=>uxEditor.slicing.active') is None
                page.evaluate('()=>uxEditor.select([])')
                page.wait_for_function('uxEditor.results.length===65')
                assert page.evaluate('()=>uxEditor.scene.renderedSnow')>0
                cases.append({'name':'geometry_gray_and_selection_do_not_reslice_or_hide_all_snow','passed':True})
                page.evaluate('()=>{uxEditor.select(["L00.attn_norm"]);document.getElementById("view-prepare").click();uxEditor.model.set("L00.attn_norm","gridX",16);uxEditor.model.set("L00.attn_norm","sourceConvention","hf");uxEditor.model.set("L00.attn_norm","extraDiagnostics",true);uxEditor.model.set("L00.attn_norm","channel","feature");}')
                fourth=cut()
                with urlopen(args.url.rstrip('/')+fourth['manifest_url']) as response:fm=json.load(response)
                with urlopen(args.url.rstrip('/')+fm['tensors'][0]['url']) as response:aligned=json.load(response)
                for a,b in zip(aligned['parts'],old['parts']):
                    for channel in ('full','signed','feature','counts'):np.testing.assert_array_equal(a[channel],b[channel])
                assert aligned['sourceConvention']=='hf' and aligned['extraDiagnostics'] is True
                cases.append({'name':'explicit_alignment_and_diagnostics_preserve_legacy_values','task':fourth['id']})
                page.evaluate('()=>{uxEditor.model.set("L00.attn_norm","sourceConvention","gguf");uxEditor.model.set("L00.attn_norm","extraDiagnostics",false);uxEditor.model.set("L00.attn_norm","gridX",8);uxEditor.model.set("L00.attn_norm","channel","full");}')
                page.wait_for_function('uxEditor.results.find(r=>r.id==="L00.attn_norm")?.pieces[0].source_convention==="gguf"')
                assert page.evaluate('()=>uxEditor.slicing.fresh("L00.attn_norm")') is True
                assert page.evaluate('()=>uxEditor.slicing.active') is None
                cases.append({'name':'switch_back_reuses_raw_variant_without_new_job','passed':True})
                saved=page.evaluate('()=>uxEditor.getProject()')
                restored=browser.new_page(viewport={'width':1600,'height':1050})
                restored.on('pageerror',lambda e:errors.append(str(e)))
                restored.add_init_script('(doc=>localStorage.setItem("snowglass.editor-ux.20261122-055413-124110.v2",JSON.stringify(doc)))('+json.dumps(saved)+')')
                restored.goto(args.url,wait_until='domcontentloaded',timeout=15000)
                restored.wait_for_function('window.uxEditor?.slicing.tasks.length===4 && uxEditor.slicing.fresh("L00.attn_norm") && typeof uxEditor.scene.renderedSnow==="number"',timeout=45000)
                assert restored.evaluate('()=>uxEditor.scene.renderedSnow')==0
                restored.close()
                cases.append({'name':'project_restores_statistics_references_without_computation','passed':True})
            assert not errors,errors
        except Exception as e:
            failure=str(e) or type(e).__name__
            try:cases.append({'name':'diagnostic','status':page.locator('#status').inner_text(),'task':page.evaluate('()=>window.uxEditor?.slicing.last'),'tabs':page.evaluate('()=>["view-prepare","view-preview"].map(id=>{const e=document.getElementById(id),r=e.getBoundingClientRect();return {id,width:r.width,height:r.height,disabled:e.disabled};})')})
            except Exception:pass
        finally:
            browser.close()
    after={str(p.relative_to(ROOT)):sha(p) for p in frozen}
    report={'passed':failure is None,'failure':failure,'real_scope':'L00.attn_norm' if args.real else None,
            'cases':cases,'page_errors':errors,'frozen_inputs_unchanged':before==after,'hashes':after,'seconds':round(time.monotonic()-start,2)}
    (report_dir / 'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'failure':failure,'cases':len(cases),'report':str(report_dir / 'checks.json')},ensure_ascii=False),flush=True)
    if failure or before!=after:raise SystemExit(1)


if __name__=='__main__':
    main()

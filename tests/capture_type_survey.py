# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.50,<2"]
# ///
"""所有功能组可载入性、数值映射与实际三维截图。复现说明 docs/type_survey.md。"""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True)
    parser.add_argument('--port',type=int,default=8124)
    args=parser.parse_args()
    source=ROOT/'prototype/data/type_surveys'/args.run
    folder=source/('verification-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(exist_ok=False)
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob('*.json')}
    errors=[];result={'run':args.run,'groups':[],'captures':[],'errors':errors}
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True,args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1600,'height':1040},device_scale_factor=1)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(f'http://localhost:{args.port}/prototype/type_survey.html?run={args.run}',wait_until='networkidle',timeout=60000)
        page.wait_for_function('window.typeSurveyTest?.views?.length===3',timeout=15000)
        # 全部组合都载入，不只选择好看的几块；避免把部分失败冒充全覆盖。
        groups=page.evaluate('() => typeSurveyTest.manifest.blocks.concat(typeSurveyTest.manifest.geometry_only).map(b=>({id:b.id,tensors:(b.tensors||[]).length}))')
        for group in groups:
            record=page.evaluate('''async id=>{
                const a=typeSurveyTest;await a.select(id);a.apply({channel:'feature',gain:1,gamma:1,cutoff:.25,slab:false,part:'all'});
                const s=a.state;
                for(const p of s.pieces){
                    const n=p.grid.reduce((x,y)=>x*y,1);
                    if(p.arrays.some(v=>v.length!==n||v.some(x=>!Number.isFinite(x))))throw Error('非有限或格数错误 '+id);
                    for(let i=0;i<n;i++)if(p.arrays[2][i] !== (p.mask[i]?p.arrays[1][i]:0))throw Error('筛选改变入选灰度 '+id);
                }
                const count=s.statistics[2].positive;a.apply({gain:3,gamma:.7});
                if(a.state.statistics[2].positive!==count)throw Error('显影改变位置 '+id);
                return {id,pieces:s.pieces.length,cells:s.statistics[0].cells,kept:count,caveats:s.caveats,source:document.getElementById('block-source').textContent};
            }''',group['id'])
            if group['tensors']:
                assert record['pieces']>=group['tensors'],record
            else:
                assert record['cells']==0,record
            result['groups'].append(record)
        # 控件边界、来源和单区显示。
        await_result=page.evaluate('''async()=>{
            const a=typeSurveyTest;await a.select('L00.mix1');
            const size=a.state.pieces.length;if(size!==7)throw Error('GDN 控制块未包含七张量');
            const first=a.state.pieces[0].id;a.apply({part:first});
            if(a.state.pieces.length!==1)throw Error('单区选择失效');
            a.apply({cutoff:1,channel:'feature'});
            if(a.state.statistics[2].positive!==0)throw Error('高门槛空边界失效');
            return {control_parts:size,one_part:true,empty:true};
        }''')
        result['boundaries']=await_result
        # 每一种主要组型至少截图一幅，连不理想的小参数也展示。
        captures=['L03.mix0','L03.mix1','L03.mix2','L00.mix0','L00.mix1','L00.mix2',
                  'L16.gate','L16.up','L16.down','L15.attn_norm','embed','lm_head',
                  'V00.attn','V13.mlp','V26.norm1','V.patch','V.merger','mtp']
        for group in captures:
            page.evaluate('async id=>await typeSurveyTest.select(id)',group)
            page.evaluate("() => typeSurveyTest.apply({part:'all',channel:'feature',gain:2,gamma:1,cutoff:.25,slab:false,axis:1,slice:.5,mode:'opaque'})")
            page.wait_for_timeout(150)
            # 几何要真正贡献像素，不能只有一个 canvas 或空线框。
            if group!='mtp':
                pixel=page.evaluate('''()=>{
                    const a=typeSurveyTest,v=a.views[0],gl=v.renderer.getContext(),n=gl.drawingBufferWidth*gl.drawingBufferHeight*4;
                    const on=new Uint8Array(n),off=new Uint8Array(n);v.renderer.render(v.scene,v.camera);
                    gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,on);
                    v.meshes.forEach(o=>o.visible=false);v.renderer.render(v.scene,v.camera);
                    gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,off);
                    v.meshes.forEach(o=>o.visible=true);v.renderer.render(v.scene,v.camera);
                    return {pixels:on.filter((x,i)=>i%4!==3&&x!==off[i]).length,instances:v.meshes.reduce((n,o)=>n+o.count,0)};
                }''')
                if pixel['instances']:
                    assert pixel['pixels']>0,(group,pixel)
            else:pixel={'instances':0}
            path=folder/(group.replace('.','_')+'.png')
            page.locator('.survey-content').screenshot(path=str(path))
            result['captures'].append({'group':group,'path':path.name,'pixels':pixel})
        # 真正按钮与输入事件，保存只拦截下载，不产生无用测试文件。
        page.locator('[data-block="L03.mix0"]').click()
        page.wait_for_function("typeSurveyTest.state.block==='L03.mix0' && typeSurveyTest.state.pieces.length===2")
        page.locator('#cutoff').focus();page.locator('#cutoff').press('End')
        page.wait_for_function("typeSurveyTest.state.settings.cutoff==='1'")
        # 小 norm 的归一幅度可能超过 1；滑块到 1 不保证全空，不能把正确数据判成错误。
        count=page.evaluate('() => ({actual:typeSurveyTest.state.statistics[2].positive,expected:typeSurveyTest.state.pieces.reduce((n,p)=>n+p.raw.filter(v=>v>1).length,0)})')
        assert count['actual']==count['expected'],count
        result['keyboard_threshold']=count
        result['save']=page.evaluate('''async()=>{
            let blob;const create=URL.createObjectURL,click=HTMLAnchorElement.prototype.click;
            try{URL.createObjectURL=b=>{blob=b;return 'blob:test';};HTMLAnchorElement.prototype.click=function(){};
                document.getElementById('save').click();const obj=JSON.parse(await blob.text());
                if(obj.schema!=='snowglass.type-survey-view.v1'||obj.block!=='L03.mix0')throw Error('保存错误');
                return {schema:obj.schema,block:obj.block,pieces:obj.pieces.length};
            }finally{URL.createObjectURL=create;HTMLAnchorElement.prototype.click=click;}
        }''')
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(200)
        result['mobile']=page.evaluate('() => ({width:innerWidth,scroll:document.documentElement.scrollWidth})')
        assert result['mobile']['scroll']<=result['mobile']['width'],result['mobile']
        assert not errors,errors
        browser.close()
    after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob('*.json')}
    assert before==after,'源结果改变'
    result['source_unchanged']=True
    with (folder/'verification.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'folder':str(folder),'groups':len(result['groups']),'screenshots':len(result['captures']),
                      'mobile':result['mobile'],'errors':errors},ensure_ascii=False),flush=True)


if __name__=='__main__':main()

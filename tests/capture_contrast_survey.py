# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.50,<2"]
# ///
"""核验独立全类型灰度展开、复制哈希、所有通道与图像。说明 docs/contrast_survey.md。"""
import argparse
import hashlib
import html
import json
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--folder',type=Path,required=True);parser.add_argument('--port',type=int,default=8127)
    args=parser.parse_args();bundle=args.folder.resolve()
    manifest=json.loads((bundle/'data/manifest.json').read_text(encoding='utf-8'))
    before={p:sha(ROOT/p) for p in manifest['source_hashes']}
    assert before==manifest['source_hashes'],'原件已发生变化'
    for name,digest in before.items():
        dst=bundle/('source_data' if '/data/type_surveys/' in name.replace('\\','/') else 'original_files')/Path(name).name
        assert sha(dst)==digest,'逐字副本不一致'
    checked=0
    for item in manifest['tensors']:
        path=bundle/'data'/item['data_file'];assert sha(path)==item['data_sha256']
        data=json.loads(path.read_text(encoding='utf-8'));original=json.loads((bundle/'source_data'/item['data_file']).read_text(encoding='utf-8'))
        assert data['reference_white']==original['reference_white'] and data['spectral']==original['spectral']
        for a,b in zip(data['parts'],original['parts']):
            for key in b:assert a[key]==b[key],f'原统计被改写：{item["key"]} {key}'
        for channel,w in data['windows'].items():
            if w is None:continue
            values=[v for p in data['parts'] for v in (p['expanded'].get(channel) or [])]
            if not w['constant']:assert min(values)==0 and max(values)==1
            else:assert len(set(values))==1
            checked+=1
    folder=bundle/('verification-'+datetime.now().strftime('%Y%m%d-%H%M%S'));folder.mkdir(exist_ok=False)
    errors=[];records=[];captures=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True,args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1720,'height':1100},device_scale_factor=1)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(f'http://localhost:{args.port}/',wait_until='networkidle',timeout=60000)
        page.wait_for_function('window.contrastTest?.views?.length===3',timeout=15000)
        groups=page.evaluate('() => contrastTest.manifest.blocks.concat(contrastTest.manifest.geometry_only).map(b=>({id:b.id,label:b.label,n:(b.tensors||[]).length}))')
        for group in groups:
            page.evaluate('async id=>await contrastTest.select(id)',group['id'])
            for channel in ('full','feature','rowcol','residual'):
                record=page.evaluate('''s=>{
                    const a=contrastTest;a.apply({channel:s.channel,black:0,white:1,gamma:1,window:'range',oldgain:2,part:'all',mode:'opaque',slab:false});
                    const t=a.state;
                    for(const p of t.pieces){
                        const n=p.grid.reduce((x,y)=>x*y,1);
                        if(p.arrays.some(arr=>arr.length!==n||arr.some(v=>!Number.isFinite(v))))throw Error('灰度数组错误');
                        for(let i=0;i<n;i++){
                            const expected=a.math.windowGray(p.raw[i],p.window.low,p.window.high,p.tensor.reference_white);
                            if(Math.abs(p.arrays[1][i]-expected)>1e-12)throw Error('Python/JS 灰度展开不一致');
                            if(p.arrays[2][i]!==p.arrays[1][i])throw Error('默认左右窗口不一致');
                        }
                    }
                    for(const [i,v] of a.views.entries())if(t.pieces.length){
                        const count=v.meshes.reduce((n,m)=>n+m.count,0);
                        if(count!==t.statistics[i].cells)throw Error('仍在按黑色删除格子');
                    }
                    return {group:t.block,channel:s.channel,pieces:t.pieces.length,statistics:t.statistics,windows:t.pieces.map(p=>({id:p.id,range:[p.window.low,p.window.high],amplification:p.amplification}))};
                }''',{'channel':channel})
                assert record['pieces']>=group['n'] if group['n'] else record['pieces']==0
                records.append(record)
                if channel in ('full','feature') and group['n']:
                    page.wait_for_timeout(70)
                    name=group['id'].replace('.','_')+'_'+channel+'.png'
                    page.locator('.comparison').screenshot(path=str(folder/name))
                    captures.append({'group':group['id'],'label':group['label'],'channel':channel,'file':name})
            if len(records)%20==0:print(json.dumps({'tested_groups':len(records)//4,'images':len(captures)},ensure_ascii=False),flush=True)
        # 恒定、零和无效窗口边界，不能凭归一化制造新纹理。
        result=page.evaluate('''async()=>{
            const a=contrastTest;
            if(a.math.windowGray(0,0,0,0)!==0||a.math.windowGray(3,3,3,6)!==.5)throw Error('恒定策略错误');
            await a.select('L16.down');a.apply({channel:'full',black:0,white:1,gamma:1,window:'range',oldgain:2,part:'all'});
            const original=JSON.stringify(a.state.pieces[0].arrays[1]);a.apply({oldgain:1});
            if(JSON.stringify(a.state.pieces[0].arrays[1])!==original)throw Error('旧曝光改变展开数据');
            if(a.apply({black:.9,white:.1})!==false)throw Error('未拒绝无效窗口');
            a.apply({black:0,white:1,window:'robust'});
            document.getElementById('reset').click();
            if(a.state.settings.window!=='range'||a.state.settings.channel!=='full')throw Error('恢复按钮错误');
            const info=[];
            for(const v of a.views){
                const gl=v.renderer.getContext(),n=gl.drawingBufferWidth*gl.drawingBufferHeight*4,on=new Uint8Array(n),off=new Uint8Array(n);
                v.renderer.render(v.scene,v.camera);gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,on);
                v.meshes.forEach(m=>m.visible=false);v.renderer.render(v.scene,v.camera);
                gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,off);
                v.meshes.forEach(m=>m.visible=true);v.renderer.render(v.scene,v.camera);
                const count=on.filter((x,i)=>i%4!==3&&x!==off[i]).length;if(!count)throw Error('实际小块未显示');info.push(count);
            }
            return {constant:true,zero:true,invalid_window:true,old_exposure_independent:true,pixel_contribution:info};
        }''')
        page.locator('#gamma').focus();page.locator('#gamma').press('End')
        page.wait_for_function("contrastTest.state.settings.gamma==='3'")
        saved=page.evaluate('''async()=>{
            let blob;const create=URL.createObjectURL,click=HTMLAnchorElement.prototype.click;
            try{URL.createObjectURL=b=>{blob=b;return 'blob:check';};HTMLAnchorElement.prototype.click=function(){};
                document.getElementById('save').click();const r=JSON.parse(await blob.text());
                if(r.pieces[0].gray.length!==contrastTest.state.pieces[0].arrays[2].length)throw Error('保存格子丢失');
                return {schema:r.schema,block:r.block};
            }finally{URL.createObjectURL=create;HTMLAnchorElement.prototype.click=click;}
        }''')
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(200)
        mobile=page.evaluate('() => ({width:innerWidth,scroll:document.documentElement.scrollWidth})');assert mobile['scroll']<=mobile['width'],mobile
        assert not errors,errors;browser.close()
    after={p:sha(ROOT/p) for p in manifest['source_hashes']};assert before==after
    report={'channels_verified_python':checked,'cases_browser':len(records),'groups':len(groups),'screenshots':len(captures),
            'errors':errors,'mobile':mobile,'boundaries':result,'save':saved,'source_unchanged':True,'captures':captures,'records':records,
            'page_sha256':{str(path.relative_to(bundle)):sha(path) for path in [bundle/'index.html',*list((bundle/'assets').glob('*'))]}}
    with (folder/'verification.json').open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,allow_nan=False,indent=2)
    cards=''.join(f'<article><h2>{html.escape(v["group"]+" · "+v["label"]+" / "+v["channel"])}</h2><a href="{html.escape(v["file"])}"><img loading="lazy" src="{html.escape(v["file"])}" alt="实际浏览器截图"></a></article>' for v in captures)
    with (folder/'gallery.html').open('x',encoding='utf-8') as f:
        f.write('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>全部灰度展开截图</title><link rel="stylesheet" href="../assets/base.css"><style>article{margin:24px auto;max-width:1600px}img{width:100%;height:auto}</style><main><h1>65组 × 完整幅度与谱特征对照</h1><p>三列：旧标尺／全范围展开／可调窗口；全部格子保留。</p>'+cards+'</main></html>')
    print(json.dumps({'folder':str(folder),'channels':checked,'cases':len(records),'screenshots':len(captures),'errors':errors,'source_unchanged':True},ensure_ascii=False),flush=True)


if __name__=='__main__':main()

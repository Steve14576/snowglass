# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.50,<2"]
# ///
"""对照新旧模式、记录区域筛选截图；方法见 docs/weight_sample_comparison.md。"""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent
SOURCE=ROOT/'prototype/data/gray_samples/run-20261121-211150-652530'
ANALYSIS=ROOT/'prototype/data/gray_samples/support-20261121-214004-601105'
BASE='http://localhost:8125'


def main():
    folder=ANALYSIS/('verification-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(exist_ok=False)
    files=[SOURCE/'manifest.json']+[SOURCE/f'{k}.{e}' for k in ('attention','mlp') for e in ('json','npz')]
    before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    errors=[]
    result={'captures':[],'errors':errors,'source_hashes':before}
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True,
                                  args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1520,'height':1040},device_scale_factor=1)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(BASE+'/prototype/gray_samples.html',wait_until='networkidle',timeout=45000)
        page.wait_for_function('window.graySampleTest?.views?.length===3')
        result['original_checks']=page.evaluate("async()=>await(0,eval)(await(await fetch('../tests/gray_samples_checks.js')).text())")
        page.locator('#study-switch').click()
        page.wait_for_function('window.graySampleTest?.supportStudy && window.graySampleTest?.views?.length===3')
        result['support_checks']=page.evaluate("async()=>await(0,eval)(await(await fetch('../tests/gray_support_checks.js')).text())")
        for key,tau in [('attention',.24),('attention',.25),('attention',.26),('mlp',.25),('mlp',.1)]:
            settings={'tensor':key,'cutoff':tau,'resolution':'fine','gain':2,'gamma':1,'axis':1,'slice':8,'slab':False,'render-mode':'opaque'}
            page.evaluate('s=>window.graySampleTest.set(s)',settings)
            page.wait_for_timeout(250)
            name=f'{key}_{tau:.2f}'
            record=page.evaluate('() => ({settings:graySampleTest.state.settings,statistics:graySampleTest.state.statistics,info:graySampleTest.state.support.info,neighbor:graySampleTest.state.support.neighbor})')
            record['name']=name
            page.locator('.comparison').screenshot(path=str(folder/(name+'.png')))
            if key=='attention' and tau==.25:
                page.screenshot(path=str(folder/'attention_default_full.png'),full_page=True)
            result['captures'].append(record)
        # 真正的控件事件，而不只调用检查入口。
        page.locator('#cutoff').focus()
        page.locator('#cutoff').press('End')
        page.wait_for_function("window.graySampleTest.state.settings.cutoff==='0.4'")
        result['input_event']=page.evaluate('() => graySampleTest.state.support.info.retained')
        assert result['input_event']==0
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_timeout(200)
        result['mobile']=page.evaluate('() => ({width:innerWidth,scroll:document.documentElement.scrollWidth})')
        assert result['mobile']['scroll']<=result['mobile']['width']
        assert not errors,errors
        browser.close()
    after={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    assert before==after,'原始缓存发生变化'
    result['source_unchanged']=True
    result['page_source_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [ROOT/'prototype'/name for name in ('gray_samples.html','gray_samples.js','gray_samples_scene.js','gray_support.js','gray_samples.css')]}
    with (folder/'verification.json').open('x',encoding='utf-8') as f:
        json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'folder':str(folder),'original':result['original_checks'],'support':result['support_checks'],
                      'mobile':result['mobile'],'source_unchanged':True,'errors':errors},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()

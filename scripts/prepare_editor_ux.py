"""建立核心UX的独立副本。只复制已完成统计与原型，不读权重、不重算SVD。

设计与实施状态见 docs/editor_spec.md。每次运行新建唯一目录，不覆盖。
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'prototype/contrast_survey/20261122-033209-256746/data'
# 旧编辑器已于 2026-11-22 归档；优先新位置，保留旧路径作回退。
OLD=next(p for p in [ROOT/'prototype/_archive/editor_legacy/snowglass_editor.html',ROOT/'prototype/snowglass_editor.html'] if p.exists())
TOPO=ROOT/'prototype/data/qwen35_9b.topo.json'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def exclusive(path,content):
    with path.open('xb') as f:f.write(content)


def main():
    manifest=json.loads((CACHE/'manifest.json').read_text(encoding='utf-8'))
    topo=json.loads(TOPO.read_text(encoding='utf-8'))
    assert topo['schema_version']==2 and len(manifest['blocks'])==65 and len(manifest['tensors'])==124
    ids={b['id'] for b in topo['blocks']}
    assert all(b['id'] in ids for b in manifest['blocks'])
    keys={t['key'] for t in manifest['tensors']}
    assert all(t['file']+':'+t['gguf'] in keys for b in manifest['blocks'] for t in b['tensors'])
    folder=ROOT/'prototype/editor_ux'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    for sub in ('assets','data/tensors','originals'): (folder/sub).mkdir(parents=True,exist_ok=False)
    files=[OLD,TOPO,CACHE/'manifest.json',*[CACHE/t['data_file'] for t in manifest['tensors']]]
    before={str(p.relative_to(ROOT)):sha(p) for p in files}
    exclusive(folder/'originals/snowglass_editor.html',OLD.read_bytes())
    exclusive(folder/'data/topology.json',TOPO.read_bytes())
    exclusive(folder/'data/manifest.json',(CACHE/'manifest.json').read_bytes())
    for item in manifest['tensors']:
        source=CACHE/item['data_file'];assert sha(source)==item['data_sha256']
        data=json.loads(source.read_text(encoding='utf-8'))
        assert data['key']==item['key'] and data['parts'] and data['reference_white']>=0
        for part in data['parts']:
            count=1
            for dim in part['grid']:count*=dim
            assert len(part['full'])==count and len(part['counts'])==count
        exclusive(folder/'data/tensors'/source.name,source.read_bytes())
    # 原配方逐字提取到独立适配器，布局仍仅在前端，不在Python复算。
    old=OLD.read_text(encoding='utf-8')
    recipe=old[old.index('const RECIPE ='):old.index('\n\n/*',old.index('const RECIPE ='))]
    functions=old[old.index('function groupWidths('):old.index('function prepare()')]
    adapter="/* 从旧编辑器逐字提取的4.2配方，仅在独立副本调用。 */\nwindow.SnowLayout=(topo,config={})=>{\n"
    adapter+="const P={widthMode:'equal',squash:.55,depth:6.2,layerGap:0,vision:true,scale:1,...config};\n"
    adapter+="const assembly=new THREE.Matrix4(),manuals={},blockById=Object.fromEntries(topo.blocks.map(b=>[b.id,b]));\n"
    adapter+=recipe+'\n'+functions+'\nreturn layout();\n};\n'
    exclusive(folder/'assets/layout.js',adapter.encode('utf-8'))
    exclusive(folder/'assets/base.css',(ROOT/'prototype/gray_samples.css').read_bytes())
    after={str(p.relative_to(ROOT)):sha(p) for p in files};assert before==after
    record={'bundle':folder.name,'source_run':manifest['source_run'],'source_unchanged':True,
            'source_hashes':before,'cached_groups':65,'cached_tensors':124,
            'topology_sha256':sha(TOPO),'manifest_sha256':sha(CACHE/'manifest.json'),
            'source_script_sha256':sha(Path(__file__))}
    exclusive(folder/'provenance.json',json.dumps(record,ensure_ascii=False,indent=2).encode('utf-8'))
    print(json.dumps({'folder':str(folder),'cached_groups':65,'cached_tensors':124,'source_unchanged':True},ensure_ascii=False),flush=True)


if __name__=='__main__':main()

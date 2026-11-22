# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2,<3", "gguf==0.19.0", "threadpoolctl>=3,<4", "psutil>=6,<8"]
# ///
"""一级切片任务：复用冻结的探路算法，参数化网格，逐张量校验并复用。

命令行与本地服务共用入口。新结果在 out/slices，不覆盖旧缓存。
"""
import argparse
import hashlib
import gc
import json
import multiprocessing as mp
import os
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil
from gguf import GGUFReader
from threadpoolctl import threadpool_limits

import survey_data as d
import survey_math as m
import preprocess as processing
from run_type_survey import validate
from prepare_contrast_survey import distribution

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'out/slices'
DEFAULT_GRID = [16, 16, 32]
CHANNELS = ('full', 'feature', 'residual', 'rowcol')
ORIGINAL_POOL = d.pooled
ORIGINAL_REDUCE = m.stream_reduce


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def scalar(v):
    if isinstance(v, np.generic):
        return v.item()
    raise TypeError(type(v).__name__)


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, allow_nan=False, default=scalar, separators=(',', ':'))


def atomic_json(path, value):
    """仅更新本任务的状态文件；结果文件另用排他创建。"""
    path = Path(path)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, default=scalar), encoding='utf-8')
    for attempt in range(5):
        try:
            os.replace(temp, path)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(.02)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def grid_value(value):
    if not isinstance(value, list) or len(value) != 3 or any(type(v) is not int or not 1 <= v <= 64 for v in value):
        raise ValueError('统计网格须为三项 1–64 的整数')
    if np.prod(value) > 65536:
        raise ValueError('当前单个分区最多 65536 格；这是本批资源限制，不是加工精度')
    return value


def make_plan(request, topo=None):
    topo = topo or read_json(d.TOPO)
    entries = request.get('blocks') if isinstance(request, dict) else None
    if not isinstance(entries, list) or not 1 <= len(entries) <= len(topo['blocks']):
        raise ValueError('请选择至少一个真实权重功能块')
    by_id = {b['id']: b for b in topo['blocks']}
    blocks, tasks, seen = [], {}, set()
    core = {p.name: d.sha(p) for p in (Path(__file__), Path(d.__file__), Path(m.__file__), Path(processing.__file__))}
    topology_sha = d.sha(d.TOPO)
    for item in entries:
        if not isinstance(item, dict) or not {'id','grid'} <= set(item) or set(item)-{'id','grid','source','convention','diagnostics'} or item['id'] not in by_id or item['id'] in seen:
            raise ValueError('块身份无效或重复；毛坯和 MTP 空框不能切权重')
        seen.add(item['id'])
        grid = grid_value(item['grid'])
        selected, convention, diagnostics = item.get('source','full'), item.get('convention','gguf'), item.get('diagnostics',False)
        if selected not in CHANNELS or convention not in ('gguf','hf') or type(diagnostics) is not bool:
            raise ValueError('统计来源、数值约定或诊断选项无效')
        outputs = ['full'] + (['feature','residual'] if selected in ('feature','residual') else ['rowcol'] if selected == 'rowcol' else [])
        if diagnostics:
            outputs.append('signed')
        b = by_id[item['id']]
        blocks.append({**b, 'slice_grid': grid, 'sourceConvention': convention, 'extraDiagnostics': diagnostics, 'selected_source': selected})
        for ref in b['tensors']:
            key = ref['file'] + ':' + ref['gguf']
            path = d.FILES[ref['file']]
            stat = path.stat()
            identity = {'key': key, 'ref': ref, 'grid': grid, 'core': core,
                        'source': {'name': path.name, 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns},
                        'topology_sha256': topology_sha, 'recipe': 'on-demand-v1', 'pool': 'abs_mean',
                                                'outputs': outputs, 'sourceConvention': convention, 'extraDiagnostics': diagnostics}
            if key in tasks:
                raise ValueError('一个张量不能在同一任务重复归入多个块')
            tasks[key] = {'key': key, 'ref': ref, 'grid': grid, 'signature': digest(identity), 'identity': identity, 'source_path': str(path),
                          'source': selected, 'convention': convention, 'diagnostics': diagnostics}
    blocks.sort(key=lambda b: b['id'])
    tasks = sorted(tasks.values(), key=lambda t: (t['ref']['file'], np.prod(t['ref']['shape']) > 100_000_000, t['key']))
    canonical = {'blocks': [{'id': b['id'], 'grid': b['slice_grid'], 'source': b['selected_source'],
                            'convention': b['sourceConvention'], 'diagnostics': b['extraDiagnostics']} for b in blocks]}
    return {'request': canonical, 'blocks': blocks, 'tasks': tasks, 'core': core,
            'signature': digest([t['signature'] for t in tasks]), 'topology_sha256': topology_sha,
            'block_count': len(blocks), 'tensor_count': len(tasks), 'recipe': 'on-demand-v1',
            'note': '按需生成：full直接池化，rowcol才计算行列强度，feature/residual才运行原谱配方；对齐与额外诊断显式可选。'}


def configure_grid(grid):
    """只在隔离的计算进程注入网格适配器；默认路径逐字调用原函数。"""
    grid_value(grid)
    original_pool = ORIGINAL_POOL
    original_reduce = ORIGINAL_REDUCE

    def pool(part, absolute=True):
        if grid == DEFAULT_GRID:
            return original_pool(part, absolute)
        dims = tuple(min(n, k) for n, k in zip(part.shape, grid))
        bounds = [np.linspace(0, n, g + 1, dtype=np.int64) for n, g in zip(part.shape, dims)]
        a = np.abs(part) if absolute else part
        for axis, edges in enumerate(bounds):
            a = np.add.reduceat(a, edges[:-1], axis=axis, dtype=np.float64)
        counts = np.diff(bounds[0])[:, None, None] * np.diff(bounds[1])[None, :, None] * np.diff(bounds[2])[None, None, :]
        values = (a / counts).astype(np.float32)
        assert int(counts.sum()) == part.size and counts.min() > 0
        expected = np.abs(part).sum(dtype=np.float64) if absolute else part.sum(dtype=np.float64)
        np.testing.assert_allclose(np.sum(values.astype(np.float64) * counts), expected, rtol=2e-6, atol=1e-5)
        return values, counts

    def reduce(source, frames, tick):
        if grid == DEFAULT_GRID:
            return original_reduce(source, frames, tick)
        rows, cols = source.shape
        gx, gy, gz = grid
        if gx * gy > rows or gz > cols:
            raise ValueError('流式折叠网格超过原始行列数')
        rb = np.linspace(0, rows, gx * gy + 1, dtype=int)
        cb = np.linspace(0, cols, gz + 1, dtype=int)
        counts = np.diff(rb)[:, None] * np.diff(cb)[None, :]
        sums = {k: np.zeros((gx * gy, gz), dtype=np.float64) for k in (*CHANNELS, 'signed')}
        for i in range(gx * gy):
            a, b = int(rb[i]), int(rb[i + 1])
            w = source.rows(a, b)
            for key, values in frames(w, a, b).items():
                sums[key][i] = np.add.reduceat(values.sum(axis=0, dtype=np.float64), cb[:-1])
            if i % 32 == 0:
                tick('大矩阵池化', row=b, total=rows)
        assert counts.sum() == rows * cols
        return [{'name': 'main', 'grid': grid, 'fold': {'basis': 'stream_row_bins', 'row_groups': gx * gy,
                 'row_group_shape': [gx, gy], 'column_groups': gz, 'note': '连续行分箱；不聚类、不跳取权重'},
                 'counts': counts.reshape(grid).ravel().tolist(),
                 **{k: (v / counts).astype(np.float32).reshape(grid).ravel().tolist() for k, v in sums.items()}}]

    d.pooled = pool
    m.pooled = pool
    m.stream_reduce = reduce


def worker(connection):
    reader, lookup, current_file = None, {}, None
    try:
        with threadpool_limits(limits=4):
            while True:
                job = connection.recv()
                if job is None:
                    break
                task, artifact = job
                try:
                    configure_grid(task['grid'])
                    ref = task['ref']
                    if current_file != task['source_path']:
                        reader = GGUFReader(task['source_path'], 'r')
                        lookup = {t.name: t for t in reader.tensors}
                        current_file = task['source_path']
                    source = processing.Source(lookup[ref['gguf']], ref, task['convention'])
                    def tick(stage, **info):
                        connection.send({'kind': 'stage', 'stage': stage, **info})
                    tick('解码／统计开始')
                    output = processing.compute(source, task['source'], task['diagnostics'], task['grid'], tick)
                    result = {'key': task['key'], 'name': ref['gguf'], 'file': ref['file'], 'shape': list(source.shape),
                              'quantization': ref['qtype'], 'restore': source.ref.get('restore'), 'storage_restore_rule': ref.get('restore'),
                                                            'sourceConvention': task['convention'], 'packed_sha256': source.packed_sha256,
                              'reference_white': 2 * output['statistics']['mean_abs'], 'slice_signature': task['signature'], **output}
                    validate(result)
                    result['windows'] = {}
                    for channel in CHANNELS:
                        values = [v for p in result['parts'] for v in (p.get(channel) or [])]
                        result['windows'][channel] = distribution(values) if values else None
                    artifact = Path(artifact)
                    artifact.mkdir(parents=True, exist_ok=False)
                    write_new(artifact / 'result.json', result)
                    index = {'key': task['key'], 'data_file': 'result.json', 'data_sha256': d.sha(artifact / 'result.json'),
                             'slice_signature': task['signature'], 'packed_sha256': source.packed_sha256,
                             'shape': list(source.shape), 'grid': task['grid'], 'sourceConvention': task['convention'],
                                                          'extraDiagnostics': task['diagnostics'], 'channel_status': output['channel_status']}
                    write_new(artifact / 'complete.json', index)
                    connection.send({'kind': 'result', 'index': index})
                    del source, output, result
                except Exception as e:
                    connection.send({'kind': 'error', 'error': repr(e), 'traceback': traceback.format_exc()})
                gc.collect()
    finally:
        connection.close()


def reusable(task, store, packed_sha):
    for marker in sorted((store / 'artifacts' / task['signature']).glob('*/complete.json')):
        try:
            index = read_json(marker)
            path = marker.parent / 'result.json'
            if index['slice_signature'] == task['signature'] and index['packed_sha256'] == packed_sha and d.sha(path) == index['data_sha256']:
                result = read_json(path)
                validate(result)
                if result['key'] == task['key']:
                    return index, path
        except (ValueError, OSError, KeyError, AssertionError):
            continue
    return None


def run_job(folder, store=STORE):
    folder, store = Path(folder), Path(store)
    if (folder / 'manifest.json').exists():
        raise FileExistsError('此任务已有结果；请建立新任务并复用完成张量，不覆盖旧任务')
    plan = read_json(folder / 'plan.json')
    # 运行前再次核对源文件身份和当前核心，不允许排队时更换原件。
    current = make_plan(plan['request'])
    if current['signature'] != plan['signature']:
        raise ValueError('源文件、拓扑或计算核心已变化，请建立新任务')
    start = time.monotonic()
    status = {'id': folder.name, 'state': 'running', 'completed': 0, 'failed': 0, 'reused': 0,
              'total': len(plan['tasks']), 'stage': '准备任务', 'signature': plan['signature']}
    entries, failures = {}, []
    reader, lookup, source_file = None, {}, None
    process, parent = None, None
    def emit(stage, **info):
        status.update(stage=stage, elapsed_seconds=round(time.monotonic() - start, 2), **info)
        atomic_json(folder / 'status.json', status)
        with (folder / 'progress.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(status, ensure_ascii=False, default=scalar) + '\n')
    emit('开始任务')
    try:
        for task in plan['tasks']:
            if (folder / 'cancel').exists():
                status['state'] = 'cancelled'
                break
            emit('核对可复用统计', tensor=task['key'], source=task['source'], convention=task['convention'],
                 svd_enabled=task['source'] in ('feature','residual'), diagnostics=task['diagnostics'], iteration=None, rank=None)
            # 复用前比较当前原张量的压缩字节SHA256，而非只信文件时间戳。
            if source_file != task['source_path']:
                reader = GGUFReader(task['source_path'], 'r')
                lookup = {t.name: t for t in reader.tensors}
                source_file = task['source_path']
            packed_sha = d.TensorSource(lookup[task['ref']['gguf']], task['ref']).packed_sha256
            found = reusable(task, store, packed_sha)
            if found:
                index, path = found
                status['reused'] += 1
            else:
                attempt = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                path = store / 'artifacts' / task['signature'] / attempt / 'result.json'
                if process is None or not process.is_alive():
                    parent, child = mp.Pipe()
                    process = mp.Process(target=worker, args=(child,), daemon=True)
                    process.start()
                    child.close()
                parent.send((task, str(path.parent)))
                begin, last = time.monotonic(), time.monotonic()
                limit = 420 if np.prod(task['ref']['shape']) > 100_000_000 else 180
                index, error = None, None
                try:
                    while True:
                        if (folder / 'cancel').exists():
                            status['state'] = 'cancelled'
                            break
                        if parent.poll(.5):
                            msg = parent.recv()
                            if msg['kind'] == 'result':
                                index = msg['index']
                                break
                            if msg['kind'] == 'error':
                                error = msg['error']+'\n'+msg.get('traceback','')
                                break
                            emit(msg['stage'], **{k: v for k, v in msg.items() if k not in ('kind', 'stage')})
                            last = time.monotonic()
                        if not process.is_alive():
                            error = '计算子进程退出'
                            break
                        if time.monotonic() - begin > limit:
                            error = f'单张量超过 {limit} 秒，保留已完成结果'
                            break
                        if getattr(psutil.Process(process.pid).memory_info(), 'private', psutil.Process(process.pid).memory_info().rss) > 3 * 1024**3:
                            error = '计算子进程私有内存超过 3 GiB'
                            break
                        if time.monotonic() - last >= 10:
                            emit(status['stage'], heartbeat=True)
                            last = time.monotonic()
                except (EOFError, OSError, psutil.NoSuchProcess) as e:
                    error = repr(e)
                finally:
                    if index is None:
                        if process.is_alive():
                            process.terminate()
                        process.join(5)
                        parent.close()
                        process, parent = None, None
                if status['state'] == 'cancelled':
                    break
                if error or index is None:
                    failures.append({'key': task['key'], 'error': error or '结果缺失'})
                    status['failed'] += 1
                    emit('张量失败，继续下一项', error=failures[-1]['error'])
                    continue
            entry = {**index, 'url': '/api/slice1/files/' + path.relative_to(store).as_posix()}
            entries[task['key']] = entry
            status['completed'] += 1
            emit('张量完成')
        blocks = [{**b, 'slice_signature': plan['signature'], 'source_run': folder.name} for b in plan['blocks']
                  if all(t['file'] + ':' + t['gguf'] in entries for t in b['tensors'])]
        manifest = {'schema': 'snowglass.slice1.v1', 'source_run': folder.name, 'status': 'complete' if len(entries) == status['total'] else 'partial',
                    'topology_sha256': plan['topology_sha256'], 'signature': plan['signature'], 'request': plan['request'],
                    'recipe': plan['recipe'], 'blocks': blocks, 'tensors': list(entries.values()), 'failures': failures,
                    'completed_blocks': len(blocks), 'requested_blocks': len(plan['blocks']),
                    'note': '仅发布全部成员张量成功的块；源统计独立于灰度、包络和小块毫米边长。'}
        write_new(folder / 'manifest.json', manifest)
        if status['state'] != 'cancelled':
            status['state'] = 'complete' if not failures else 'partial'
        emit('任务结束', manifest_url='/api/slice1/jobs/' + folder.name + '/manifest', failures=failures)
    except Exception as e:
        emit('任务失败', state='failed', error=repr(e))
        raise
    finally:
        if process is not None:
            if process.is_alive():
                parent.send(None)
            process.join(5)
            if process.is_alive():
                process.terminate();process.join(5)
            parent.close()


def create_job(request, store=STORE):
    plan = make_plan(request)
    job = Path(store) / 'jobs' / ('slice-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    job.mkdir(parents=True, exist_ok=False)
    write_new(job / 'plan.json', plan)
    atomic_json(job / 'status.json', {'id': job.name, 'state': 'queued', 'total': plan['tensor_count'], 'completed': 0,
                'failed': 0, 'reused': 0, 'stage': '等待计算', 'signature': plan['signature']})
    return job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, help='块身份与网格的JSON；每次新建任务')
    parser.add_argument('--job', type=Path, help='执行服务已建立的任务')
    args = parser.parse_args()
    if bool(args.request) == bool(args.job):
        parser.error('二选一：--request 或 --job')
    folder = args.job.resolve() if args.job else create_job(read_json(args.request))
    if not folder.is_relative_to(STORE.resolve()):
        parser.error('任务只能位于 out/slices/jobs')
    print(json.dumps({'job': str(folder)}, ensure_ascii=False), flush=True)
    run_job(folder)


if __name__ == '__main__':
    mp.freeze_support()
    main()

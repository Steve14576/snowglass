"""按需生成统计。只保留必需池化，原谱函数不改；原约定对齐与诊断显式可选。"""
import numpy as np
from gguf.quants import dequantize

import survey_data as d
import survey_math as m

CHANNELS = ('full', 'feature', 'residual', 'rowcol')


class Source(d.TensorSource):
    def __init__(self, tensor, ref, convention):
        self.storage_rule = ref.get('restore')
        self.convention = convention
        effective = dict(ref)
        if convention == 'gguf':
            effective['restore'] = None
        super().__init__(tensor, effective)

    def decode(self):
        w = np.ascontiguousarray(dequantize(self.tensor.data, self.tensor.tensor_type).reshape(self.shape), dtype=np.float32)
        if self.ref.get('restore'):
            w = d.restore(w, self.ref['restore'])
        if not np.isfinite(w).all():
            raise ValueError('解码值非有限，不生成替代纹理')
        return w


def statuses(source):
    status = {k: 'not_generated' for k in CHANNELS}
    status['full'] = 'ready'
    if source in ('feature', 'residual'):
        status['feature'] = status['residual'] = 'ready'
    elif source == 'rowcol':
        status['rowcol'] = 'ready'
    return status


def mean_abs(parts):
    n = sum(sum(p['counts']) for p in parts)
    return sum(sum(v * c for v, c in zip(p['full'], p['counts'])) for p in parts) / n


def dense(source, selected, diagnostics, tick):
    w = source.decode()
    tick('解码完成', convention=getattr(source, 'convention', 'gguf'))
    parts = []
    for name, values, fold in d.split_parts(w, source.ref):
        pooled, count = d.pooled(values)
        signed = d.pooled(values, False)[0].ravel().tolist() if diagnostics else None
        parts.append({'name': name, 'grid': list(pooled.shape), 'fold': fold, 'counts': count.ravel().tolist(),
                      'full': pooled.ravel().tolist(), 'signed': signed, 'feature': None, 'residual': None, 'rowcol': None})
    info = {'mean_abs': mean_abs(parts)}
    if diagnostics:
        info = m.stats(w)
    status = statuses(selected)
    spectral = {'method': 'not_computed', 'reason': '未选择谱来源，不运行SVD', 'retained': None, 'rank_capped': False}
    if selected in ('feature', 'residual'):
        if 'rms' not in info:
            info['rms'] = float(np.sqrt(np.einsum('i,i->', w.ravel(), w.ravel(), dtype=np.float64) / w.size))
        if w.ndim == 2 and min(w.shape) >= 64 and info['rms'] > 0:
            spectral = m.spectral_matrix(w, source.ref, parts, info, tick)
        else:
            for part in parts:
                part['feature'] = part['full'].copy()
            spectral = {'method': 'direct', 'reason': '此张量不适用谱分解；特征为直接幅度',
                        'retained': None, 'rank_capped': False, 'pooled_iteration_change': None}
            status['feature'] = status['residual'] = 'not_applicable'
    if selected == 'rowcol':
        if w.ndim == 2:
            row = np.sqrt(np.einsum('ij,ij->i', w, w, dtype=np.float64) / w.shape[1])
            col = np.sqrt(np.einsum('ij,ij->j', w, w, dtype=np.float64) / w.shape[0])
            outer = np.outer(row, col).astype(np.float32)
            if outer.mean(dtype=np.float64):
                outer *= info['mean_abs'] / outer.mean(dtype=np.float64)
            d.assign_channel(parts, outer, source.ref, 'rowcol')
        else:
            status['rowcol'] = 'not_applicable'
    return {'parts': parts, 'statistics': info, 'spectral': spectral, 'channel_status': status,
            'extraDiagnostics': diagnostics}


def bins(source, grid):
    rows, cols = source.shape
    x, y, z = grid
    if x * y > rows or z > cols:
        raise ValueError('流式网格超过原始行列数')
    rb = np.linspace(0, rows, x * y + 1, dtype=int)
    cb = np.linspace(0, cols, z + 1, dtype=int)
    count = np.diff(rb)[:, None] * np.diff(cb)[None, :]
    return rb, cb, count


def part_from_sums(sums, count, grid):
    return {'name': 'main', 'grid': grid, 'counts': count.reshape(grid).ravel().tolist(),
            'fold': {'basis': 'stream_row_bins', 'row_groups': grid[0] * grid[1],
                     'row_group_shape': grid[:2], 'column_groups': grid[2], 'note': '连续行分箱；不聚类、不跳取'},
            **{k: (v / count).astype(np.float32).reshape(grid).ravel().tolist() if v is not None else None
               for k, v in sums.items()}}


def stream_direct(source, selected, diagnostics, grid, tick):
    """一遍分块读取生成full；行列强度用可分离的外积，不分配整张外积阵。"""
    rows, cols = source.shape
    rb, cb, count = bins(source, grid)
    sums = {k: None for k in (*CHANNELS, 'signed')}
    sums['full'] = np.zeros(count.shape, dtype=np.float64)
    if diagnostics:
        sums['signed'] = np.zeros(count.shape, dtype=np.float64)
    if selected == 'rowcol':
        row_sums = np.zeros(len(rb) - 1, dtype=np.float64)
        col2 = np.zeros(cols, dtype=np.float64)
    square_sum, zeros = 0., 0
    minimum, maximum = float('inf'), -float('inf')
    for i in range(len(rb) - 1):
        a, b = int(rb[i]), int(rb[i + 1])
        w = source.rows(a, b)
        if not np.isfinite(w).all():
            raise ValueError('解码值非有限')
        sums['full'][i] = np.add.reduceat(np.abs(w).sum(axis=0, dtype=np.float64), cb[:-1])
        if selected == 'rowcol':
            row_sums[i] = np.sqrt(np.einsum('ij,ij->i', w, w, dtype=np.float64) / cols).sum()
            col2 += np.einsum('ij,ij->j', w, w, dtype=np.float64)
        if diagnostics:
            sums['signed'][i] = np.add.reduceat(w.sum(axis=0, dtype=np.float64), cb[:-1])
            square_sum += float(np.einsum('i,i->', w.ravel(), w.ravel(), dtype=np.float64))
            minimum, maximum = min(minimum, float(w.min())), max(maximum, float(w.max()))
            zeros += int(np.count_nonzero(w == 0))
        if i % 32 == 0:
            tick('直接分块池化', row=b, total=rows)
    mean = float(sums['full'].sum() / (rows * cols))
    if selected == 'rowcol':
        col = np.sqrt(col2 / rows)
        outer_mean = (row_sums.sum() / rows) * col.mean()
        col_means = np.add.reduceat(col, cb[:-1]) / np.diff(cb)
        row_means = row_sums / np.diff(rb)
        sums['rowcol'] = np.outer(row_means, col_means) * (mean / outer_mean if outer_mean else 0) * count
    info = {'mean_abs': mean}
    if diagnostics:
        info.update(rms=float(np.sqrt(square_sum / (rows * cols))), minimum=minimum, maximum=maximum,
                    zero_fraction=zeros / (rows * cols))
    part = part_from_sums(sums, count, grid)
    assert sum(part['counts']) == rows * cols
    return {'parts': [part], 'statistics': info, 'spectral': {'method': 'not_computed',
            'reason': '直接分块池化，不运行SVD', 'retained': None, 'rank_capped': False},
            'channel_status': statuses(selected), 'extraDiagnostics': diagnostics}


def stream_spectral(source, diagnostics, grid, tick):
    """沿用原96方向/4次求解，只在显式选择谱来源时执行；不预算rowcol。"""
    rows, cols = source.shape
    rank, width, chunk = 96, 112, 2048
    if min(rows, cols) < width:
        raise ValueError('此超大矩阵不适用原流式谱配方')
    z, _ = np.linalg.qr(np.random.default_rng(m.SEED).standard_normal((cols, width), dtype=np.float32))
    row2 = np.zeros(rows, dtype=np.float64)
    abs_sum, zeros = 0., 0
    minimum, maximum = float('inf'), -float('inf')
    for iteration in range(4):
        accumulation = np.zeros((cols, width), dtype=np.float64)
        for start in range(0, rows, chunk):
            end = min(rows, start + chunk)
            w = source.rows(start, end)
            accumulation += w.T @ (w @ z)
            if iteration == 0:
                row2[start:end] = np.einsum('ij,ij->i', w, w, dtype=np.float64)
                abs_sum += float(np.abs(w).sum(dtype=np.float64))
                if diagnostics:
                    minimum, maximum = min(minimum, float(w.min())), max(maximum, float(w.max()))
                    zeros += int(np.count_nonzero(w == 0))
            if start % (chunk * 8) == 0:
                tick('大矩阵分块子空间迭代', iteration=iteration + 1, row=end, total=rows)
        z, _ = np.linalg.qr(accumulation.astype(np.float32))
    mean = abs_sum / (rows * cols)
    rms = float(np.sqrt(row2.sum() / (rows * cols)))
    threshold = rms * (np.sqrt(rows) + np.sqrt(cols))
    y = np.empty((rows, width), dtype=np.float32)
    for start in range(0, rows, chunk):
        end = min(rows, start + chunk)
        y[start:end] = source.rows(start, end) @ z
    q, _ = np.linalg.qr(y)
    del y
    b = np.zeros((width, cols), dtype=np.float64)
    for start in range(0, rows, chunk):
        end = min(rows, start + chunk)
        b += q[start:end].T @ source.rows(start, end)
    ub, values, vt = np.linalg.svd(b, full_matrices=False)
    u = (q @ ub[:, :rank]).astype(np.float32)
    values, vt = values[:rank], vt[:rank].astype(np.float32)
    keep = values > threshold
    left, right = u[:, keep] * values[keep].astype(np.float32), vt[keep]
    del q, b, u
    rb, cb, count = bins(source, grid)
    sums = {k: None for k in (*CHANNELS, 'signed')}
    for k in ('full', 'feature', 'residual') + (('signed',) if diagnostics else ()):
        sums[k] = np.zeros(count.shape, dtype=np.float64)
    for i in range(len(rb) - 1):
        a, end = int(rb[i]), int(rb[i + 1])
        w = source.rows(a, end)
        reconstructed = left[a:end] @ right
        frames = {'full': np.abs(w), 'feature': np.abs(reconstructed), 'residual': np.abs(w - reconstructed)}
        if diagnostics:
            frames['signed'] = w
        for k, v in frames.items():
            sums[k][i] = np.add.reduceat(v.sum(axis=0, dtype=np.float64), cb[:-1])
        if i % 32 == 0:
            tick('大矩阵谱通道池化', row=end, total=rows)
    info = {'mean_abs': mean, 'rms': rms}
    if diagnostics:
        info.update(minimum=minimum, maximum=maximum, zero_fraction=zeros / (rows * cols))
    return {'parts': [part_from_sums(sums, count, grid)], 'statistics': info, 'extraDiagnostics': diagnostics,
            'channel_status': statuses('feature'), 'spectral': {'method': 'stream_spectral', 'rank_limit': rank,
            'iterations': 4, 'retained': int(keep.sum()), 'rank_capped': bool(keep[-1]), 'threshold': threshold,
            'energy_fraction': float(np.sum(values[keep] ** 2) / row2.sum()) if row2.sum() else 0,
            'pooled_iteration_change': None, 'convergence_note': '沿用原流式精度；未增加收敛对照',
            'singular_values': values.tolist(), 'threshold_counts': {str(v): int((values > v * threshold).sum()) for v in (.8, 1, 1.2)}}}


def compute(source, selected, diagnostics, grid, tick):
    if selected not in CHANNELS or type(diagnostics) is not bool:
        raise ValueError('统计来源或诊断选项无效')
    if np.prod(source.shape) > 100_000_000:
        if len(source.shape) != 2 or source.ref.get('restore'):
            raise ValueError('当前超大张量只支持无需约定还原的二维流式处理')
        return stream_spectral(source, diagnostics, grid, tick) if selected in ('feature', 'residual') else stream_direct(source, selected, diagnostics, grid, tick)
    return dense(source, selected, diagnostics, tick)

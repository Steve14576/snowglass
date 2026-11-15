"""量化可见性测试：BF16 vs 模拟 Q8 / Q4，在同一张真实权重上跑完整"池化 → 8bit → 灰度"链路。

要回答的问题：
  1. 池化到体素尺度后，Q4 与 BF16 的图差多少？
  2. 底噪（局部纹理）是否被量化误差替换？
  3. 对比度（p99/p1）是否被压平 —— 即"亮点变钝"是否成立？
  4. 残差在空间上是白噪声还是带结构？

只 Range 取一个张量（约 100 MB），不下载整个 shard。

用法：
  uv run --no-project --with numpy python scripts/test_quant_visibility.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

import numpy as np

REPO = "Qwen/Qwen3.5-9B"
BASE = f"https://huggingface.co/{REPO}/resolve/main/"
SHARD = "model.safetensors-00002-of-00004.safetensors"
TENSOR = "model.language_model.layers.0.mlp.down_proj.weight"

BLOCK = 32          # 块量化块大小（GGUF Q4_0 / Q8_0 都是 32）
POOL = 100          # 池化后的体素边长（对应 8 mm 模块在 0.08 点距下的 100 格）
GAMMA = 2.4
FLOOR = 0.03
SEED = 20261115


def fetch_range(url: str, start: int, end: int, retries: int = 3) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"range fetch failed: {last}")


def read_header(url: str) -> tuple[dict, int]:
    n = int.from_bytes(fetch_range(url, 0, 7), "little")
    hdr = json.loads(fetch_range(url, 8, 8 + n - 1))
    return hdr, n


def load_bf16_tensor(url: str, name: str) -> tuple[np.ndarray, str]:
    hdr, hlen = read_header(url)
    meta = hdr[name]
    begin, end = meta["data_offsets"]
    dt = meta["dtype"]
    shape = meta["shape"]
    nbytes = end - begin
    mb = nbytes / 1e6
    print(f"  tensor   : {name}")
    print(f"  shape    : {shape}  dtype={dt}  bytes={mb:.1f} MB")
    t0 = time.time()
    buf = fetch_range(url, 8 + hlen + begin, 8 + hlen + end - 1)
    dt_s = time.time() - t0
    print(f"  fetched  : {len(buf)/1e6:.1f} MB in {dt_s:.1f}s ({len(buf)/1e6/max(dt_s,1e-6):.1f} MB/s)")
    if len(buf) != nbytes:
        raise RuntimeError(f"字节数不符: 期望 {nbytes}, 实得 {len(buf)}")

    if dt == "BF16":
        u16 = np.frombuffer(buf, dtype="<u2")
        w = (u16.astype(np.uint32) << 16).view(np.float32)
    elif dt == "F16":
        w = np.frombuffer(buf, dtype="<f2").astype(np.float32)
    elif dt == "F32":
        w = np.frombuffer(buf, dtype="<f4").astype(np.float32)
    else:
        raise RuntimeError(f"未支持的 dtype: {dt}")
    return np.ascontiguousarray(w.reshape(shape)), dt


def block_quantize(w: np.ndarray, bits: int, block: int = BLOCK) -> np.ndarray:
    """对称块量化：每 block 个权重共享一个 absmax scale，round 到 2^(bits-1)-1 级。"""
    flat = w.reshape(-1).astype(np.float32, copy=True)
    n = flat.size
    pad = (-n) % block
    if pad:
        flat = np.concatenate([flat, np.zeros(pad, dtype=np.float32)])
    blk = flat.reshape(-1, block)
    absmax = np.abs(blk).max(axis=1, keepdims=True)
    levels = float((1 << (bits - 1)) - 1)
    step = np.where(absmax > 0, absmax / levels, 1.0)
    q = np.clip(np.rint(blk / step), -levels, levels) * step
    out = q.reshape(-1)
    if pad:
        out = out[:n]
    return out.reshape(w.shape)


def pool_absmean(w: np.ndarray, size: int) -> np.ndarray:
    """按行/列分块，取 |w| 的均值，缩放成 size×size。"""
    m, n = w.shape
    rows = np.linspace(0, m, size + 1).astype(int)
    cols = np.linspace(0, n, size + 1).astype(int)
    a = np.abs(w)
    out = np.empty((size, size), dtype=np.float64)
    for i in range(size):
        r0, r1 = rows[i], max(rows[i] + 1, rows[i + 1])
        band = a[r0:r1]
        cs = np.add.reduceat(band, cols[:-1], axis=1)
        cnt = np.diff(cols)
        out[i] = cs.sum(axis=0) / (band.shape[0] * cnt)
    return out


def pool_local_std(w: np.ndarray, size: int) -> np.ndarray:
    """局部标准差，作为"纹理/底噪强度"的代理。"""
    m, n = w.shape
    rows = np.linspace(0, m, size + 1).astype(int)
    cols = np.linspace(0, n, size + 1).astype(int)
    a = np.abs(w)
    out = np.empty((size, size), dtype=np.float64)
    for i in range(size):
        r0, r1 = rows[i], max(rows[i] + 1, rows[i + 1])
        band = a[r0:r1]
        cs1 = np.add.reduceat(band, cols[:-1], axis=1)
        cs2 = np.add.reduceat(band * band, cols[:-1], axis=1)
        cnt = np.diff(cols)
        tot = band.shape[0] * cnt
        mean = cs1.sum(axis=0) / tot
        var = cs2.sum(axis=0) / tot - mean * mean
        out[i] = np.sqrt(np.maximum(var, 0))
    return out


def normalize(a: np.ndarray) -> np.ndarray:
    lo, hi = float(np.percentile(a, 0.5)), float(np.percentile(a, 99.5))
    if hi <= lo:
        return np.zeros_like(a)
    return np.clip((a - lo) / (hi - lo), 0.0, 1.0)


def to_gray(a01: np.ndarray) -> np.ndarray:
    return np.rint(a01 * 255).astype(np.uint8)


def to_prob(gray8: np.ndarray) -> np.ndarray:
    base = gray8.astype(np.float64) / 255.0
    return np.clip(FLOOR + (1.0 - FLOOR) * base ** GAMMA, 0.0, 1.0)


def autocorr(a: np.ndarray, lag: int, axis: int) -> float:
    x = a - a.mean()
    y = np.roll(x, lag, axis=axis)
    denom = float((x * x).sum())
    return float((x * y).sum() / denom) if denom else 0.0


def top_singulars(w: np.ndarray, k: int = 8, seed: int = 0) -> np.ndarray:
    """随机化 SVD 取前 k 个奇异值，成本约 O(m n k)。"""
    rng = np.random.default_rng(seed)
    m, n = w.shape
    p = min(k + 10, min(m, n))
    omega = rng.standard_normal((n, p), dtype=np.float32)
    a = (w.astype(np.float32) @ omega).astype(np.float64)
    q, _ = np.linalg.qr(a)
    b = (q.T.astype(np.float32) @ w.astype(np.float32)).astype(np.float64)
    s = np.linalg.svd(b, compute_uv=False)
    return s[:k]


def main() -> int:
    url = BASE + SHARD
    print("=" * 72)
    print("step 1  load one real tensor (range fetch only)")
    print("=" * 72)
    w, dt = load_bf16_tensor(url, TENSOR)
    m, n = w.shape
    print(f"  stats    : mean|w|={np.abs(w).mean():.5f}  rms={np.sqrt((w.astype(np.float64)**2).mean()):.5f}")
    print()

    print("=" * 72)
    print("step 2  simulate quantized variants")
    print("=" * 72)
    t0 = time.time()
    w8 = block_quantize(w, 8)
    w4 = block_quantize(w, 4)
    print(f"  Q8 / Q4 simulated in {time.time()-t0:.1f}s  (block={BLOCK})")
    for tag, q in (("Q8", w8), ("Q4", w4)):
        err = (q - w).astype(np.float64)
        sigma = float(np.sqrt((w.astype(np.float64) ** 2).mean()))
        print(f"  {tag}: rms_err={np.sqrt((err**2).mean()):.6f}  "
              f"rel_to_sigma={np.sqrt((err**2).mean())/sigma*100:.1f}%")
    print()

    print("=" * 72)
    print(f"step 3  pool to {POOL}x{POOL} (the actual voxel scale)  tile = "
          f"{m/POOL:.0f} x {n/POOL:.0f} weights")
    print("=" * 72)
    maps = {}
    for tag, src in (("bf16", w), ("q8", w8), ("q4", w4)):
        am = pool_absmean(src, POOL)
        maps[tag] = {"absmean": am, "lstd": pool_local_std(src, POOL)}
    print(f"  weights per voxel ≈ {(m/POOL)*(n/POOL):.0f}")
    print()

    print("=" * 72)
    print("step 4  8-bit gray + gamma/floor, compare maps")
    print("=" * 72)
    ref = maps["bf16"]
    g_ref = to_gray(normalize(ref["absmean"]))
    p_ref = to_prob(g_ref)
    for tag in ("q8", "q4"):
        cur = maps[tag]
        g = to_gray(normalize(cur["absmean"]))
        p = to_prob(g)
        dl1 = float(np.abs(g.astype(int) - g_ref.astype(int)).mean())
        dmax = int(np.abs(g.astype(int) - g_ref.astype(int)).max())
        corr = float(np.corrcoef(g.ravel(), g_ref.ravel())[0, 1])
        dp = float(np.abs(p - p_ref).mean() / max(p_ref.mean(), 1e-9))
        print(f"  {tag.upper()}")
        print(f"    8bit map : L1={dl1:.2f} levels  max={dmax} levels  corr={corr:.6f}")
        print(f"    p map    : mean |dp| / mean p = {dp*100:.2f}%")
        print(f"    residual : rms={np.sqrt(((cur['absmean']-ref['absmean'])**2).mean()):.6e} "
              f"vs map std={ref['absmean'].std():.6e}")
        r = cur["absmean"] - ref["absmean"]
        print(f"    autocorr : lag1(x)={autocorr(r,1,1):+.4f} lag1(y)={autocorr(r,1,0):+.4f} "
              f"lag4(x)={autocorr(r,4,1):+.4f}")
    print()

    print("=" * 72)
    print("step 5  contrast (are highlights flattened?)")
    print("=" * 72)
    for tag in ("bf16", "q8", "q4"):
        a = normalize(maps[tag]["absmean"])
        p1, p50, p99 = np.percentile(a, [1, 50, 99])
        print(f"  {tag.upper():5s} p1={p1:.4f} p50={p50:.4f} p99={p99:.4f} "
              f"(p99-p1)={p99-p1:.4f} std={a.std():.4f}")
    print()

    print("=" * 72)
    print("step 6  does the spectral split stay put?  (top singular values)")
    print("=" * 72)
    q_asp = n / m
    sigma = float(np.sqrt((w.astype(np.float64) ** 2).mean()))
    lam_plus = sigma ** 2 * (1 + 1 / np.sqrt(q_asp)) ** 2
    print(f"  MP upper edge lambda+ = {lam_plus:.6e}   (asymptotic, iid-gaussian assumption)")
    t0 = time.time()
    s_bf = top_singulars(w, 8, seed=1)
    s_q4 = top_singulars(w4, 8, seed=1)
    print(f"  randomized SVD k=8 in {time.time()-t0:.1f}s")
    print(f"  idx   sigma_bf16        sigma_q4          rel_diff   inside_MP_bulk?")
    for i in range(8):
        rel = (s_q4[i] - s_bf[i]) / s_bf[i] if s_bf[i] else 0.0
        # 判定：sigma^2 是否落在 bulk 内
        inside = "yes(bulk)" if s_bf[i] ** 2 <= lam_plus else "no (spike)"
        print(f"  {i:3d}  {s_bf[i]:.6e}   {s_q4[i]:.6e}   {rel*100:+7.3f}%  {inside}")
    print()

    print("=" * 72)
    print("summary")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())

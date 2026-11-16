"""阶段 0 核对（线性注意力的头顺序）：llama.cpp 转换时是否重排了 GDN 的 value 头？重排规则是什么？涉及哪些张量？

背景：verify_gguf_1d.py 发现 blk.0.ssm_dt.bias 与 HF dt_bias 的 32 个值相同但顺序不同。
本脚本：
  1. 用 dt_bias 的数值匹配，求出 GGUF 第 j 个 value 头对应 HF 的第 p[j] 个
  2. 检验 A_log -> ssm_a 在 p 下是否严格等于 -exp(A_log)
  3. 对每个相关二维张量，按 128 行（或列）一个头分块，找出每块在 HF 里对应哪一块，看是否与 p 一致

用法：
  uv run --no-project --with gguf --with numpy python scripts/verify_gguf_gdn_order.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_quant_visibility as qv  # 复用带重试的 Range 取数
from verify_gguf_1d import fetch_hf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GGUF = ROOT / "data" / "gguf" / "Qwen3.5-9B-Q4_K_M.gguf"
L = "model.language_model.layers.0.linear_attn."
HD = 128          # 每头维度（GGUF: ssm.state_size = 128）
N_V = 32          # value 头数（GGUF: ssm.time_step_rank = 32）
N_K = 16          # key 头数（GGUF: ssm.group_count = 16）


def block_match(gg: np.ndarray, hf: np.ndarray, axis: int, n_blocks: int, offset: int, step: int):
    """把 gg 与 hf 沿 axis 从 offset 起切成 n_blocks 块（每块 step 行或列），返回 gg 每块最像的 hf 块号与最差的那个相关系数。"""
    def take(a, i):
        sl = [slice(None)] * a.ndim
        sl[axis] = slice(offset + i * step, offset + (i + 1) * step)
        return a[tuple(sl)].ravel()

    hf_blocks = [take(hf, i) for i in range(n_blocks)]
    hf_blocks = [(b - b.mean()) / (b.std() + 1e-30) for b in hf_blocks]
    out, cors = [], []
    for j in range(n_blocks):
        g = take(gg, j)
        g = (g - g.mean()) / (g.std() + 1e-30)
        c = [float((g * h).mean()) for h in hf_blocks]
        k = int(np.argmax(c))
        out.append(k)
        cors.append(c[k])
    return out, min(cors)


def main() -> int:
    from gguf import GGUFReader
    from gguf.quants import dequantize

    raw = qv.fetch_range(qv.BASE + "model.safetensors.index.json", 0, 50_000_000)
    wmap = json.loads(raw)["weight_map"]
    headers: dict = {}
    reader = GGUFReader(str(GGUF), "r")
    gg = {t.name: t for t in reader.tensors}

    def g(name):
        t = gg[name]
        return dequantize(t.data, t.tensor_type).astype(np.float32)

    # 1. 求置换：按数值匹配会被重复值干扰（BF16 下有个别头的 dt_bias 恰好相等），
    #    所以先按数值匹配看出规律，再把规律当候选、用 dt_bias 与 A_log 两个张量严格验证。
    hf_dt = fetch_hf(L + "dt_bias", wmap, headers).ravel().astype(np.float64)
    gg_dt = g("blk.0.ssm_dt.bias").ravel().astype(np.float64)
    p_value = [int(np.argmin(np.abs(hf_dt - v))) for v in gg_dt]
    print("== 按数值匹配得到的对应（会被重复值干扰）")
    print(f"  {p_value}")
    print(f"  HF dt_bias 里数值重复的头："
          f"{[i for i in range(N_V) if (hf_dt == hf_dt[i]).sum() > 1]}")

    hf_a = fetch_hf(L + "A_log", wmap, headers).ravel().astype(np.float64)
    gg_a = g("blk.0.ssm_a").ravel().astype(np.float64)

    rules = {
        "p[j] = (j mod 16)*2 + floor(j/16)  [GGUF 前 16 个 = HF 偶数号，后 16 个 = HF 奇数号]":
            [(j % N_K) * 2 + j // N_K for j in range(N_V)],
        "p[j] = floor(j/2) + (j mod 2)*16":
            [(j // 2) + (j % 2) * N_K for j in range(N_V)],
        "p[j] = j（不重排）":
            list(range(N_V)),
    }
    p = None
    print()
    print("== 用 dt_bias 与 A_log 严格验证候选规则")
    for desc, cand in rules.items():
        e_dt = np.abs(hf_dt[cand] - gg_dt).max()
        e_a = np.abs(-np.exp(hf_a[cand]) - gg_a).max()
        ok = e_dt == 0 and e_a < 1e-6
        print(f"  {desc}")
        print(f"      dt_bias 最大差 {e_dt:.2e}   ssm_a vs -exp(A_log) 最大差 {e_a:.2e}   {'成立' if ok else '不成立'}")
        if ok and p is None:
            p = cand
    if p is None:
        print("  没有候选规则成立，停止")
        return 1
    print()

    # 3. 二维张量逐块比对
    checks = [
        ("in_proj_a.weight", "blk.0.ssm_alpha.weight", 0, N_V, 0, 1),     # 行 = 32 个 value 头，每头 1 行
        ("in_proj_b.weight", "blk.0.ssm_beta.weight", 0, N_V, 0, 1),
        ("in_proj_z.weight", "blk.0.attn_gate.weight", 0, N_V, 0, HD),    # 行 = 32 × 128
        ("out_proj.weight", "blk.0.ssm_out.weight", 1, N_V, 0, HD),       # 列 = 32 × 128
        ("in_proj_qkv.weight", "blk.0.attn_qkv.weight", 0, N_K, 0, HD),   # q 段：行 0..2047
        ("in_proj_qkv.weight", "blk.0.attn_qkv.weight", 0, N_K, 2048, HD),  # k 段：行 2048..4095
        ("in_proj_qkv.weight", "blk.0.attn_qkv.weight", 0, N_V, 4096, HD),  # v 段：行 4096..8191
        ("conv1d.weight", "blk.0.ssm_conv1d.weight", 0, N_V, 4096, HD),     # conv 的 v 通道
        ("conv1d.weight", "blk.0.ssm_conv1d.weight", 0, N_K, 0, HD),        # conv 的 q 通道
    ]
    hf_cache: dict = {}
    print("== 二维张量按头分块比对（每块找 HF 里最像的那块）")
    for hf_name, gg_name, axis, n, off, step in checks:
        if hf_name not in hf_cache:
            hf_cache[hf_name] = fetch_hf(L + hf_name, wmap, headers).astype(np.float32)
        h = hf_cache[hf_name]
        w = g(gg_name)
        if h.ndim == 3:                       # conv1d: HF [8192, 1, 4] -> [8192, 4]
            h = h.reshape(h.shape[0], -1)
        if w.shape != h.shape:
            print(f"  {gg_name}: 形状 {w.shape} vs HF {h.shape}，跳过")
            continue
        idx, worst = block_match(w, h, axis, n, off, step)
        seg = {0: "", 2048: "（k 段）", 4096: "（v 段）"}.get(off, "")
        if "qkv" in gg_name and off == 0:
            seg = "（q 段）"
        if "conv1d" in gg_name:
            seg = "（v 通道）" if off == 4096 else "（q 通道）"
        ident = idx == list(range(n))
        same_p = (n == N_V) and idx == p
        verdict = "原顺序" if ident else ("按 p 重排" if same_p else f"其他顺序 {idx}")
        print(f"  {gg_name:28s}{seg:8s} {verdict:10s}  最差块相关 {worst:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""阶段 0 核对：从 GGUF 里真实解码两个张量，和已缓存的 HF BF16 原版逐元素比对。

一次确认四件事：
  1. 张量名对应关系对不对（blk.3.attn_q ↔ layers.3.self_attn.q_proj，blk.0.ffn_down ↔ layers.0.mlp.down_proj）
  2. 形状方向对不对（GGUF 维度顺序反转成行优先之后，能否与 HF 的 [行, 列] 逐元素对齐）
  3. gguf.quants.dequantize 的解码结果对不对
  4. 真实 Q4_K / Q6_K 相对 BF16 的误差有多大（此前 U5 用的是自写模拟）

用法：
  uv run --no-project --with gguf --with numpy python scripts/verify_gguf_decode.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
GGUF = ROOT / "data" / "gguf" / "Qwen3.5-9B-Q4_K_M.gguf"
CACHE = ROOT / "data" / "cache"

PAIRS = [
    ("blk.3.attn_q.weight", CACHE / "Llayers_3_self_attn_q_proj.bf16", (8192, 4096)),
    ("blk.0.ffn_down.weight", CACHE / "L0_down_proj.bf16", (4096, 12288)),
]


def load_bf16(path: Path, shape) -> np.ndarray:
    u16 = np.frombuffer(path.read_bytes(), dtype="<u2")
    return (u16.astype(np.uint32) << 16).view(np.float32).reshape(shape)


def main() -> int:
    from gguf import GGUFReader, GGMLQuantizationType
    from gguf.quants import dequantize

    # 先确认这个文件用到的 5 种格式都能解
    print("== dequantize 支持检查")
    for q in ("F32", "Q4_K", "Q5_K", "Q6_K", "Q8_0"):
        qt = GGMLQuantizationType[q]
        try:
            if q == "F32":
                ok = True
            else:
                from gguf.constants import GGML_QUANT_SIZES
                block, nbytes = GGML_QUANT_SIZES[qt]
                dequantize(np.zeros(nbytes, dtype=np.uint8), qt)
                ok = True
        except Exception as exc:  # noqa: BLE001
            ok = f"失败: {type(exc).__name__}: {exc}"
        print(f"  {q:5s} {ok}")
    print()

    reader = GGUFReader(str(GGUF), "r")
    by_name = {t.name: t for t in reader.tensors}

    for gname, bf16_path, hf_shape in PAIRS:
        t = by_name[gname]
        t0 = time.time()
        w_q = dequantize(t.data, t.tensor_type).astype(np.float32)
        dt = time.time() - t0
        w_ref = load_bf16(bf16_path, hf_shape)

        print(f"== {gname}  ({t.tensor_type.name})")
        print(f"  GGUF 解码形状 {w_q.shape}   HF 形状 {w_ref.shape}   解码 {dt:.1f}s")
        if w_q.shape != w_ref.shape:
            if w_q.T.shape == w_ref.shape:
                print("  形状是转置关系，按转置比对")
                w_q = w_q.T
            else:
                print("  形状对不上，停止")
                continue

        d = (w_q - w_ref).astype(np.float64)
        sigma = float(np.sqrt((w_ref.astype(np.float64) ** 2).mean()))
        corr = float(np.corrcoef(w_q.ravel()[::7], w_ref.ravel()[::7])[0, 1])
        print(f"  逐元素相关系数   {corr:.6f}")
        print(f"  误差均方根 / σ   {np.sqrt((d ** 2).mean()) / sigma * 100:.2f} %")
        print(f"  最大绝对误差     {np.abs(d).max():.5f}   （σ = {sigma:.5f}）")
        # 如果名字对应错了，相关系数会接近 0；如果行列顺序错了，也会接近 0
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

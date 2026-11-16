"""同一个张量：BF16 原版 vs GGUF 量化版，池化图逐格对比。

要回答两件事：
  1. 量化会不会改变池化图的形态（也就是玻璃里看到的东西）
  2. 池化图上那些"块状明暗"，是真实权重结构，还是量化 scale 的伪影
     （Q4_K / Q5_K / Q6_K 每 256 个元素共享一个 scale，格子和量化块不同对齐时，
      格与格之间的 scale 差异会直接表现成明暗）

两张缓存的 BF16 原版：
  data/cache/L0_down_proj.bf16             (4096, 12288)  对应 blk.0.ffn_down.weight
  data/cache/Llayers_3_self_attn_q_proj.bf16 (8192, 4096) 对应 blk.3.attn_q.weight

用法：
  uv run --no-project --with gguf --with numpy --with matplotlib python scripts/compare_quant_visual.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
GGUF = ROOT / "data" / "gguf" / "Qwen3.5-9B-Q4_K_M.gguf"
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "out" / "fig"

NX, NY, NZ = 19, 22, 250
SEED = 20261116

PAIRS = [
    ("L0 ffn_down", "blk.0.ffn_down.weight", CACHE / "L0_down_proj.bf16", (4096, 12288)),
    ("L3 attn_q", "blk.3.attn_q.weight", CACHE / "Llayers_3_self_attn_q_proj.bf16", (8192, 4096)),
]


def load_bf16(path: Path, shape) -> np.ndarray:
    u16 = np.frombuffer(path.read_bytes(), dtype="<u2")
    return np.ascontiguousarray(((u16.astype(np.uint32) << 16).view(np.float32)).reshape(shape))


def group_bounds(n: int, m: int) -> np.ndarray:
    return np.round(np.linspace(0, n, m + 1)).astype(int)


def pool(w: np.ndarray, rb: np.ndarray, cb: np.ndarray, signed: bool) -> np.ndarray:
    a = w if signed else np.abs(w)
    s = np.add.reduceat(a, rb[:-1], axis=0) / np.diff(rb)[:, None]
    s = np.add.reduceat(s, cb[:-1], axis=1) / np.diff(cb)[None, :]
    return s.astype(np.float64)


def unit(v: np.ndarray) -> np.ndarray:
    return np.clip(v / max(np.percentile(v, 99.5), 1e-30), 0, 1)


def main() -> int:
    from gguf import GGUFReader
    from gguf.quants import dequantize
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    reader = GGUFReader(str(GGUF), "r")
    by_name = {t.name: t for t in reader.tensors}
    OUT.mkdir(parents=True, exist_ok=True)

    for title, gname, bf16_path, shape in PAIRS:
        if not bf16_path.exists():
            print(f"缺少缓存 {bf16_path}，跳过 {title}")
            continue
        wb = load_bf16(bf16_path, shape)
        t = by_name[gname]
        wq = dequantize(t.data, t.tensor_type).astype(np.float32)
        if wq.ndim == 1:
            wq = wq.reshape(list(reversed([int(x) for x in t.shape])))

        nr, nc = NX * NY, NZ
        rb, cb = group_bounds(shape[0], nr), group_bounds(shape[1], nc)
        ab = pool(wb, rb, cb, signed=False)
        aq = pool(wq, rb, cb, signed=False)
        sb = pool(wb, rb, cb, signed=True)
        sq = pool(wq, rb, cb, signed=True)

        corr_abs = float(np.corrcoef(ab.ravel(), aq.ravel())[0, 1])
        corr_sig = float(np.corrcoef(sb.ravel(), sq.ravel())[0, 1])
        cv_b, cv_q = ab.std() / ab.mean(), aq.std() / aq.mean()
        wpv = shape[0] * shape[1] / (nr * nc)
        cv_n = float(np.sqrt(np.pi / 2 - 1) / np.sqrt(wpv))

        print(f"== {title}  ({gname}, {t.tensor_type.name})")
        print(f"  |W| 池化：BF16 CV {cv_b:.3f}   量化 CV {cv_q:.3f}   纯噪声 {cv_n:.3f}   逐格相关系数 {corr_abs:.5f}")
        print(f"  signed 池化：逐格相关系数 {corr_sig:.5f}   BF16 标准差 {sb.std():.3e}   量化标准差 {sq.std():.3e}")
        ratio = ab / np.maximum(aq, 1e-30)
        print(f"  |W| 比值 BF16/量化：中位 {np.median(ratio):.3f}  10%分位 {np.percentile(ratio,10):.3f}  "
              f"90%分位 {np.percentile(ratio,90):.3f}")
        print()

        fig, axs = plt.subplots(2, 3, figsize=(15.5, 9.6))
        rows = [("abs", ab, aq, "|W| pooled"),
                ("signed", sb, sq, "signed pooled")]
        for r, (_, vb, vq, label) in enumerate(rows):
            lo, hi = min(vb.min(), vq.min()), max(vb.max(), vq.max())
            im = axs[r][0].imshow(vb, aspect="auto", origin="lower", cmap="gray",
                                  vmin=lo, vmax=hi, interpolation="nearest")
            axs[r][0].set_title(f"{label} · BF16", fontsize=10)
            fig.colorbar(im, ax=axs[r][0], fraction=0.046)
            im = axs[r][1].imshow(vq, aspect="auto", origin="lower", cmap="gray",
                                  vmin=lo, vmax=hi, interpolation="nearest")
            axs[r][1].set_title(f"{label} · {t.tensor_type.name}  (same scale)", fontsize=10)
            fig.colorbar(im, ax=axs[r][1], fraction=0.046)
            d = vq - vb
            lim = np.percentile(np.abs(d), 99.5)
            im = axs[r][2].imshow(d, aspect="auto", origin="lower", cmap="coolwarm",
                                  vmin=-lim, vmax=lim, interpolation="nearest")
            axs[r][2].set_title("quant - BF16  (same units)", fontsize=10)
            fig.colorbar(im, ax=axs[r][2], fraction=0.046)
            for cx in axs[r]:
                cx.set_xlabel("col group -> z")
                cx.set_ylabel("row group -> (x, y)")
        fig.suptitle(f"{title}  {shape[0]} x {shape[1]} -> {nr} x {nc}   "
                     f"corr(abs) {corr_abs:.5f}  corr(signed) {corr_sig:.5f}   "
                     f"CV bf16 {cv_b:.3f} / quant {cv_q:.3f} / noise {cv_n:.3f}", fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        p = OUT / f"quant_vs_bf16_{gname.replace('.', '_')}.png"
        fig.savefig(p, dpi=130)
        plt.close(fig)
        print(f"图 {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

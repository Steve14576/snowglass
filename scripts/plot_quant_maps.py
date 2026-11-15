"""把任意一个二维权重的 BF16 / Q8 / Q4 可视化并排画出来。

三行：
  行 1  池化后的 |w| 灰度图（0-255）
  行 2  按点概率采样出来的点图（水晶里真正会看到的东西）
  行 3  8-bit 差值图 + 差值直方图

权重缓存在 data/cache/，第二次跑不再下载。只 Range 取目标张量，不下载整个 shard。

用法：
  uv run --no-project --with numpy --with matplotlib python scripts/plot_quant_maps.py
  uv run --no-project --with numpy --with matplotlib python scripts/plot_quant_maps.py ^
      --tensor model.language_model.layers.3.self_attn.q_proj.weight
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_quant_visibility as qv  # 复用已验证的取数与量化实现

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "out" / "fig"
DEFAULT_TENSOR = "model.language_model.layers.0.mlp.down_proj.weight"


def sanitize(name: str) -> str:
    s = name.replace("model.language_model.", "L").replace(".weight", "")
    return s.replace(".", "_")


def resolve(tensor: str) -> tuple[str, list[int]]:
    raw = qv.fetch_range(qv.BASE + "model.safetensors.index.json", 0, 50_000_000)
    wmap = json.loads(raw)["weight_map"]
    if tensor not in wmap:
        near = [k for k in wmap if tensor.split(".")[-3] in k][:10]
        raise KeyError(f"{tensor} 不在此仓库；相近候选: {near}")
    return wmap[tensor], None  # type: ignore[return-value]


def load_tensor(tensor: str) -> tuple[np.ndarray, str]:
    CACHE.mkdir(parents=True, exist_ok=True)
    tag = sanitize(tensor)
    f = CACHE / f"{tag}.bf16"

    raw = qv.fetch_range(qv.BASE + "model.safetensors.index.json", 0, 50_000_000)
    shard = json.loads(raw)["weight_map"][tensor]
    url = qv.BASE + shard
    hdr, hlen = qv.read_header(url)
    meta = hdr[tensor]
    shape = tuple(meta["shape"])
    begin, end = meta["data_offsets"]
    nbytes = end - begin

    if f.exists() and f.stat().st_size == nbytes:
        print(f"cache hit : {f.name}  ({nbytes/1e6:.1f} MB)")
        buf = f.read_bytes()
    else:
        print(f"fetch     : {tensor}")
        print(f"            shard={shard}  shape={shape}  dtype={meta['dtype']}  {nbytes/1e6:.1f} MB")
        buf = qv.fetch_range(url, 8 + hlen + begin, 8 + hlen + end - 1)
        f.write_bytes(buf)
        print(f"            cached -> {f}")

    if meta["dtype"] != "BF16":
        raise NotImplementedError(f"暂只处理 BF16，实得 {meta['dtype']}")
    u16 = np.frombuffer(buf, dtype="<u2")
    w = (u16.astype(np.uint32) << 16).view(np.float32)
    return np.ascontiguousarray(w.reshape(shape)), tag


def sample_dots(p: np.ndarray, total: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = rng.poisson(p / p.sum() * total)
    yy, xx = np.nonzero(n)
    reps = n[yy, xx]
    yy = np.repeat(yy, reps)
    xx = np.repeat(xx, reps)
    jit = rng.random((yy.size, 2)) - 0.5
    return np.column_stack([xx + jit[:, 0], yy + jit[:, 1]])


def main(argv: list[str]) -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    tensor = DEFAULT_TENSOR
    if "--tensor" in argv:
        tensor = argv[argv.index("--tensor") + 1]

    OUT.mkdir(parents=True, exist_ok=True)
    w, tag = load_tensor(tensor)
    if w.ndim != 2:
        raise ValueError(f"需要二维张量，实得 shape={w.shape}")

    w8 = qv.block_quantize(w, 8)
    w4 = qv.block_quantize(w, 4)
    variants = [("BF16 (original)", w), ("Q8 simulated", w8), ("Q4 simulated", w4)]

    grays, probs, amaps = [], [], []
    for _, src in variants:
        am = qv.pool_absmean(src, qv.POOL)
        g = qv.to_gray(qv.normalize(am))
        amaps.append(am)
        grays.append(g)
        probs.append(qv.to_prob(g))

    fig = plt.figure(figsize=(15, 13.5), facecolor="#101012")
    gs = fig.add_gridspec(3, 3, hspace=0.28, wspace=0.12,
                          left=0.04, right=0.97, top=0.93, bottom=0.05)

    def style(ax, title, sub=""):
        ax.set_facecolor("#000000")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(title, color="#e8e8e8", fontsize=12, pad=8)
        if sub:
            ax.set_xlabel(sub, color="#8a8a8a", fontsize=9, labelpad=4)

    for j, (name, _) in enumerate(variants):
        ax = fig.add_subplot(gs[0, j])
        ax.imshow(grays[j], cmap="gray", vmin=0, vmax=255, interpolation="nearest")
        style(ax, name, "pooled |w|, 8-bit gray")

    TOTAL = 6000
    for j, (name, _) in enumerate(variants):
        ax = fig.add_subplot(gs[1, j])
        d = sample_dots(probs[j], TOTAL, seed=7)
        ax.scatter(d[:, 0], d[:, 1], s=2.0, c="#ffffff", alpha=0.75,
                   linewidths=0, marker="s")
        ax.set_xlim(-0.5, qv.POOL - 0.5)
        ax.set_ylim(qv.POOL - 0.5, -0.5)
        style(ax, name, f"dots sampled at p (n={TOTAL})")

    d8 = grays[1].astype(int) - grays[0].astype(int)
    d4 = grays[2].astype(int) - grays[0].astype(int)
    vmax = max(abs(d8).max(), abs(d4).max(), 1)
    cmap = LinearSegmentedColormap.from_list("bwr0", ["#2b6cb0", "#101012", "#e04b4b"])

    for j, (dd, name) in enumerate([(d8, "Q8 - BF16"), (d4, "Q4 - BF16")]):
        ax = fig.add_subplot(gs[2, j])
        im = ax.imshow(dd, cmap=cmap, vmin=-vmax, vmax=vmax, interpolation="nearest")
        style(ax, name, f"8-bit levels, L1={np.abs(dd).mean():.2f}, max={np.abs(dd).max()}")
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
        cb.ax.tick_params(colors="#aaa", labelsize=8)

    ax = fig.add_subplot(gs[2, 2])
    ax.set_facecolor("#101012")
    bins = np.arange(-20.5, 21.5, 1)
    ax.hist(d8.ravel(), bins=bins, color="#2b6cb0", alpha=0.85, label="Q8 - BF16")
    ax.hist(d4.ravel(), bins=bins, color="#e04b4b", alpha=0.6, label="Q4 - BF16")
    ax.set_yscale("log")
    ax.tick_params(colors="#aaa", labelsize=8)
    for s in ax.spines.values():
        s.set_color("#333")
    ax.set_title("distribution of difference", color="#e8e8e8", fontsize=12, pad=8)
    ax.set_xlabel("gray levels", color="#8a8a8a", fontsize=9)
    ax.legend(fontsize=8, facecolor="#18181a", edgecolor="#333", labelcolor="#ccc")

    fig.suptitle(
        f"Qwen3.5-9B  ·  {tensor.split('language_model.')[-1]}  ·  {w.shape[0]}x{w.shape[1]}"
        f"  ·  pooled to {qv.POOL}x{qv.POOL}  ·  gamma={qv.GAMMA} floor={qv.FLOOR}",
        color="#f0f0f0", fontsize=13, y=0.965)

    out = OUT / f"quant_visibility_{tag}.png"
    fig.savefig(out, dpi=130, facecolor=fig.get_facecolor())
    print(f"wrote     : {out}  ({out.stat().st_size/1e6:.2f} MB)")

    print()
    print(f"{'variant':16s} {'L1':>6s} {'max':>4s} {'corr':>8s} {'dp/p':>7s} "
          f"{'resid_rms/std':>14s} {'autocorr x/y':>14s}")
    for j, (name, _) in enumerate(variants[1:], start=1):
        g, g0 = grays[j], grays[0]
        dl1 = float(np.abs(g.astype(int) - g0.astype(int)).mean())
        dmax = int(np.abs(g.astype(int) - g0.astype(int)).max())
        corr = float(np.corrcoef(g.ravel(), g0.ravel())[0, 1])
        dp = float(np.abs(probs[j] - probs[0]).mean() / max(probs[0].mean(), 1e-9))
        r = amaps[j] - amaps[0]
        rr = float(np.sqrt((r ** 2).mean()) / max(amaps[0].std(), 1e-30))

        def ac(a, lag, axis):
            x = a - a.mean()
            y = np.roll(x, lag, axis=axis)
            d = float((x * x).sum())
            return float((x * y).sum() / d) if d else 0.0

        print(f"{name:16s} {dl1:6.2f} {dmax:4d} {corr:8.6f} {dp*100:6.2f}% "
              f"{rr:14.3f} {ac(r,1,1):+7.3f}/{ac(r,1,0):+.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

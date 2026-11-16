"""阶段 2 第一块：拿一个真实权重块跑通 谱分解 → 池化 → 灰度 → 出图。

只回答一个问题：真实权重的点云，配上谱分解和池化，看上去是什么形态；它有没有方向性，
以及谱分解到底带来了什么。不做任何观感上的取舍，也不改布局。

流程（D4 / D10 / D13）：
  1. 从 GGUF 解码一个张量的真实权重（Q4_K / Q6_K），不做任何分位拉伸
  2. 池化：行按 nx*ny 分组、列按 nz 分组，每格取 |w| 的均值（幅值能量）
  3. 在池化矩阵上做随机化 SVD（2 次幂迭代），用 MP 噪声上界 s+ = σ(√m+√n) 定界外个数 k
     W_struct = 前 k 个奇异方向的重构；W_res = W - W_struct
  4. 三种灰度：raw（|W| 相对均值）、struct（|W_struct|）、res（|W_res|），外加一个合成
  5. 出图：池化矩阵四联 + 三维灰度体的三视图和点云

网格默认 19 × 22 × 250，是"块宽 1.5 × 块厚 1.8 × 块长 20 mm 在 0.08 mm 点距下的格子数"，
即 L28.v 那个块的真实格子数；别的块尺寸不同，等 layout.json 出来后按块逐个替换。

用法：
  uv run --no-project --with gguf --with numpy --with matplotlib python scripts/try_one_block.py
  uv run ... python scripts/try_one_block.py --tensor blk.3.attn_q.weight --nx 19 --ny 22 --nz 250
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
GGUF = ROOT / "data" / "gguf" / "Qwen3.5-9B-Q4_K_M.gguf"
OUT_FIG = ROOT / "out" / "fig"
OUT_DATA = ROOT / "out" / "blocks"

GAMMA = 2.4
FLOOR = 0.03
SEED = 20261116
K_MAX = 64


def group_bounds(n: int, m: int) -> np.ndarray:
    """把 n 个元素分成 m 组，返回 m+1 个边界（严格递增，允许不整除）。"""
    b = np.round(np.linspace(0, n, m + 1)).astype(int)
    if len(np.unique(b)) != m + 1:
        raise ValueError(f"分组边界有重复：n={n} m={m}")
    return b


def pool_absmean(w: np.ndarray, rb: np.ndarray, cb: np.ndarray) -> np.ndarray:
    """先按行分组平均，再按列分组平均。每格是 |w| 的均值。"""
    a = np.abs(w)
    s = np.add.reduceat(a, rb[:-1], axis=0) / np.diff(rb)[:, None]
    s = np.add.reduceat(s, cb[:-1], axis=1) / np.diff(cb)[None, :]
    return s.astype(np.float64)


def pool_signed(w: np.ndarray, rb: np.ndarray, cb: np.ndarray) -> np.ndarray:
    """带符号的均值。abs 平均会把系统性的正负结构抹成常数，这一路保留符号。"""
    s = np.add.reduceat(w, rb[:-1], axis=0) / np.diff(rb)[:, None]
    s = np.add.reduceat(s, cb[:-1], axis=1) / np.diff(cb)[None, :]
    return s.astype(np.float64)


def grouped_rms(v: np.ndarray, b: np.ndarray) -> np.ndarray:
    """一维数组按边界分组求均方根。"""
    s = np.add.reduceat(v.astype(np.float64) ** 2, b[:-1]) / np.diff(b)
    return np.sqrt(s)


def randomized_svd(w: np.ndarray, k: int, seed: int, power: int = 2):
    rng = np.random.default_rng(seed)
    n = w.shape[1]
    p = min(k + 10, min(w.shape))
    omega = rng.standard_normal((n, p)).astype(np.float32)
    y = w @ omega
    for _ in range(power):
        y, _ = np.linalg.qr(y)
        y = w @ (w.T @ y)
    q, _ = np.linalg.qr(y)
    b = q.T @ w
    ub, s, vt = np.linalg.svd(b.astype(np.float64), full_matrices=False)
    u = (q.astype(np.float64) @ ub)[:, :k]
    return u, s, vt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tensor", default="blk.0.ffn_down.weight")
    ap.add_argument("--nx", type=int, default=19)
    ap.add_argument("--ny", type=int, default=22)
    ap.add_argument("--nz", type=int, default=250)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    from gguf import GGUFReader
    from gguf.quants import dequantize

    reader = GGUFReader(str(GGUF), "r")
    by_name = {t.name: t for t in reader.tensors}
    if args.tensor not in by_name:
        print("没有这个张量：", args.tensor)
        return 1
    t = by_name[args.tensor]

    t0 = time.time()
    w = dequantize(t.data, t.tensor_type).astype(np.float32)
    if w.ndim == 1:
        w = w.reshape([int(x) for x in reversed(list(t.shape))])
    print(f"{args.tensor}  {t.tensor_type.name}  形状 {w.shape}  解码 {time.time()-t0:.1f}s")
    R, C = w.shape

    nr, nc = args.nx * args.ny, args.nz
    rb, cb = group_bounds(R, nr), group_bounds(C, nc)
    print(f"池化 {R}x{C} -> {nr}x{nc}（每格平均覆盖 {R/nr:.1f} 行 x {C/nc:.1f} 列，"
          f"即 {R*C/(nr*nc):.0f} 个权重）")
    t0 = time.time()
    ww = pool_absmean(w, rb, cb)
    print(f"池化用时 {time.time()-t0:.1f}s，均值 {ww.mean():.5g}，CV {ww.std()/ww.mean():.3f}")

    # 纯噪声参照：同样格子数、同样均值的随机高斯，它的池化图 CV 理论上约为 sqrt(pi/2-1)/sqrt(wpv)
    wpv = R * C / (nr * nc)
    cv_noise = float(np.sqrt(np.pi / 2 - 1) / np.sqrt(wpv))
    print(f"纯噪声参照 CV = {cv_noise:.4f}（每格 {wpv:.0f} 个权重）")

    # 带符号均值：随机部分应自行抵消，系统结构留下来
    ws = pool_signed(w, rb, cb)
    cv_signed = float(ws.std() / max(w.mean() ** 2, 1e-30) ** 0.5)
    print(f"signed 池化：均值 {ws.mean():.6g}，标准差 {ws.std():.6g}，"
          f"按元素标准差归一后的 CV {ws.std()/w.std():.4f}（噪声参照 {1/np.sqrt(wpv):.4f}）")

    # 行 / 列范数（D10 的另一半）：直接回答哪些行、哪些列整体更强，不需要 SVD
    row_rms = grouped_rms(np.sqrt((w.astype(np.float64) ** 2).mean(axis=1)), rb)
    col_rms = grouped_rms(np.sqrt((w.astype(np.float64) ** 2).mean(axis=0)), cb)
    print(f"行范数：min {row_rms.min():.4g}  中位 {np.median(row_rms):.4g}  max {row_rms.max():.4g}  "
          f"max/中位 {row_rms.max()/np.median(row_rms):.2f}")
    print(f"列范数：min {col_rms.min():.4g}  中位 {np.median(col_rms):.4g}  max {col_rms.max():.4g}  "
          f"max/中位 {col_rms.max()/np.median(col_rms):.2f}")
    # 外积近似：行强度 x 列强度，归一化成与 |w| 同量纲
    outer = np.outer(row_rms, col_rms)
    outer *= ww.mean() / outer.mean()

    t0 = time.time()
    # 谱分解在 signed 池化图上做：abs 图上每格非负，谱分解必然只抓到常数
    u, s, vt = randomized_svd(ws.astype(np.float32), K_MAX, SEED, power=2)
    m, n = ws.shape
    s_plus = float(np.sqrt((ws ** 2).mean()) * (np.sqrt(m) + np.sqrt(n)))
    k_out = int((s > s_plus).sum())
    print(f"SVD（signed）用时 {time.time()-t0:.1f}s  s+ = {s_plus:.5f}  界外个数 k = {k_out}（取前 {K_MAX} 个）")
    print("  前 8 个奇异值：", " ".join(f"{v:.4f}" for v in s[:8]))

    sel = max(k_out, 1)
    w_struct = (u[:, :sel] * s[:sel]) @ vt[:sel]
    w_res = ws - w_struct
    e_struct = float((w_struct ** 2).sum() / max((ws ** 2).sum(), 1e-30))
    print(f"结构部分能量占比 {e_struct*100:.1f} %")

    # ---- 灰度：均不做分位拉伸，只按本图 99.5 分位归一成 0..1 ----
    def unit(v: np.ndarray) -> np.ndarray:
        return np.clip(v / max(np.percentile(v, 99.5), 1e-30), 0, 1)

    g_abs = unit(ww)                      # 格内 |w| 均值（第一版用的）
    g_signed = unit(np.abs(ws))           # 带符号均值，取绝对值看
    g_outer = unit(outer)                 # 行范数 x 列范数
    g_outres = unit(np.abs(ww - outer))    # abs 图减掉外积之后的残差
    g_comb = 0.5 * g_outer + 0.5 * g_outres

    def p_of(g):
        return FLOOR + (1 - FLOOR) * np.power(g, GAMMA)

    print("平均灰度与平均有点率（gamma 2.4 / floor 3%）：")
    for name, g in (("abs", g_abs), ("signed", g_signed), ("outer", g_outer),
                    ("outer-res", g_outres), ("comb", g_comb)):
        print(f"  {name:9s} 灰度均值 {g.mean():.3f}   有点率 {p_of(g).mean():.3f}")

    # ---- 存灰度体 ----
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    stem = args.tag or args.tensor.replace(".", "_")
    np.savez_compressed(OUT_DATA / f"{stem}.gray.npz",
                        g_abs=g_abs.reshape(args.nx, args.ny, args.nz),
                        g_signed=g_signed.reshape(args.nx, args.ny, args.nz),
                        g_outer=g_outer.reshape(args.nx, args.ny, args.nz),
                        g_outres=g_outres.reshape(args.nx, args.ny, args.nz),
                        g_comb=g_comb.reshape(args.nx, args.ny, args.nz),
                        grid=np.array([args.nx, args.ny, args.nz]),
                        k=np.array([k_out]), s=s, s_plus=np.array([s_plus]),
                        tensor=np.array([args.tensor]))
    print(f"写到 {OUT_DATA / f'{stem}.gray.npz'}")

    # ---- 出图 ----
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT_FIG.mkdir(parents=True, exist_ok=True)
    fig, axs = plt.subplots(1, 5, figsize=(21, 7.4))
    panels = [("|W| pooled  (abs mean)", ww / ww.mean(), "in units of the tensor mean |w|"),
              ("|signed pooled|  (mean of w)", np.abs(ws), "in original weight units"),
              ("row_rms x col_rms", outer / ww.mean(), "in units of mean |w|"),
              ("|abs - outer|", np.abs(ww - outer) / ww.mean(), "in units of mean |w|"),
              ("gray: 0.5 outer + 0.5 res", g_comb, "0..1")]
    for ax, (title, arr, unit) in zip(axs, panels):
        im = ax.imshow(arr, aspect="auto", origin="lower", cmap="gray", interpolation="nearest")
        ax.set_title(f"{title}\n{unit}", fontsize=10)
        ax.set_xlabel("col group -> z (block length)")
        ax.set_ylabel("row group -> (x, y)")
        fig.colorbar(im, ax=ax, fraction=0.046)
    fig.suptitle(f"{args.tensor}  [{R} x {C}] -> pooled {m} x {n}  "
                 f"CV={ww.std()/ww.mean():.3f} (pure-noise {cv_noise:.3f})  k={k_out}  "
                 f"struct energy {e_struct*100:.1f}%", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    p1 = OUT_FIG / f"{stem}_pooled.png"
    fig.savefig(p1, dpi=130)
    plt.close(fig)
    print(f"图 {p1}")

    # 三维灰度体：三视图投影 + 点云
    g3 = g_comb.reshape(args.nx, args.ny, args.nz)
    p3 = p_of(g3)
    fig = plt.figure(figsize=(17, 5.6))
    views = [("front  sum over z", p3.sum(axis=2), "x", "y"),
             ("side   sum over y", p3.sum(axis=1).T, "z", "x"),
             ("top    sum over x", p3.sum(axis=0).T, "z", "y")]
    for i, (title, arr, xa, ya) in enumerate(views):
        ax = fig.add_subplot(1, 4, i + 1)
        im = ax.imshow(arr, aspect="auto", origin="lower", cmap="gray", interpolation="nearest")
        ax.set_title(title, fontsize=10)
        ax.set_xlabel(xa); ax.set_ylabel(ya)
        fig.colorbar(im, ax=ax, fraction=0.046)
    ax = fig.add_subplot(1, 4, 4, projection="3d")
    rng = np.random.default_rng(SEED)
    ix, iy, iz = np.meshgrid(np.arange(args.nx), np.arange(args.ny), np.arange(args.nz), indexing="ij")
    prob = p3.ravel()
    pick = rng.random(prob.size) < prob
    n_pick = int(pick.sum())
    step = max(1, n_pick // 20000)
    idx = np.flatnonzero(pick)[::step]
    ax.scatter(ix.ravel()[idx], iz.ravel()[idx], iy.ravel()[idx],
               c=g3.ravel()[idx], cmap="gray", s=0.6, linewidths=0, vmin=0, vmax=1)
    ax.set_xlabel("x"); ax.set_ylabel("z (block length)"); ax.set_zlabel("y")
    ax.set_title(f"3D points (p={p3.mean():.2f}, {len(idx)} of {n_pick} shown)", fontsize=10)
    ax.view_init(elev=18, azim=-72)
    fig.suptitle(f"{args.tensor}  block grid {args.nx} x {args.ny} x {args.nz}  "
                 f"(gray = 0.6 struct + 0.4 res, gamma {GAMMA}, floor {FLOOR})", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    p2 = OUT_FIG / f"{stem}_views.png"
    fig.savefig(p2, dpi=130)
    plt.close(fig)
    print(f"图 {p2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

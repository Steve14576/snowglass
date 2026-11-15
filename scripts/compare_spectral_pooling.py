"""回答一个问题：不用谱分解区分主次，直接降采样，和一个"实心雪花块"有什么区别？

对照三行：
  行 1  L0 mlp.down_proj   [4096 x 12288]   真实权重
  行 2  L3 self_attn.q_proj [8192 x 4096]   真实权重
  行 3  纯随机高斯矩阵（与行 1 同形状、同 σ）—— 这就是"实心雪花块"的数学定义

五列：
  A  直接降采样 |w|，固定标尺（按本张量均值的相对偏离显示，三行共用同一标尺）
  B  直接降采样 |w|，按本张量 0.5%/99.5% 分位拉伸（目前管线用的做法）
  C  谱分解的"结构部分" W_struct（MP 噪声上界之外的奇异方向重构），单独拉伸
  D  谱分解的"残差部分" W - W_struct，固定标尺（与 A 同标尺）
  E  用 A 的灰度按 gamma/floor 采点 —— 玻璃里大致会看到的疏密

同时打印：池化图的变异系数 CV、纯噪声理论 CV、界外奇异值个数、结构部分的能量占比。

用法：
  uv run --no-project --with numpy --with matplotlib python scripts/compare_spectral_pooling.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "out" / "fig"

POOL = 100
K_MAX = 32
GAMMA = 2.4
FLOOR = 0.03
N_DOTS = 6000
SEED = 20261116

TENSORS = [
    ("L0 mlp.down_proj", CACHE / "L0_down_proj.bf16", (4096, 12288)),
    ("L3 self_attn.q_proj", CACHE / "Llayers_3_self_attn_q_proj.bf16", (8192, 4096)),
]


def load_bf16(path: Path, shape: tuple[int, int]) -> np.ndarray:
    u16 = np.frombuffer(path.read_bytes(), dtype="<u2")
    w = (u16.astype(np.uint32) << 16).view(np.float32)
    return np.ascontiguousarray(w.reshape(shape))


def pool_absmean(w: np.ndarray, size: int) -> np.ndarray:
    m, n = w.shape
    rows = np.linspace(0, m, size + 1).astype(int)
    cols = np.linspace(0, n, size + 1).astype(int)
    a = np.abs(w)
    out = np.empty((size, size), dtype=np.float64)
    cnt = np.diff(cols)
    for i in range(size):
        band = a[rows[i]:rows[i + 1]]
        out[i] = np.add.reduceat(band, cols[:-1], axis=1).sum(axis=0) / (band.shape[0] * cnt)
    return out


def randomized_svd(w: np.ndarray, k: int, seed: int, power: int = 2):
    """返回前 k 个奇异三元组。power iteration 2 次，保证前几个奇异值足够准。"""
    rng = np.random.default_rng(seed)
    m, n = w.shape
    p = k + 10
    omega = rng.standard_normal((n, p)).astype(np.float32)
    y = w @ omega
    for _ in range(power):
        y, _ = np.linalg.qr(y)
        y = w @ (w.T @ y)
    q, _ = np.linalg.qr(y)
    b = q.T @ w
    ub, s, vt = np.linalg.svd(b.astype(np.float64), full_matrices=False)
    u = (q.astype(np.float64) @ ub)[:, :k]
    return u.astype(np.float32), s[:k], vt[:k].astype(np.float32)


def analyse(name: str, w: np.ndarray, seed: int) -> dict:
    m, n = w.shape
    sigma = float(np.sqrt((w.astype(np.float64) ** 2).mean()))
    s_plus = sigma * (np.sqrt(m) + np.sqrt(n))          # MP 噪声上界（奇异值口径）
    u, s, vt = randomized_svd(w, K_MAX, seed)
    k = int((s > s_plus).sum())

    fro2 = float((w.astype(np.float64) ** 2).sum())
    energy = float((s[:k] ** 2).sum() / fro2) if k else 0.0

    if k:
        w_struct = (u[:, :k] * s[:k].astype(np.float32)) @ vt[:k]
    else:
        w_struct = np.zeros_like(w)
    w_res = w - w_struct

    full = pool_absmean(w, POOL)
    struct = pool_absmean(w_struct, POOL)
    res = pool_absmean(w_res, POOL)

    weights_per_voxel = (m / POOL) * (n / POOL)
    cv = float(full.std() / full.mean())
    cv_noise = float(np.sqrt(np.pi / 2 - 1) / np.sqrt(weights_per_voxel))

    print(f"{name}")
    print(f"  shape={m}x{n}  sigma={sigma:.5f}  MP 上界 s+={s_plus:.3f}")
    print(f"  前 8 个奇异值: {np.array2string(s[:8], precision=3, separator=', ')}")
    print(f"  界外个数 k={k}   结构部分能量占比={energy*100:.3f}%")
    print(f"  每体素 {weights_per_voxel:.0f} 个权重")
    print(f"  池化图 CV={cv*100:.2f}%   纯噪声理论 CV={cv_noise*100:.2f}%   比值={cv/cv_noise:.1f}x")
    rel = full / full.mean() - 1
    print(f"  相对均值偏离: p0.5={np.percentile(rel,0.5)*100:+.1f}%  p99.5={np.percentile(rel,99.5)*100:+.1f}%")
    print()
    return dict(name=name, full=full, struct=struct, res=res, k=k, energy=energy,
                cv=cv, cv_noise=cv_noise, wpv=weights_per_voxel)


def stretch(a: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(a, [0.5, 99.5])
    return np.clip((a - lo) / max(hi - lo, 1e-30), 0, 1)


def fixed(a: np.ndarray, ref_mean: float, half: float) -> np.ndarray:
    return np.clip((a / ref_mean - 1) / (2 * half) + 0.5, 0, 1)


def sample_dots(g01: np.ndarray, total: int, seed: int) -> np.ndarray:
    p = FLOOR + (1 - FLOOR) * g01 ** GAMMA
    rng = np.random.default_rng(seed)
    cnt = rng.poisson(p / p.sum() * total)
    yy, xx = np.nonzero(cnt)
    reps = cnt[yy, xx]
    yy, xx = np.repeat(yy, reps), np.repeat(xx, reps)
    j = rng.random((yy.size, 2)) - 0.5
    return np.column_stack([xx + j[:, 0], yy + j[:, 1]])


def setup_font() -> None:
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm

    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if Path(p).exists():
            fm.fontManager.addfont(p)
            plt.rcParams["font.family"] = fm.FontProperties(fname=p).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    setup_font()
    OUT.mkdir(parents=True, exist_ok=True)

    results = []
    for i, (name, path, shape) in enumerate(TENSORS):
        if not path.exists():
            print(f"缺缓存: {path}（先跑 scripts/plot_quant_maps.py 取数）")
            return 1
        results.append(analyse(name, load_bf16(path, shape), SEED + i))

    # 实心雪花块：与 down_proj 同形状、同 σ 的纯随机高斯
    m, n = TENSORS[0][2]
    sigma0 = float(np.sqrt((load_bf16(TENSORS[0][1], TENSORS[0][2]).astype(np.float64) ** 2).mean()))
    rng = np.random.default_rng(SEED + 99)
    w_rand = (rng.standard_normal((m, n), dtype=np.float32) * sigma0)
    results.append(analyse("纯随机高斯（实心雪花块）", w_rand, SEED + 7))
    del w_rand

    # 三行共用的固定标尺：取所有行里最大的相对偏离
    half = max(float(np.percentile(np.abs(r["full"] / r["full"].mean() - 1), 99.5)) for r in results)
    print(f"固定标尺：均值 ±{half*100:.1f}% 映射到 0..255（三行共用）")

    cols = ["A 直接降采样\n固定标尺", "B 直接降采样\n按分位拉伸（现管线）",
            "C 谱「结构」部分\n单独拉伸", "D 谱「残差」部分\n固定标尺", "E 按 A 采点\n玻璃里大致的疏密"]

    fig, axes = plt.subplots(3, 5, figsize=(19, 12.2), facecolor="#0e0f12")
    for r_i, r in enumerate(results):
        mu = r["full"].mean()
        imgs = [
            fixed(r["full"], mu, half),
            stretch(r["full"]),
            stretch(r["struct"]) if r["k"] else np.zeros_like(r["struct"]),
            fixed(r["res"], mu, half),
        ]
        for c_i in range(4):
            ax = axes[r_i, c_i]
            ax.imshow(imgs[c_i], cmap="gray", vmin=0, vmax=1, interpolation="nearest")
        ax = axes[r_i, 4]
        ax.set_facecolor("#000")
        d = sample_dots(imgs[0], N_DOTS, SEED + r_i)
        ax.scatter(d[:, 0], d[:, 1], s=1.6, c="#fff", alpha=0.8, linewidths=0, marker="s")
        ax.set_xlim(-0.5, POOL - 0.5)
        ax.set_ylim(POOL - 0.5, -0.5)

        for c_i in range(5):
            a = axes[r_i, c_i]
            a.set_xticks([])
            a.set_yticks([])
            for s in a.spines.values():
                s.set_color("#2a2e36")
            if r_i == 0:
                a.set_title(cols[c_i], color="#e6e9ef", fontsize=11, pad=8)

        axes[r_i, 0].set_ylabel(r["name"], color="#e6e9ef", fontsize=11, labelpad=10)
        info = (f"CV {r['cv']*100:.2f}%（纯噪声 {r['cv_noise']*100:.2f}%，{r['cv']/r['cv_noise']:.1f}×）")
        axes[r_i, 0].set_xlabel(info, color="#9aa3b2", fontsize=9)
        axes[r_i, 2].set_xlabel(
            f"界外方向 k={r['k']}，能量占比 {r['energy']*100:.2f}%" if r["k"] else "无界外方向",
            color="#d8b366", fontsize=9)
        axes[r_i, 1].set_xlabel("拉伸后连纯噪声也有明暗", color="#9aa3b2", fontsize=9)

    fig.suptitle("直接降采样 vs 谱分解 vs 实心雪花块（Qwen3.5-9B 真实 BF16 权重，池化到 100×100）",
                 color="#f2f4f8", fontsize=15, y=0.985)
    fig.subplots_adjust(left=0.05, right=0.99, top=0.92, bottom=0.04, wspace=0.06, hspace=0.22)
    out = OUT / "spectral_vs_pooling.png"
    fig.savefig(out, dpi=110, facecolor=fig.get_facecolor())
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

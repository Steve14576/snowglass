"""三种视觉语法的骨架对比图（假数据，只画结构）。

同一把尺：毛坯 25 x 25 x 80 mm，可雕区 20 x 20 x 65 mm，32 层，3 线性注意力 + 1 全注意力循环。
三张图都是正立面（前视），只表达"模块怎么摆、主干怎么走"，不表达内部雪花。

输出：out/fig/grammar_candidates.png
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402
from matplotlib.patches import Polygon, Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "fig"

LAYERS = 32
FULL_EVERY = 4          # 每 4 层一个全注意力
Y_EMBED = (0.8, 5.6)
Y_L0 = 6.4
LAYER_H = 1.62
Y_TOP = Y_L0 + LAYERS * LAYER_H
Y_HEAD = (Y_TOP + 0.8, Y_TOP + 5.6)

C_TRUNK = "#59657a"
C_GDN = "#3d78b8"
C_FULL = "#d08a33"
C_MLP = "#4e7d60"
C_END = "#8a6fa0"
C_EDGE = "#20242c"
C_BLANK = "#3a3f49"
C_TEXT = "#d8d8d8"
C_DIM = "#8a8a8a"


def setup_font() -> bool:
    cands = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ]
    for p in cands:
        if not Path(p).exists():
            continue
        try:
            fm.fontManager.addfont(p)
            name = fm.FontProperties(fname=p).get_name()
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


CJK = setup_font()


def L(cn: str, en: str) -> str:
    return cn if CJK else en


def blank(ax) -> None:
    """毛坯外框（虚线）+ 可雕区。"""
    ax.add_patch(Rectangle((-12.5, 0), 25, 80, fill=False, ls=(0, (4, 4)),
                           lw=0.9, ec=C_BLANK))
    ax.add_patch(Rectangle((-10, 7.5), 20, 65, fill=False, lw=0.6, ec="#2b3038"))
    ax.text(0, 81.5, L("毛坯 25x25x80  ·  可雕区 20x20x65",
                       "blank 25x25x80  carve 20x20x65"),
            ha="center", va="bottom", fontsize=7.5, color=C_DIM)
    ax.set_xlim(-14, 14)
    ax.set_ylim(-3, 86)
    ax.set_aspect("equal")
    ax.axis("off")


def ends(ax) -> None:
    """embed 与 lm_head：两端对称的源与河口。"""
    ax.add_patch(Polygon([(-9.5, Y_EMBED[0]), (9.5, Y_EMBED[0]),
                          (6.0, Y_EMBED[1]), (-6.0, Y_EMBED[1])],
                         closed=True, fc=C_END, ec=C_EDGE, lw=0.6, alpha=0.85))
    ax.text(0, (Y_EMBED[0] + Y_EMBED[1]) / 2, L("embed\n248320x4096", "embed"),
            ha="center", va="center", fontsize=7, color="#f0e8f6")
    ax.add_patch(Polygon([(-6.0, Y_HEAD[0]), (6.0, Y_HEAD[0]),
                          (9.5, Y_HEAD[1]), (-9.5, Y_HEAD[1])],
                         closed=True, fc=C_END, ec=C_EDGE, lw=0.6, alpha=0.85))
    ax.text(0, (Y_HEAD[0] + Y_HEAD[1]) / 2, L("lm_head", "lm_head"),
            ha="center", va="center", fontsize=7, color="#f0e8f6")


def layer_y(i: int) -> float:
    return Y_L0 + (LAYERS - 1 - i) * LAYER_H


def is_full(i: int) -> bool:
    return i % FULL_EVERY == FULL_EVERY - 1


# ---------------------------------------------------------------- A 脊柱
def draw_spine(ax) -> None:
    blank(ax)
    ends(ax)
    # 主干：贯穿全长，直径恒定
    ax.add_patch(Rectangle((-1.5, Y_EMBED[1]), 3.0, Y_HEAD[0] - Y_EMBED[1],
                           fc=C_TRUNK, ec=C_EDGE, lw=0.5, alpha=0.9))
    ax.text(0, (Y_HEAD[0] + Y_EMBED[1]) / 2, L("残差主干", "residual stream"),
            ha="center", va="center", fontsize=7.2, color="#e8edf6", rotation=90)

    for i in range(LAYERS):
        y = layer_y(i)
        full = is_full(i)
        # 注意力：横向伸展的翼，宽度 = 它能跨多远
        w_att = 6.2 if full else 3.4
        ax.add_patch(Rectangle((-1.5 - w_att, y - LAYER_H * 0.36), w_att,
                               LAYER_H * 0.72,
                               fc=C_FULL if full else C_GDN, ec=C_EDGE, lw=0.4,
                               alpha=0.9))
        # MLP：轴向外挂的囊，体积 ∝ intermediate/hidden
        ax.add_patch(Rectangle((1.5, y - LAYER_H * 0.40), 5.0, LAYER_H * 0.80,
                               fc=C_MLP, ec=C_EDGE, lw=0.4, alpha=0.9))
        # 两个注入点
        for s in (-1, 1):
            ax.plot([s * 1.5], [y], marker="o", ms=2.2, color="#f2f6ff", zorder=5)


# ---------------------------------------------------------------- B 一摞切片
def draw_slices(ax) -> None:
    blank(ax)
    ends(ax)
    for i in range(LAYERS):
        y = layer_y(i)
        full = is_full(i)
        w_att = 9.0 if full else 5.2
        gap = 0.5
        ax.add_patch(Rectangle((-9.0, y - LAYER_H * 0.42), w_att, LAYER_H * 0.84,
                               fc=C_FULL if full else C_GDN, ec=C_EDGE, lw=0.4,
                               alpha=0.9))
        ax.add_patch(Rectangle((-9.0 + w_att + gap, y - LAYER_H * 0.42),
                               9.0 - w_att - gap, LAYER_H * 0.84,
                               fc=C_MLP, ec=C_EDGE, lw=0.4, alpha=0.9))
    ax.annotate("", xy=(10.2, Y_L0 + LAYERS * LAYER_H - 0.5), xytext=(10.2, Y_L0 + 0.5),
                arrowprops=dict(arrowstyle="-", lw=0.8, color=C_DIM, ls=(0, (2, 1))))
    ax.text(11.2, (Y_L0 + Y_TOP) / 2, L("32 片", "32 slabs"),
            fontsize=7.5, color=C_DIM, rotation=90, va="center", ha="center")


# ---------------------------------------------------------------- C 树
def draw_tree(ax) -> None:
    blank(ax)
    ends(ax)
    # 主干：从下往上收细
    ax.add_patch(Polygon([(-3.0, Y_EMBED[1]), (3.0, Y_EMBED[1]),
                          (1.0, Y_HEAD[0]), (-1.0, Y_HEAD[0])],
                         closed=True, fc=C_TRUNK, ec=C_EDGE, lw=0.5, alpha=0.9))
    for i in range(LAYERS):
        y = layer_y(i)
        full = is_full(i)
        t = i / max(LAYERS - 1, 1)
        reach = 7.6 - 3.0 * t          # 越往上枝越短
        base = 2.8 - 1.7 * t           # 主干越往上越细
        for s in (-1, 1):
            ax.add_patch(Polygon(
                [(s * base * 0.30, y + LAYER_H * 0.46),
                 (s * base * 0.30, y - LAYER_H * 0.46),
                 (s * reach, y - LAYER_H * 0.10),
                 (s * reach, y + LAYER_H * 0.10)],
                closed=True, fc=C_MLP if s > 0 else (C_FULL if full else C_GDN),
                ec=C_EDGE, lw=0.4, alpha=0.85))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 3, figsize=(16.5, 12.5), facecolor="#0d0f13")
    for ax in axes:
        ax.set_facecolor("#0d0f13")

    draw_spine(axes[0])
    draw_slices(axes[1])
    draw_tree(axes[2])

    titles = [
        (L("A  脊柱", "A  spine"),
         L("主干不断，模块是挂在主干上的器官", "continuous trunk, modules hang off it"),
         L("丢掉：模块之间的「并列」关系不明显", "loses: sibling relation between modules"),
         "ok"),
        (L("B  一摞切片", "B  stack of slabs"),
         L("每层一片厚板，模块在片内并排", "one slab per layer, modules side by side"),
         L("丢掉：残差被降级成「相邻」，看不出它是一条连续的路",
           "loses: residual reduced to adjacency"),
         "warn"),
        (L("C  倒长的树", "C  inverted tree"),
         L("从根长到冠，每层向外分叉", "grows from root to crown, branches out"),
         L("问题：残差被画成了分叉，等于说信息不回流，与 14 行 φ 不符",
           "problem: residual drawn as branching, i.e. no return path"),
         "bad"),
    ]
    for ax, (t, sub, note, flag) in zip(axes, titles):
        ax.set_title(t, color="#f2f2f2", fontsize=15, pad=34)
        ax.text(0.5, 1.018, sub, transform=ax.transAxes, ha="center",
                fontsize=9.5, color="#b9c0cc")
        col = {"ok": "#7fbf8f", "warn": "#d8b366", "bad": "#d0716f"}[flag]
        ax.text(0.5, -0.055, note, transform=ax.transAxes, ha="center",
                fontsize=9, color=col, wrap=True)

    handles = [
        Rectangle((0, 0), 1, 1, fc=C_GDN, ec=C_EDGE),
        Rectangle((0, 0), 1, 1, fc=C_FULL, ec=C_EDGE),
        Rectangle((0, 0), 1, 1, fc=C_MLP, ec=C_EDGE),
        Rectangle((0, 0), 1, 1, fc=C_TRUNK, ec=C_EDGE),
        Rectangle((0, 0), 1, 1, fc=C_END, ec=C_EDGE),
    ]
    labels = [
        L("翼 · 线性注意力 GDN（3/4 层）", "wing · GDN (3 of 4)"),
        L("翼 · 全注意力（1/4 层）", "wing · full attn (1 of 4)"),
        L("囊 · MLP（12288/4096 = 3）", "sac · MLP"),
        L("主干 · 残差流", "trunk · residual stream"),
        L("端点 · embed / lm_head", "ends · embed / lm_head"),
    ]
    leg = fig.legend(handles, labels, loc="lower center", ncol=5, frameon=False,
                     fontsize=9, labelcolor="#c8ced8", bbox_to_anchor=(0.5, 0.005))

    fig.suptitle(L("三种视觉语法：同一个 32 层模型，三种「层」的摆法",
                   "three visual grammars for the same 32-layer model"),
                 color="#f4f4f4", fontsize=17, y=0.962)
    fig.subplots_adjust(left=0.03, right=0.97, top=0.845, bottom=0.085, wspace=0.05)

    out = OUT / "grammar_candidates.png"
    fig.savefig(out, dpi=115, facecolor=fig.get_facecolor())
    print(f"wrote {out}  ({out.stat().st_size/1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

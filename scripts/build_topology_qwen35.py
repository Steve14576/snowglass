"""阶段 1 第 1 步：从阶段 0 的张量清单生成 Qwen3.5-9B 的功能块拓扑（不含坐标，坐标由编辑器算）。

输入：
  out/inventory/Qwen3.5-9B-Q4_K_M.tensors.json   （scripts/gguf_inventory.py 生成）
  out/inventory/mmproj-BF16.tensors.json
输出：
  prototype/data/qwen35_9b.topo.json

放在 prototype/data/ 下是为了让编辑器能用同目录相对路径读它，无论服务根是项目根还是
prototype/ 都能打开（前端没有构建步骤，只能靠相对路径）。

规则来源：docs/decisions.md 的 D11（切片 + 残差棒）、D13（二维怎么拆三维）、U9（MTP 只画框）、U10（还原 HF 约定）。
事实来源：docs/qwen35_9b_facts.md。

硬检查（不通过就报错退出，不出文件）：
  - 每个被引用的张量都必须真实存在于清单里
  - 清单里的每个张量必须恰好归入一个块（不漏、不重复）

用法：
  uv run --no-project python scripts/build_topology_qwen35.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INV_TEXT = ROOT / "out" / "inventory" / "Qwen3.5-9B-Q4_K_M.tensors.json"
INV_VIS = ROOT / "out" / "inventory" / "mmproj-BF16.tensors.json"
OUT = ROOT / "prototype" / "data" / "qwen35_9b.topo.json"

N_LAYERS = 32
FULL_EVERY = 4
N_VLAYERS = 27

# GGUF 名 -> HF 名（文本部分；对照表见 docs/qwen35_9b_facts.md 第 4 节）
HF_LAYER = {
    "attn_norm.weight": "input_layernorm.weight",
    "post_attention_norm.weight": "post_attention_layernorm.weight",
    "attn_qkv.weight": "linear_attn.in_proj_qkv.weight",
    "attn_gate.weight": "linear_attn.in_proj_z.weight",
    "ssm_alpha.weight": "linear_attn.in_proj_a.weight",
    "ssm_beta.weight": "linear_attn.in_proj_b.weight",
    "ssm_conv1d.weight": "linear_attn.conv1d.weight",
    "ssm_a": "linear_attn.A_log",
    "ssm_dt.bias": "linear_attn.dt_bias",
    "ssm_norm.weight": "linear_attn.norm.weight",
    "ssm_out.weight": "linear_attn.out_proj.weight",
    "attn_q.weight": "self_attn.q_proj.weight",
    "attn_k.weight": "self_attn.k_proj.weight",
    "attn_v.weight": "self_attn.v_proj.weight",
    "attn_output.weight": "self_attn.o_proj.weight",
    "attn_q_norm.weight": "self_attn.q_norm.weight",
    "attn_k_norm.weight": "self_attn.k_norm.weight",
    "ffn_gate.weight": "mlp.gate_proj.weight",
    "ffn_up.weight": "mlp.up_proj.weight",
    "ffn_down.weight": "mlp.down_proj.weight",
}
HF_GLOBAL = {
    "token_embd.weight": "model.language_model.embed_tokens.weight",
    "output.weight": "lm_head.weight",
    "output_norm.weight": "model.language_model.norm.weight",
}

# U10：GGUF 相对 HF 的约定差异，数据阶段按此还原（这里只登记，不改数值）
RESTORE = {
    "attn_norm.weight": "minus_one",
    "post_attention_norm.weight": "minus_one",
    "attn_q_norm.weight": "minus_one",
    "attn_k_norm.weight": "minus_one",
    "output_norm.weight": "minus_one",
    "ssm_a": "log_neg_then_vhead_perm",           # A_log = log(-ssm_a)，再按 value 头逆置换
    "ssm_dt.bias": "vhead_perm",
    "ssm_alpha.weight": "vhead_perm_rows",
    "ssm_beta.weight": "vhead_perm_rows",
    "attn_gate.weight": "vhead_perm_rows_x128",
    "ssm_out.weight": "vhead_perm_cols_x128",
    "attn_qkv.weight": "vhead_perm_rows_x128_v_segment",
    "ssm_conv1d.weight": "vhead_perm_rows_x128_v_segment",
}


def hf_name(gguf: str) -> str | None:
    if gguf in HF_GLOBAL:
        return HF_GLOBAL[gguf]
    if gguf.startswith("blk."):
        _, idx, rest = gguf.split(".", 2)
        if rest in HF_LAYER:
            return f"model.language_model.layers.{idx}.{HF_LAYER[rest]}"
    return None


class Builder:
    def __init__(self, inv: dict[str, dict], source: str):
        self.inv = inv
        self.source = source
        self.used: dict[str, str] = {}
        self.blocks: list[dict] = []

    def ref(self, name: str, rows: tuple[int, int] | None = None, block_id: str = "") -> dict:
        if name not in self.inv:
            raise KeyError(f"清单里没有张量 {name}（{self.source}）")
        t = self.inv[name]
        key = name if rows is None else f"{name}[{rows[0]}:{rows[1]}]"
        if key in self.used:
            raise ValueError(f"{key} 被重复归入 {self.used[key]} 与 {block_id}")
        self.used[key] = block_id
        n = t["n_elements"]
        if rows is not None:
            n = (rows[1] - rows[0]) * (t["n_elements"] // t["shape"][0])
        short = name.split(".", 2)[-1] if name.startswith("blk.") else name
        return {
            "file": self.source,
            "gguf": name,
            "hf": hf_name(name) if self.source == "text" else None,
            "shape": t["shape"],
            "rows": list(rows) if rows else None,
            "qtype": t["qtype"],
            "params": n,
            "restore": RESTORE.get(short) if self.source == "text" else None,
        }

    def add(self, bid: str, **kw) -> dict:
        tensors = [self.ref(*spec, block_id=bid) if isinstance(spec, tuple) else self.ref(spec, block_id=bid)
                   for spec in kw.pop("tensors", [])]
        b = {"id": bid, **kw, "tensors": tensors, "params": sum(t["params"] for t in tensors)}
        self.blocks.append(b)
        return b

    def coverage(self) -> list[str]:
        missing = []
        for name, t in self.inv.items():
            if name in self.used:
                continue
            # 被按行段拆开的张量：检查各段是否覆盖了全部行
            segs = sorted(tuple(map(int, k[len(name) + 1:-1].split(":")))
                          for k in self.used if k.startswith(name + "["))
            if segs and segs[0][0] == 0 and segs[-1][1] == t["shape"][0] and all(
                    a[1] == b[0] for a, b in zip(segs, segs[1:])):
                continue
            missing.append(name)
        return missing


def fold_heads(n_heads: int, head_dim: int, n_in: int, axis: str = "rows") -> dict:
    return {"basis": "structure", "axis": axis, "factors": [n_heads, head_dim, n_in],
            "labels": ["head", "head_dim", "in" if axis == "rows" else "out"]}


FOLD_ASPECT = {"basis": "aspect", "note": "长轴按块的长宽比分解成两个因子，由编辑器按块尺寸决定"}
FOLD_1D = {"basis": "aspect_1d", "note": "一维张量按长度因式分解成小块"}


def build_text(bt: Builder) -> list[dict]:
    layers = []
    bt.add("embed", group="end", role="embed", label="Token Embedding",
           tensors=["token_embd.weight"], fold=FOLD_ASPECT)
    for i in range(N_LAYERS):
        full = (i % FULL_EVERY) == FULL_EVERY - 1
        p = f"blk.{i}."
        L = f"L{i:02d}"
        kind = "full" if full else "gdn"
        layers.append({"index": i, "kind": kind})
        # 注意力一侧：从残差棒向外排
        bt.add(f"{L}.attn_norm", layer=i, side="attn", order=0, role="norm", label="input RMSNorm",
               tensors=[p + "attn_norm.weight"], fold=FOLD_1D)
        if full:
            bt.add(f"{L}.q", layer=i, side="attn", order=1, role="attn_q", label="Q（含输出门控）",
                   tensors=[p + "attn_q.weight"], fold=fold_heads(16, 512, 4096))
            bt.add(f"{L}.k", layer=i, side="attn", order=2, role="attn_k", label="K",
                   tensors=[p + "attn_k.weight"], fold=fold_heads(4, 256, 4096))
            bt.add(f"{L}.v", layer=i, side="attn", order=3, role="attn_v", label="V",
                   tensors=[p + "attn_v.weight"], fold=fold_heads(4, 256, 4096))
            bt.add(f"{L}.qk_norm", layer=i, side="attn", order=4, role="norm", label="QK norm",
                   tensors=[p + "attn_q_norm.weight", p + "attn_k_norm.weight"], fold=FOLD_1D)
            bt.add(f"{L}.o", layer=i, side="attn", order=5, role="attn_o", label="O",
                   tensors=[p + "attn_output.weight"], fold=fold_heads(16, 256, 4096, axis="cols"))
        else:
            qkv = p + "attn_qkv.weight"
            bt.add(f"{L}.q", layer=i, side="attn", order=1, role="gdn_q", label="q",
                   tensors=[(qkv, (0, 2048))], fold=fold_heads(16, 128, 4096))
            bt.add(f"{L}.k", layer=i, side="attn", order=2, role="gdn_k", label="k",
                   tensors=[(qkv, (2048, 4096))], fold=fold_heads(16, 128, 4096))
            bt.add(f"{L}.v", layer=i, side="attn", order=3, role="gdn_v", label="v",
                   tensors=[(qkv, (4096, 8192))], fold=fold_heads(32, 128, 4096))
            bt.add(f"{L}.z", layer=i, side="attn", order=4, role="gdn_gate", label="输出门控 z",
                   tensors=[p + "attn_gate.weight"], fold=fold_heads(32, 128, 4096))
            bt.add(f"{L}.ctrl", layer=i, side="attn", order=5, role="gdn_ctrl",
                   label="递推控制（α β 卷积 A dt norm）",
                   tensors=[p + "ssm_alpha.weight", p + "ssm_beta.weight", p + "ssm_conv1d.weight",
                            p + "ssm_a", p + "ssm_dt.bias", p + "ssm_norm.weight"],
                   fold={"basis": "structure", "note": "α、β 每个 value 头一行；卷积按通道；其余为一维"})
            bt.add(f"{L}.out", layer=i, side="attn", order=6, role="gdn_out", label="输出投影",
                   tensors=[p + "ssm_out.weight"], fold=fold_heads(32, 128, 4096, axis="cols"))
        # MLP 一侧：从残差棒向外排
        bt.add(f"{L}.post_norm", layer=i, side="mlp", order=0, role="norm", label="post RMSNorm",
               tensors=[p + "post_attention_norm.weight"], fold=FOLD_1D)
        bt.add(f"{L}.gate", layer=i, side="mlp", order=1, role="mlp_gate", label="gate",
               tensors=[p + "ffn_gate.weight"], fold=FOLD_ASPECT)
        bt.add(f"{L}.up", layer=i, side="mlp", order=2, role="mlp_up", label="up",
               tensors=[p + "ffn_up.weight"], fold=FOLD_ASPECT)
        bt.add(f"{L}.down", layer=i, side="mlp", order=3, role="mlp_down", label="down",
               tensors=[p + "ffn_down.weight"], fold=FOLD_ASPECT)
    bt.add("final_norm", group="end", role="norm", label="final RMSNorm",
           tensors=["output_norm.weight"], fold=FOLD_1D)
    bt.add("lm_head", group="end", role="lm_head", label="LM Head",
           tensors=["output.weight"], fold=FOLD_ASPECT)
    return layers


def build_vision(bv: Builder) -> None:
    bv.add("V.patch", group="vision_end", role="vis_patch", label="视觉 patch 嵌入 + 位置编码",
           tensors=["v.patch_embd.weight", "v.patch_embd.weight.1", "v.patch_embd.bias",
                    "v.position_embd.weight"], fold=FOLD_ASPECT)
    for i in range(N_VLAYERS):
        p = f"v.blk.{i}."
        bv.add(f"V{i:02d}.attn", vlayer=i, side="vattn", role="vis_attn", label="视觉注意力",
               tensors=[p + "ln1.weight", p + "ln1.bias", p + "attn_qkv.weight", p + "attn_qkv.bias",
                        p + "attn_out.weight", p + "attn_out.bias"], fold=FOLD_ASPECT)
        bv.add(f"V{i:02d}.mlp", vlayer=i, side="vmlp", role="vis_mlp", label="视觉 MLP",
               tensors=[p + "ln2.weight", p + "ln2.bias", p + "ffn_up.weight", p + "ffn_up.bias",
                        p + "ffn_down.weight", p + "ffn_down.bias"], fold=FOLD_ASPECT)
    bv.add("V.merger", group="vision_end", role="vis_merger", label="视觉投影器（2×2 合并 → 4096）",
           tensors=["v.post_ln.weight", "v.post_ln.bias", "mm.0.weight", "mm.0.bias",
                    "mm.2.weight", "mm.2.bias"], fold=FOLD_ASPECT)


def load_inv(path: Path) -> tuple[dict, dict]:
    d = json.loads(path.read_text(encoding="utf-8"))
    return {t["name"]: t for t in d["tensors"]}, d


def main() -> int:
    inv_t, meta_t = load_inv(INV_TEXT)
    inv_v, meta_v = load_inv(INV_VIS)

    bt = Builder(inv_t, "text")
    layers = build_text(bt)
    bv = Builder(inv_v, "vision")
    build_vision(bv)

    miss_t, miss_v = bt.coverage(), bv.coverage()
    if miss_t or miss_v:
        print("覆盖检查失败：以下张量没有归入任何块")
        for n in miss_t + miss_v:
            print("  ", n)
        return 1

    blocks = bt.blocks + bv.blocks
    geometry_only = [
        {"id": "residual_rod", "role": "residual_rod", "label": "残差流 x（4096 维，贯穿全模型）",
         "source": "code", "note": "D11：无权重，表示代码里 x = x + attn(norm(x)); x = x + mlp(norm(x)) 的 x"},
        {"id": "mtp", "role": "mtp", "label": "MTP 多 token 预测头", "source": "missing",
         "note": "U9（暂按提议执行）：GGUF 没有这部分权重，只画框，不填雪花"},
    ]

    text_params = sum(b["params"] for b in bt.blocks)
    vis_params = sum(b["params"] for b in bv.blocks)
    if text_params != sum(t["n_elements"] for t in inv_t.values()):
        print("参数总数对不上（文本）")
        return 1
    if vis_params != sum(t["n_elements"] for t in inv_v.values()):
        print("参数总数对不上（视觉）")
        return 1

    out = {
        "model": {
            "name": "Qwen3.5-9B",
            "precision_label": "Q4_K_M",
            "n_layers": N_LAYERS,
            "full_attention_interval": FULL_EVERY,
            "hidden": 4096,
            "vision_layers": N_VLAYERS,
            "params_text": text_params,
            "params_vision": vis_params,
            "sources": {"text": meta_t["file"], "vision": meta_v["file"]},
        },
        "policy": {
            "U9_mtp": "frame_only",
            "U10_restore_hf_conventions": True,
            "fold_rules": "D13",
        },
        "layers": layers,
        "blocks": blocks,
        "geometry_only": geometry_only,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    by_role: dict[str, int] = {}
    for b in blocks:
        by_role[b["role"]] = by_role.get(b["role"], 0) + 1
    print(f"blocks           : {len(blocks)}（文本 {len(bt.blocks)}，视觉 {len(bv.blocks)}）+ 纯几何 {len(geometry_only)}")
    print(f"tensors covered  : 文本 {len(inv_t)}/{len(inv_t)}，视觉 {len(inv_v)}/{len(inv_v)}")
    print(f"params           : 文本 {text_params/1e9:.3f} B，视觉 {vis_params/1e9:.3f} B（与清单总数一致）")
    print("blocks by role   : " + ", ".join(f"{k}={v}" for k, v in sorted(by_role.items())))
    print(f"wrote {OUT}  ({OUT.stat().st_size/1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

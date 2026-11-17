"""阶段 1 第 1 步：从阶段 0 的张量清单生成 Qwen3.5-9B 的功能块拓扑（不含坐标，坐标由编辑器算）。

输入：
  out/inventory/Qwen3.5-9B-Q4_K_M.tensors.json   （scripts/gguf_inventory.py 生成）
  out/inventory/mmproj-BF16.tensors.json
输出：
  prototype/data/qwen35_9b.topo.json

放在 prototype/data/ 下是为了让编辑器能用同目录相对路径读它，无论服务根是项目根还是
prototype/ 都能打开（前端没有构建步骤，只能靠相对路径）。

规则来源：docs/decisions.md 的 D11（4.2 排布、不画棒）、D13（独立张量分区）、U9 / U10。
配置独立驱动架构；现有张量清单绑定实际形状与格式。--architecture-only 可只凭 config 出架构。
首次运行只获取官方小配置，不读取权重数值。
事实来源：docs/qwen35_9b_facts.md。

硬检查（不通过就报错退出，不出文件）：
  - 每个被引用的张量都必须真实存在于清单里
  - 清单里的每个张量必须恰好归入一个块（不漏、不重复）

用法：
  uv run --no-project python scripts/build_topology_qwen35.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INV_TEXT = ROOT / "out" / "inventory" / "Qwen3.5-9B-Q4_K_M.tensors.json"
INV_VIS = ROOT / "out" / "inventory" / "mmproj-BF16.tensors.json"
OUT = ROOT / "prototype" / "data" / "qwen35_9b.topo.json"

CONFIG = ROOT / "data" / "configs" / "Qwen3.5-9B.config.json"
CONFIG_URL = "https://huggingface.co/Qwen/Qwen3.5-9B/resolve/main/config.json"


def load_config(path: Path) -> tuple[dict, dict]:
    """只获取 KB 级配置，不导入 gguf，也不读取权重文件。已有本地配置不覆盖。"""
    if not path.exists():
        if path != CONFIG:
            raise FileNotFoundError(path)
        with urllib.request.urlopen(CONFIG_URL, timeout=30) as response:
            raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("配置超过 1 MB，拒绝将它当作小配置加载")
        json.loads(raw)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    raw = path.read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    return doc, {"path": str(path), "url": CONFIG_URL if path == CONFIG else None,
                 "sha256": hashlib.sha256(raw).hexdigest()}


def parse_config(doc: dict) -> dict:
    text = doc.get("text_config", doc)
    if text.get("model_type") != "qwen3_5_text":
        raise ValueError("本轮适配器仅支持 qwen3_5_text，不凭相似字段猜测其他架构")
    def positive(obj, key):
        value = obj.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"配置字段 {key} 必须是正整数")
        return value
    count = positive(text, "num_hidden_layers")
    interval = text.get("full_attention_interval", 4)
    types = text.get("layer_types")
    if types is None:
        if not isinstance(interval, int) or interval <= 0:
            raise ValueError("full_attention_interval 必须为正整数")
        types = ["full_attention" if (i + 1) % interval == 0 else "linear_attention" for i in range(count)]
    if len(types) != count or any(t not in ("linear_attention", "full_attention") for t in types):
        raise ValueError("layer_types 必须逐层列出受支持的类型，长度与层数一致")
    vision = doc.get("vision_config", {})
    cfg = {"name": "Qwen3.5-9B" if count == 32 and text.get("hidden_size") == 4096 else "Qwen3.5 配置实例",
           "n_layers": count, "layer_types": types, "full_attention_interval": interval,
           "hidden": positive(text, "hidden_size"), "ffn": positive(text, "intermediate_size"),
           "vocab": positive(text, "vocab_size"), "heads": positive(text, "num_attention_heads"),
           "kv_heads": positive(text, "num_key_value_heads"), "head_dim": positive(text, "head_dim"),
           "key_heads": positive(text, "linear_num_key_heads"),
           "value_heads": positive(text, "linear_num_value_heads"),
           "key_dim": positive(text, "linear_key_head_dim"), "value_dim": positive(text, "linear_value_head_dim"),
           "conv": positive(text, "linear_conv_kernel_dim"), "tie_embeddings": bool(text.get("tie_word_embeddings", doc.get("tie_word_embeddings", False))),
           "mtp_layers": text.get("mtp_num_hidden_layers", 0), "vision_layers": vision.get("depth", 0),
           "vision_hidden": vision.get("hidden_size", 0), "vision_ffn": vision.get("intermediate_size", 0)}
    if vision:
        for key in ("depth", "hidden_size", "intermediate_size", "patch_size", "in_channels", "num_position_embeddings",
                    "spatial_merge_size", "out_hidden_size", "temporal_patch_size"):
            positive(vision, key)
        if vision["temporal_patch_size"] != 2:
            raise ValueError("当前 mmproj 命名适配器仅核实过 temporal_patch_size=2 的双 patch 权重")
    gate = text.get("attn_output_gate", True)
    if not isinstance(gate, bool):
        raise ValueError("attn_output_gate 必须是布尔值")
    cfg["_q_multiplier"] = 2 if gate else 1
    cfg["_vision"] = vision
    return cfg


def expected_text_shape(name: str, c: dict) -> list[int] | None:
    short = name.split(".", 2)[-1] if name.startswith("blk.") else name
    h, f, d = c["hidden"], c["ffn"], c["head_dim"]
    qk = c["key_heads"] * c["key_dim"]
    v = c["value_heads"] * c["value_dim"]
    shapes = {"token_embd.weight": [c["vocab"], h], "output.weight": [c["vocab"], h], "output_norm.weight": [h],
              "attn_norm.weight": [h], "post_attention_norm.weight": [h],
              "ffn_gate.weight": [f, h], "ffn_up.weight": [f, h], "ffn_down.weight": [h, f],
              "attn_q.weight": [c["_q_multiplier"] * c["heads"] * d, h], "attn_k.weight": [c["kv_heads"] * d, h],
              "attn_v.weight": [c["kv_heads"] * d, h], "attn_output.weight": [h, c["heads"] * d],
              "attn_q_norm.weight": [d], "attn_k_norm.weight": [d],
              "attn_qkv.weight": [2 * qk + v, h], "attn_gate.weight": [v, h],
              "ssm_alpha.weight": [c["value_heads"], h], "ssm_beta.weight": [c["value_heads"], h],
              "ssm_conv1d.weight": [2 * qk + v, c["conv"]], "ssm_a": [c["value_heads"]],
              "ssm_dt.bias": [c["value_heads"]], "ssm_norm.weight": [c["value_dim"]], "ssm_out.weight": [h, v]}
    return shapes.get(short)

def expected_vision_shape(name: str, c: dict) -> list[int] | None:
    v = c["_vision"]
    if not v:
        return None
    d, f, patch = v["hidden_size"], v["intermediate_size"], v["patch_size"]
    if name.startswith("v.blk."):
        short = name.split(".", 3)[-1]
        return {"ln1.weight": [d], "ln1.bias": [d], "ln2.weight": [d], "ln2.bias": [d],
                "attn_qkv.weight": [3*d, d], "attn_qkv.bias": [3*d], "attn_out.weight": [d, d], "attn_out.bias": [d],
                "ffn_up.weight": [f, d], "ffn_up.bias": [f], "ffn_down.weight": [d, f], "ffn_down.bias": [d]}.get(short)
    merged = d * v["spatial_merge_size"]**2
    return {"v.patch_embd.weight": [d, v["in_channels"], patch, patch],
            "v.patch_embd.weight.1": [d, v["in_channels"], patch, patch], "v.patch_embd.bias": [d],
            "v.position_embd.weight": [v["num_position_embeddings"], d], "v.post_ln.weight": [d], "v.post_ln.bias": [d],
            "mm.0.weight": [merged, merged], "mm.0.bias": [merged],
            "mm.2.weight": [v["out_hidden_size"], merged], "mm.2.bias": [v["out_hidden_size"]]}.get(name)


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
    def __init__(self, inv: dict[str, dict] | None, source: str, cfg: dict):
        self.inv = inv
        self.source = source
        self.cfg = cfg
        self.used: dict[str, str] = {}
        self.blocks: list[dict] = []

    def ref(self, name: str, rows: tuple[int, int] | None = None, block_id: str = "") -> dict:
        expected = expected_text_shape(name, self.cfg) if self.source == "text" else None
        if self.inv is None:
            t = {"shape": expected, "qtype": None, "n_elements": math.prod(expected) if expected else 0}
        else:
            if name not in self.inv:
                raise KeyError(f"清单里没有张量 {name}（{self.source}）")
            t = self.inv[name]
            checked = expected if self.source == "text" else expected_vision_shape(name, self.cfg)
            if checked and t["shape"] != checked:
                raise ValueError(f"配置与清单形状冲突：{name}，预期 {checked}，清单 {t['shape']}")
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
            "binding": "inventory" if self.inv is not None else "config_unbound",
            "fold": FOLD_1D if expected and len(expected) == 1 else FOLD_ASPECT,
        }

    def add(self, bid: str, **kw) -> dict:
        tensors = [self.ref(*spec, block_id=bid) if isinstance(spec, tuple) else self.ref(spec, block_id=bid)
                   for spec in kw.pop("tensors", [])]
        b = {"id": bid, **kw, "tensors": tensors, "params": sum(t["params"] for t in tensors)}
        self.blocks.append(b)
        return b

    def coverage(self) -> list[str]:
        missing = []
        for name, t in (self.inv or {}).items():
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
    c = bt.cfg
    bt.add("embed", group="end", slot="embed", role="embed", label="Token Embedding",
           tensors=["token_embd.weight"], fold=FOLD_ASPECT)
    layers = []
    for i, typ in enumerate(c["layer_types"]):
        full = typ == "full_attention"
        p, tag = f"blk.{i}.", f"L{i:02d}"
        layers.append({"index": i, "kind": "full" if full else "gdn", "type": typ})
        bt.add(f"{tag}.attn_norm", layer=i, slot="norm1", role="norm", label="Input RMSNorm",
               tensors=[p + "attn_norm.weight"], fold=FOLD_1D)
        names = [(["attn_q.weight", "attn_q_norm.weight"], "Q / Gate" if c["_q_multiplier"] == 2 else "Q", "attn_q"),
                 (["attn_k.weight", "attn_v.weight", "attn_k_norm.weight"], "K / V", "attn_k"),
                 (["attn_output.weight"], "输出投影", "attn_o")] if full else [
                 (["attn_qkv.weight"], "输入投影 q / k / v", "gdn_q"),
                 (["attn_gate.weight", "ssm_alpha.weight", "ssm_beta.weight", "ssm_conv1d.weight", "ssm_a", "ssm_dt.bias", "ssm_norm.weight"],
                  "门控 / Conv / 递推控制", "gdn_ctrl"), (["ssm_out.weight"], "输出投影", "gdn_out")]
        for j, (ts, label, role) in enumerate(names):
            bt.add(f"{tag}.mix{j}", layer=i, slot="mixer", order=j, role=role,
                   label=("Full Attention · " if full else "Gated DeltaNet · ") + label,
                   tensors=[p + n for n in ts], fold={"basis": "per_tensor", "note": "各张量独立处理后分区填充"})
        bt.add(f"{tag}.post_norm", layer=i, slot="norm2", role="norm", label="Post RMSNorm",
               tensors=[p + "post_attention_norm.weight"], fold=FOLD_1D)
        for j, part in enumerate(("gate", "up", "down")):
            bt.add(f"{tag}.{part}", layer=i, slot="ffn", order=j, role="mlp_" + part,
                   label="MLP · " + part, tensors=[p + f"ffn_{part}.weight"], fold=FOLD_ASPECT)
    bt.add("final_norm", group="end", slot="final_norm", role="norm", label="Final RMSNorm",
           tensors=["output_norm.weight"], fold=FOLD_1D)
    if not c["tie_embeddings"]:
        bt.add("lm_head", group="end", slot="lm_head", role="lm_head", label="LM Head",
               tensors=["output.weight"], fold=FOLD_ASPECT)
    return layers


def build_vision(bv: Builder) -> None:
    bv.add("V.patch", group="vision_end", role="vis_patch", label="视觉 patch 嵌入 + 位置编码",
           tensors=["v.patch_embd.weight", "v.patch_embd.weight.1", "v.patch_embd.bias",
                    "v.position_embd.weight"], fold=FOLD_ASPECT)
    for i in range(bv.cfg["vision_layers"]):
        p = f"v.blk.{i}."
        for slot, role, names in (("norm1", "norm", ["ln1.weight", "ln1.bias"]),
                                  ("attn", "vis_attn", ["attn_qkv.weight", "attn_qkv.bias", "attn_out.weight", "attn_out.bias"]),
                                  ("norm2", "norm", ["ln2.weight", "ln2.bias"]),
                                  ("mlp", "vis_mlp", ["ffn_up.weight", "ffn_up.bias", "ffn_down.weight", "ffn_down.bias"])):
            bv.add(f"V{i:02d}.{slot}", vlayer=i, slot="v_" + slot, role=role, label="视觉 · " + slot,
                   tensors=[p + n for n in names], fold={"basis": "per_tensor", "note": "各张量独立处理"})
    bv.add("V.merger", group="vision_end", role="vis_merger", label="视觉投影器（2×2 合并 → 4096）",
           tensors=["v.post_ln.weight", "v.post_ln.bias", "mm.0.weight", "mm.0.bias",
                    "mm.2.weight", "mm.2.bias"], fold=FOLD_ASPECT)


def load_inv(path: Path) -> tuple[dict, dict]:
    d = json.loads(path.read_text(encoding="utf-8"))
    inv = {t["name"]: t for t in d["tensors"]}
    if len(inv) != len(d["tensors"]):
        raise ValueError(f"清单包含重名张量：{path}")
    return inv, d


def main() -> int:
    ap = argparse.ArgumentParser(description="只读配置和清单，生成 4.2 功能分组，不加载权重")
    ap.add_argument("--config", type=Path, default=CONFIG)
    ap.add_argument("--architecture-only", action="store_true", help="不绑定张量清单，输出未绑定架构")
    ap.add_argument("--output", type=Path, default=OUT)
    args = ap.parse_args()
    doc, provenance = load_config(args.config.resolve())
    cfg = parse_config(doc)
    inv_t, meta_t = (None, {}) if args.architecture_only else load_inv(INV_TEXT)
    inv_v, meta_v = (None, {}) if args.architecture_only or not cfg["vision_layers"] else load_inv(INV_VIS)
    bt = Builder(inv_t, "text", cfg)
    layers = build_text(bt)
    bv = Builder(inv_v, "vision", cfg)
    if cfg["vision_layers"]:
        build_vision(bv)

    miss_t, miss_v = bt.coverage(), bv.coverage()
    if miss_t or miss_v:
        print("覆盖检查失败：以下张量没有归入任何块")
        for n in miss_t + miss_v:
            print("  ", n)
        return 1

    blocks = bt.blocks + bv.blocks
    geometry_only = [{"id": "mtp", "role": "mtp", "label": "MTP 辅助预测 · 权重未收录", "source": "missing",
                      "note": "只画框，不生成模拟或真实雪花"}] if cfg["mtp_layers"] else []
    for b in blocks:
        for t in b["tensors"]:
            short = t["gguf"].split(".", 2)[-1]
            if t["file"] != "text":
                continue
            h = cfg["hidden"]
            if short == "attn_q.weight":
                t["fold"] = fold_heads(cfg["heads"], cfg["_q_multiplier"] * cfg["head_dim"], h)
            elif short in ("attn_k.weight", "attn_v.weight"):
                t["fold"] = fold_heads(cfg["kv_heads"], cfg["head_dim"], h)
            elif short in ("attn_gate.weight", "ssm_out.weight"):
                t["fold"] = fold_heads(cfg["value_heads"], cfg["value_dim"], h,
                                       axis="cols" if short == "ssm_out.weight" else "rows")
            elif short == "attn_output.weight":
                t["fold"] = fold_heads(cfg["heads"], cfg["head_dim"], h, axis="cols")
            elif short == "attn_qkv.weight":
                k, v = cfg["key_heads"] * cfg["key_dim"], cfg["value_heads"] * cfg["value_dim"]
                t["fold"] = {"basis": "segments", "segments": [
                    {"name": "q", "rows": [0, k], "factors": [cfg["key_heads"], cfg["key_dim"], h]},
                    {"name": "k", "rows": [k, 2 * k], "factors": [cfg["key_heads"], cfg["key_dim"], h]},
                    {"name": "v", "rows": [2 * k, 2 * k + v], "factors": [cfg["value_heads"], cfg["value_dim"], h]}]}

    text_params = sum(b["params"] for b in bt.blocks)
    vis_params = sum(b["params"] for b in bv.blocks)
    if inv_t is not None and text_params != sum(t["n_elements"] for t in inv_t.values()):
        print("参数总数对不上（文本）")
        return 1
    if inv_v is not None and vis_params != sum(t["n_elements"] for t in inv_v.values()):
        print("参数总数对不上（视觉）")
        return 1

    out = {
        "schema_version": 2,
        "config": provenance,
        "model": {**{k:v for k,v in cfg.items() if not k.startswith("_")}, "precision_label": "未绑定权重" if args.architecture_only else "Q4_K_M",
                  "params_text": text_params, "params_vision": vis_params,
                  "sources": {"text": meta_t.get("file"), "vision": meta_v.get("file")}},
        "coverage": {"status": "unbound" if args.architecture_only else "verified",
                     "text_tensors": len(inv_t or {}), "vision_tensors": len(inv_v or {}),
                     "source": "config_only" if args.architecture_only else "config_and_inventory"},
        "policy": {
            "U9_mtp": "frame_only",
            "U10_restore_hf_conventions": True,
            "fold_rules": "D13", "layout_reference": "real_config4.2", "unit_mm": 1,
            "tensor_processing": "independent", "residual_rod": False,
        },
        "layers": layers,
        "blocks": blocks,
        "geometry_only": geometry_only,
    }
    out["topology_id"] = hashlib.sha256(json.dumps(out, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    target = args.output.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(target)

    by_role: dict[str, int] = {}
    for b in blocks:
        by_role[b["role"]] = by_role.get(b["role"], 0) + 1
    print(f"blocks           : {len(blocks)}（文本 {len(bt.blocks)}，视觉 {len(bv.blocks)}）+ 纯几何 {len(geometry_only)}")
    print(f"config sha256    : {provenance['sha256']}")
    print(f"coverage         : {out['coverage']}")
    if args.architecture_only:
        print(f"params           : 文本形状估算 {text_params/1e9:.3f} B；视觉未绑定，不宣称参数量已核实")
    else:
        print(f"params           : 文本 {text_params/1e9:.3f} B，视觉 {vis_params/1e9:.3f} B（与清单总数一致）")
    print("blocks by role   : " + ", ".join(f"{k}={v}" for k, v in sorted(by_role.items())))
    print(f"wrote {target}  ({target.stat().st_size/1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

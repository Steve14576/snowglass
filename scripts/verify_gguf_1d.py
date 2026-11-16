"""阶段 0 核对（一维张量）：GGUF 转换时有没有改动一维参数的数值？

做法：从 HF safetensors 用 Range 只取第 0 层几个一维张量（每个几 KB），
与 GGUF 里对应张量逐元素比较，判断关系是"原样"、"取负指数"还是"加 1"。
另外把视觉塔元数据里 is_deepstack_layers 数组的值打出来。

用法：
  uv run --no-project --with gguf --with numpy python scripts/verify_gguf_1d.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_quant_visibility as qv  # 复用带重试的 Range 取数

ROOT = Path(__file__).resolve().parent.parent
GGUF = ROOT / "data" / "gguf" / "Qwen3.5-9B-Q4_K_M.gguf"
MMPROJ = ROOT / "data" / "gguf" / "mmproj-BF16.gguf"

PAIRS = [
    ("model.language_model.layers.0.linear_attn.A_log", "blk.0.ssm_a"),
    ("model.language_model.layers.0.linear_attn.dt_bias", "blk.0.ssm_dt.bias"),
    ("model.language_model.layers.0.linear_attn.norm.weight", "blk.0.ssm_norm.weight"),
    ("model.language_model.layers.0.input_layernorm.weight", "blk.0.attn_norm.weight"),
    ("model.language_model.layers.0.post_attention_layernorm.weight", "blk.0.post_attention_norm.weight"),
    ("model.language_model.layers.3.self_attn.q_norm.weight", "blk.3.attn_q_norm.weight"),
    ("model.language_model.norm.weight", "output_norm.weight"),
]


def fetch_hf(name: str, wmap: dict, headers: dict) -> np.ndarray:
    shard = wmap[name]
    url = qv.BASE + shard
    if shard not in headers:
        headers[shard] = qv.read_header(url)
    hdr, hlen = headers[shard]
    meta = hdr[name]
    b, e = meta["data_offsets"]
    buf = qv.fetch_range(url, 8 + hlen + b, 8 + hlen + e - 1)
    if meta["dtype"] == "BF16":
        u16 = np.frombuffer(buf, dtype="<u2")
        return (u16.astype(np.uint32) << 16).view(np.float32).reshape(meta["shape"])
    if meta["dtype"] == "F32":
        return np.frombuffer(buf, dtype="<f4").reshape(meta["shape"])
    raise NotImplementedError(meta["dtype"])


def relation(hf: np.ndarray, gg: np.ndarray) -> str:
    hf = hf.astype(np.float64).ravel()
    gg = gg.astype(np.float64).ravel()
    cands = {
        "原样": hf,
        "加 1": hf + 1.0,
        "取负指数 -exp(x)": -np.exp(hf),
        "指数 exp(x)": np.exp(hf),
    }
    best = min(cands, key=lambda k: np.abs(cands[k] - gg).max())
    err = np.abs(cands[best] - gg).max()
    return f"{best}（最大差 {err:.2e}）"


def main() -> int:
    from gguf import GGUFReader

    raw = qv.fetch_range(qv.BASE + "model.safetensors.index.json", 0, 50_000_000)
    wmap = json.loads(raw)["weight_map"]
    headers: dict = {}

    reader = GGUFReader(str(GGUF), "r")
    by_name = {t.name: t for t in reader.tensors}

    print("== 一维张量：HF 原值 与 GGUF 存值 的关系")
    for hf_name, gg_name in PAIRS:
        hf = fetch_hf(hf_name, wmap, headers)
        gg = np.asarray(by_name[gg_name].data, dtype=np.float32)
        short = hf_name.replace("model.language_model.", "")
        print(f"  {short:46s} -> {gg_name:34s} {relation(hf, gg)}")
        print(f"      HF 前 4 个: {np.round(hf.ravel()[:4], 4)}   GGUF 前 4 个: {np.round(gg.ravel()[:4], 4)}")
    print()

    mm = GGUFReader(str(MMPROJ), "r")
    f = mm.fields.get("clip.vision.is_deepstack_layers")
    if f is not None:
        vals = [bool(f.parts[i][0]) for i in f.data]
        idx = [i for i, v in enumerate(vals) if v]
        print(f"== clip.vision.is_deepstack_layers（27 个视觉层）")
        print(f"  为 True 的视觉层编号：{idx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

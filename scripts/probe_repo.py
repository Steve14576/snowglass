"""秒级探针：只读 HF 仓库元数据，不下载权重。

用途：
  1. 确认仓库可达、是否 gated
  2. 列出所有文件的体积，决定"只下第一个 shard"是否可行
  3. 打印 config.json 里的关键字段，核对与 docs/decisions.md 是否一致

用法：
  uv run --no-project --with huggingface_hub python scripts/probe_repo.py
  国内网络不通时：
  $env:HF_ENDPOINT="https://hf-mirror.com"; uv run --no-project --with huggingface_hub python scripts/probe_repo.py
"""

from __future__ import annotations

import json
import os
import sys

REPO = os.environ.get("SNOWGLASS_REPO", "Qwen/Qwen3.5-9B")


def human(n: int) -> str:
    return f"{n / 1e9:7.2f} GB"


def main() -> int:
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi()
    print(f"endpoint : {os.environ.get('HF_ENDPOINT', 'https://huggingface.co')}")
    print(f"repo     : {REPO}")

    try:
        info = api.model_info(REPO, files_metadata=True)
    except Exception as exc:  # noqa: BLE001 - 探针就是要看到真实异常
        print(f"FAILED   : {type(exc).__name__}: {exc}")
        return 1

    print(f"gated    : {info.gated}")
    print(f"sha      : {info.sha}")
    card = info.card_data or {}
    print(f"license  : {card.get('license')}")
    print()

    rows = []
    total = 0
    for s in info.siblings:
        size = s.size or 0
        total += size
        rows.append((s.rfilename, size))

    rows.sort()
    print(f"{'size':>10}  file")
    print("-" * 70)
    for name, size in rows:
        print(f"{human(size) if size else '     ????':>10}  {name}")
    print("-" * 70)
    print(f"{human(total):>10}  TOTAL ({len(rows)} files)")
    print()

    # 第一个 shard 里有哪些张量？只读 safetensors header，不读数据。
    shards = [n for n, _ in rows if n.endswith(".safetensors")]
    if not shards:
        print("no safetensors found; 可能是 GGUF-only 仓库，需要换路线")
        return 2

    index_name = "model.safetensors.index.json"
    try:
        path = hf_hub_download(REPO, index_name, cache_dir=None)
        with open(path, "r", encoding="utf-8") as f:
            index = json.load(f)
        weight_map = index.get("weight_map", {})
    except Exception as exc:  # noqa: BLE001
        print(f"index.json 读取失败（可能不存在）: {type(exc).__name__}: {exc}")
        weight_map = {}

    if weight_map:
        first = sorted(shards)[0]
        in_first = [k for k, v in weight_map.items() if v == first]
        print(f"first shard = {first}")
        print(f"tensors in first shard = {len(in_first)}")
        for k in in_first[:25]:
            print(f"  {k}")
        if len(in_first) > 25:
            print(f"  ... 共 {len(in_first)} 个")

        print()
        print("关键张量分布（确认第一个 shard 是否含 embed 与前几层）:")
        probes = [
            "model.embed_tokens.weight",
            "lm_head.weight",
            "model.layers.0.self_attn.q_proj.weight",
            "model.layers.0.mlp.down_proj.weight",
            "model.layers.1.self_attn.q_proj.weight",
        ]
        for p in probes:
            print(f"  {p:55s} -> {weight_map.get(p, '<不存在>')}")

    # config 关键字段
    try:
        cfg_path = hf_hub_download(REPO, "config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        keys = [
            "architectures",
            "num_hidden_layers",
            "hidden_size",
            "intermediate_size",
            "vocab_size",
            "num_attention_heads",
            "num_key_value_heads",
            "head_dim",
            "num_experts",
            "torch_dtype",
        ]
        print()
        print("config.json 关键字段:")
        for k in keys:
            if k in cfg:
                print(f"  {k:28s} = {cfg[k]}")
        if "text_config" in cfg:
            print("  (存在 text_config，以下来自 text_config)")
            for k in keys:
                if k in cfg["text_config"]:
                    print(f"  text.{k:23s} = {cfg['text_config'][k]}")
    except Exception as exc:  # noqa: BLE001
        print(f"config.json 读取失败: {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

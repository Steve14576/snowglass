"""秒级探针 2：分片覆盖 + safetensors header（不下载权重）。

回答三个问题：
  1. 每个 shard 覆盖哪些层、哪些张量类型 —— 决定"只下哪个 shard 就够做量化对比"
  2. safetensors 里到底是 bf16 还是 fp16 / fp32 —— 决定读权重时要不要 ml_dtypes
  3. 几个关键张量的 shape —— 核对 config

只发 HTTP Range 请求读前若干 KB，不落盘。
"""

from __future__ import annotations

import collections
import json
import sys
import urllib.request

REPO = "Qwen/Qwen3.5-9B"
BASE = f"https://huggingface.co/{REPO}/resolve/main/"


def fetch_range(url: str, start: int, end: int) -> bytes:
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def read_safetensors_header(url: str) -> dict:
    n = int.from_bytes(fetch_range(url, 0, 7), "little")
    if n <= 0 or n > 100_000_000:
        raise ValueError(f"header size 不合理: {n}")
    return json.loads(fetch_range(url, 8, 8 + n - 1))


def layer_of(name: str) -> str:
    parts = name.split(".")
    if "layers" in parts:
        i = parts.index("layers")
        return f"L{parts[i + 1]}"
    return "-"


def kind_of(name: str) -> str:
    for k in (
        "self_attn.q_proj",
        "self_attn.k_proj",
        "self_attn.v_proj",
        "self_attn.o_proj",
        "mlp.gate_proj",
        "mlp.up_proj",
        "mlp.down_proj",
        "linear_attn",
        "embed_tokens",
        "lm_head",
        "visual",
        "mtp",
    ):
        if k in name:
            return k
    return name.rsplit(".", 2)[-2] if name.endswith(".weight") else "?"


def main() -> int:
    # 1) index
    idx_url = BASE + "model.safetensors.index.json"
    with urllib.request.urlopen(idx_url, timeout=90) as r:
        index = json.loads(r.read())
    wmap = index["weight_map"]

    by_shard: dict[str, list[str]] = collections.defaultdict(list)
    for name, shard in wmap.items():
        by_shard[shard].append(name)

    print(f"total tensors = {len(wmap)}, shards = {len(by_shard)}")
    print()
    for shard in sorted(by_shard):
        names = by_shard[shard]
        layers = sorted({layer_of(n) for n in names if layer_of(n) != "-"},
                        key=lambda s: int(s[1:]))
        kinds = collections.Counter(kind_of(n) for n in names)
        print(f"== {shard}")
        print(f"   tensors = {len(names)}")
        print(f"   layers  = {layers if len(layers) <= 12 else layers[:6] + ['...'] + layers[-6:]}")
        print(f"   kinds   = {dict(kinds)}")
        print()

    # 2) header：dtype 直方图 + 关键 shape
    print("=" * 70)
    for shard in sorted(by_shard):
        url = BASE + shard
        try:
            hdr = read_safetensors_header(url)
        except Exception as exc:  # noqa: BLE001
            print(f"{shard}: header 读取失败 {type(exc).__name__}: {exc}")
            continue
        dtypes = collections.Counter(v.get("dtype") for v in hdr.values())
        print(f"{shard}")
        print(f"   dtypes = {dict(dtypes)}")
        # 挑几个有代表性的打印 shape
        show = []
        for n, v in hdr.items():
            k = kind_of(n)
            if k in ("embed_tokens", "lm_head", "mlp.down_proj", "self_attn.q_proj",
                     "linear_attn", "visual"):
                show.append((n, v.get("shape"), v.get("dtype")))
            if len(show) >= 4:
                break
        for n, shape, dt in show:
            print(f"   {n:60s} {shape} {dt}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""秒级探针：列出 Qwen3.5-9B 的 GGUF 仓库里有哪些文件、多大（只读元数据，不下载权重）。

用法：
  uv run --no-project --with huggingface_hub python scripts/probe_gguf_repos.py
"""

from __future__ import annotations

import sys

CANDIDATES = [
    "Qwen/Qwen3.5-9B-GGUF",
    "unsloth/Qwen3.5-9B-GGUF",
    "lmstudio-community/Qwen3.5-9B-GGUF",
    "bartowski/Qwen_Qwen3.5-9B-GGUF",
]


def main() -> int:
    from huggingface_hub import HfApi

    api = HfApi()
    for repo in CANDIDATES:
        print("=" * 72)
        print(repo)
        try:
            info = api.model_info(repo, files_metadata=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  不可用: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        card = info.card_data or {}
        print(f"  gated={info.gated}  license={card.get('license')}  sha={info.sha[:10]}")
        rows = sorted((s.rfilename, s.size or 0) for s in info.siblings)
        for name, size in rows:
            if name.endswith(".gguf"):
                print(f"  {size/1e9:7.2f} GB  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

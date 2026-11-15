"""列出仓库里的张量名（可按子串过滤），并标注所在 shard。

用法：
  uv run --no-project python scripts/list_tensors.py .layers.0. .layers.3.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_quant_visibility as qv  # 复用带重试的 fetch_range


def main(argv: list[str]) -> int:
    raw = qv.fetch_range(qv.BASE + "model.safetensors.index.json", 0, 50_000_000)
    idx = json.loads(raw)
    wmap = idx["weight_map"]

    pats = argv[1:] or ["."]
    sel = sorted(k for k in wmap if any(p in k for p in pats))
    print(f"{len(sel)} tensors match {pats}")
    for k in sel:
        shard = wmap[k].rsplit("-", 1)[-1].replace(".safetensors", "")
        print(f"  shard {shard}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

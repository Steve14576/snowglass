"""下载 Qwen3.5-9B 的 Q4_K_M GGUF 与视觉塔 mmproj，并用 HF 记录的 sha256 校验。

来源与选择见 docs/decisions.md D12。
支持断点续传：中断后重跑本脚本即可。

用法：
  uv run --no-project --with huggingface_hub python scripts/download_gguf.py
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

REPO = "unsloth/Qwen3.5-9B-GGUF"
FILES = [
    "Qwen3.5-9B-Q4_K_M.gguf",   # 文本主模型（Q4_K_M，个别张量 Q6_K）
    "mmproj-BF16.gguf",         # 视觉塔（BF16）
]
DEST = Path(__file__).resolve().parent.parent / "data" / "gguf"


def sha256_of(path: Path, chunk: int = 16 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main() -> int:
    from huggingface_hub import HfApi, hf_hub_download

    DEST.mkdir(parents=True, exist_ok=True)
    info = HfApi().model_info(REPO, files_metadata=True)
    meta = {s.rfilename: s for s in info.siblings}
    print(f"repo     : {REPO}  (sha {info.sha[:10]})", flush=True)
    print(f"dest     : {DEST}", flush=True)

    ok = True
    for name in FILES:
        s = meta.get(name)
        if s is None:
            print(f"[缺失] 仓库里没有 {name}", flush=True)
            ok = False
            continue
        expect_size = s.size or 0
        lfs = s.lfs
        expect_sha = None
        if lfs is not None:
            expect_sha = lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)
        print(f"\n== {name}  {expect_size/1e9:.2f} GB", flush=True)

        t0 = time.time()
        path = Path(hf_hub_download(REPO, name, local_dir=DEST))
        dt = time.time() - t0
        got = path.stat().st_size
        print(f"   downloaded in {dt/60:.1f} min  ->  {path}", flush=True)
        print(f"   size     : {got} (expect {expect_size})  {'OK' if got == expect_size else 'MISMATCH'}",
              flush=True)
        if got != expect_size:
            ok = False
            continue

        if expect_sha:
            t1 = time.time()
            sha = sha256_of(path)
            match = sha == expect_sha
            print(f"   sha256   : {sha}", flush=True)
            print(f"   expect   : {expect_sha}  {'OK' if match else 'MISMATCH'}  ({time.time()-t1:.0f}s)",
                  flush=True)
            ok = ok and match
        else:
            print("   sha256   : HF 未提供，跳过校验", flush=True)

    print("\nALL OK" if ok else "\nSOME FILES FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

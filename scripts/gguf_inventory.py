"""阶段 0：读 GGUF 文件头，列出张量清单（不加载权重数据）。

输出：
  - 屏幕：模型元数据关键字段、量化类型统计、非层张量、第 0 层与第 3 层的全部张量
  - out/inventory/<文件名>.tensors.json：每个张量的 名字 / 形状（行优先）/ 量化类型 / 元素数 / 字节数

形状说明：GGUF 记录的维度顺序是"最快变化的维度在前"（ne0 = 列数），
本脚本统一反转成 numpy 的行优先顺序，与 HF safetensors 的写法一致（例如 q_proj 写成 [8192, 4096]）。

用法：
  uv run --no-project --with gguf --with numpy python scripts/gguf_inventory.py
  uv run --no-project --with gguf --with numpy python scripts/gguf_inventory.py data/gguf/mmproj-BF16.gguf
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "data" / "gguf" / "Qwen3.5-9B-Q4_K_M.gguf"
OUT = ROOT / "out" / "inventory"

META_PATTERNS = (
    "general.architecture", "general.name", "general.file_type",
    "block_count", "context_length", "embedding_length", "feed_forward_length",
    "attention.head_count", "attention.head_count_kv", "attention.key_length",
    "attention.value_length", "full_attention_interval", "rope", "ssm.", "linear_attn",
    "nextn", "mtp", "vision", "clip.", "projector",
)


def field_value(field):
    """把 GGUF 元数据字段转成可打印的 Python 值；长数组只给长度。"""
    from gguf import GGUFValueType

    types = field.types
    if not types:
        return None
    if types[0] == GGUFValueType.ARRAY:
        n = len(field.data)
        if n > 16:
            return f"<array len={n}>"
        sub = types[-1]
        vals = [field.parts[i] for i in field.data]
        if sub == GGUFValueType.STRING:
            return [bytes(v).decode("utf-8", "replace") for v in vals]
        return [v.tolist()[0] if hasattr(v, "tolist") else v for v in vals]
    part = field.parts[field.data[0]]
    if types[0] == GGUFValueType.STRING:
        return bytes(part).decode("utf-8", "replace")
    return part.tolist()[0] if hasattr(part, "tolist") else part


def layer_index(name: str) -> int | None:
    m = re.match(r"(?:blk|v\.blk)\.(\d+)\.", name)
    return int(m.group(1)) if m else None


def main(argv: list[str]) -> int:
    from gguf import GGUFReader

    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    if not path.exists():
        print(f"文件不存在：{path}")
        return 1

    reader = GGUFReader(str(path), "r")
    size = path.stat().st_size
    print(f"file     : {path.name}  ({size/1e9:.3f} GB)")
    print(f"tensors  : {len(reader.tensors)}")
    print()

    print("== 元数据关键字段")
    for key, field in reader.fields.items():
        if any(p in key for p in META_PATTERNS):
            print(f"  {key:52s} = {field_value(field)}")
    tok = reader.fields.get("tokenizer.ggml.tokens")
    if tok is not None:
        print(f"  {'tokenizer.ggml.tokens (词表大小)':52s} = {len(tok.data)}")
    print()

    rows = []
    qcount = collections.Counter()
    qbytes = collections.Counter()
    total_elems = 0
    total_bytes = 0
    for t in reader.tensors:
        shape = [int(x) for x in reversed(list(t.shape))]
        qtype = t.tensor_type.name
        n_el = int(t.n_elements)
        n_by = int(t.n_bytes)
        rows.append({"name": t.name, "shape": shape, "qtype": qtype,
                     "n_elements": n_el, "n_bytes": n_by, "data_offset": int(t.data_offset)})
        qcount[qtype] += 1
        qbytes[qtype] += n_by
        total_elems += n_el
        total_bytes += n_by

    print("== 量化类型统计")
    for q, c in qcount.most_common():
        print(f"  {q:8s} {c:4d} 个张量   {qbytes[q]/1e9:7.3f} GB")
    print(f"  合计     {len(rows):4d} 个张量   {total_bytes/1e9:7.3f} GB   "
          f"{total_elems/1e9:.3f} B 个参数（文件 {size/1e9:.3f} GB，其余为文件头）")
    print()

    layers = collections.defaultdict(list)
    others = []
    for r in rows:
        li = layer_index(r["name"])
        (layers[li] if li is not None else others).append(r)

    print(f"== 层数：{len(layers)}（编号 {min(layers) if layers else '-'} … {max(layers) if layers else '-'}）")
    print()
    print("== 不属于任何层的张量")
    for r in others:
        print(f"  {r['name']:44s} {str(r['shape']):22s} {r['qtype']}")
    print()

    for li in (0, 3):
        if li in layers:
            print(f"== 第 {li} 层的全部张量")
            for r in layers[li]:
                print(f"  {r['name']:44s} {str(r['shape']):22s} {r['qtype']}")
            print()

    # 每层张量名模式：看各层是否同构，以及节律
    patterns = collections.Counter()
    for li, rs in layers.items():
        key = tuple(sorted(re.sub(r"^(?:v\.)?blk\.\d+\.", "", r["name"]) for r in rs))
        patterns[key] += 1
    print(f"== 各层的张量组成共有 {len(patterns)} 种")
    for i, (key, cnt) in enumerate(patterns.most_common()):
        idx = sorted(li for li, rs in layers.items()
                     if tuple(sorted(re.sub(r'^(?:v\.)?blk\.\d+\.', '', r['name']) for r in rs)) == key)
        print(f"  组成 {i}：{cnt} 层，层号 {idx[:12]}{' …' if len(idx) > 12 else ''}")
        print(f"         {', '.join(key)}")
    print()

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{path.stem}.tensors.json"
    out.write_text(json.dumps({
        "file": path.name,
        "file_bytes": size,
        "n_tensors": len(rows),
        "shape_order": "row-major (reversed from GGUF ne order)",
        "tensors": rows,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

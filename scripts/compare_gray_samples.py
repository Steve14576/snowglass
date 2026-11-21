# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2,<3", "gguf==0.19.0", "threadpoolctl>=3,<4"]
# ///
"""两张真实矩阵的连续灰度小样。方法、边界与复现见 docs/weight_sample_comparison.md。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_info, threadpool_limits

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data/gguf/Qwen3.5-9B-Q4_K_M.gguf"
BASE = ROOT / "prototype/data/gray_samples"
TARGETS = {
    "attention": ("blk.3.attn_q.weight", (8192, 4096), "Q4_K"),
    "mlp": ("blk.0.ffn_down.weight", (4096, 12288), "Q6_K"),
}
GRID = (16, 16, 32)
K, SEED = 64, 20261121


def write_json(path, data):
    with Path(path).open("x", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class Progress:
    """阶段日志、五秒心跳及进程级超时，日志只落本次新目录。"""
    def __init__(self, folder, seconds):
        self.start = time.perf_counter()
        self.deadline = self.start + seconds
        self.label = "启动"
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.path = folder / "progress.jsonl"
        self.path.touch(exist_ok=False)
        threading.Thread(target=self.heartbeat, daemon=True).start()

    def emit(self, label, **data):
        self.label = label
        record = {"seconds": round(time.perf_counter() - self.start, 3), "stage": label, **data}
        text = json.dumps(record, ensure_ascii=False, allow_nan=False)
        with self.lock:
            print(text, flush=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(text + "\n")

    def heartbeat(self):
        while not self.stop.wait(5):
            if time.perf_counter() > self.deadline:
                self.emit("达到本次耗时上限，停止；未完成目录不作为结果", previous=self.label)
                os._exit(124)
            self.emit(self.label, heartbeat=True)


def decode(reader, key, progress):
    from gguf.quants import dequantize
    name, shape, fmt = TARGETS[key]
    tensor = next(t for t in reader.tensors if t.name == name)
    assert tuple(reversed(tensor.shape.tolist())) == shape
    assert tensor.tensor_type.name == fmt
    packed = hashlib.sha256(memoryview(np.ascontiguousarray(tensor.data)).cast("B")).hexdigest()
    begin = time.perf_counter()
    w = np.ascontiguousarray(dequantize(tensor.data, tensor.tensor_type).reshape(shape), dtype=np.float32)
    assert np.isfinite(w).all()
    info = {"key": key, "tensor": name, "shape": list(shape), "quantization": fmt,
            "packed_tensor_sha256": packed, "decode_seconds": time.perf_counter() - begin}
    progress.emit("解码完成", **info)
    return w, info


def pool(w, key):
    """整数分块覆盖全部元素；输出顺序固定 x,y,z，C-order。"""
    a = np.abs(w)
    if key == "attention":
        return a.reshape(16, 16, 32, 32, 128).mean(axis=(2, 4), dtype=np.float64).astype(np.float32)
    return a.reshape(16, 256, 16, 3, 32, 8).mean(axis=(1, 3, 5), dtype=np.float64).transpose(1, 0, 2).astype(np.float32)


def coarse(a):
    x, y, z = a.shape
    return a.reshape(x // 2, 2, y // 2, 2, z // 2, 2).mean(axis=(1, 3, 5)).astype(np.float32)


def factors(w, power, progress, seed=SEED, rank=K):
    width = min(rank + 16, min(w.shape))
    omega = np.random.default_rng(seed).standard_normal((w.shape[1], width), dtype=np.float32)
    progress.emit("SVD 随机投影", power=power, rank=rank)
    q, _ = np.linalg.qr(w @ omega)
    for i in range(power):
        z, _ = np.linalg.qr(w.T @ q)
        q, _ = np.linalg.qr(w @ z)
        progress.emit("SVD 正交幂迭代", iteration=i + 1, total=power)
    b = q.T @ w
    ub, s, vt = np.linalg.svd(b.astype(np.float64), full_matrices=False)
    return (q @ ub[:, :rank]).astype(np.float32), s[:rank], vt[:rank].astype(np.float32)


def reconstruct(fs, threshold):
    u, s, vt = fs
    keep = s > threshold
    return (u[:, keep] * s[keep].astype(np.float32)) @ vt[keep], int(keep.sum())


def gray(v, reference, gain=1.0, threshold=0.0, gamma=1.0):
    if not (np.isfinite([reference, gain, threshold, gamma]).all() and reference > 0
            and gain >= 0 and 0 <= threshold < 1 and gamma > 0):
        raise ValueError("无效灰度参数")
    return np.clip((gain * v / reference - threshold) / (1 - threshold), 0, 1) ** gamma


def stats(a):
    a = np.asarray(a, dtype=np.float64)
    return {"mean": float(a.mean()), "cv": float(a.std() / max(a.mean(), 1e-30)),
            "zero_fraction": float(np.mean(a == 0)), "saturated_fraction": float(np.mean(a >= 1)),
            "quantiles": np.quantile(a, [0, .1, .5, .9, .99, 1]).tolist()}


def sensitivity(channels, reference):
    records = []
    for resolution in ("fine", "coarse"):
        a, b, c = [channels[n] if resolution == "fine" else coarse(channels[n])
                   for n in ("full", "spectral", "residual")]
        variants = {"full": a, "spectral": b, **{f"blend_{r}": b + r * c for r in (0, .05, .15, .35, 1)}}
        for name, v in variants.items():
            for gain in (1, 2, 4):
                for threshold in (0, .1, .25):
                    for gamma in (.7, 1, 2):
                        records.append({"resolution": resolution, "variant": name, "gain": gain,
                                        "threshold": threshold, "gamma": gamma,
                                        **stats(gray(v, reference, gain, threshold, gamma))})
    return records


def tensor_run(w, info, folder, progress):
    key = info["key"]
    begin = time.perf_counter()
    progress.deadline = begin + 180
    full = pool(w, key)
    mean_abs = float(np.abs(w).mean(dtype=np.float64))
    np.testing.assert_allclose(full.mean(dtype=np.float64), mean_abs, rtol=1e-6)
    fro2 = float(np.einsum("ij,ij->", w, w, dtype=np.float64))
    threshold = np.sqrt(fro2 / w.size) * sum(np.sqrt(w.shape))
    t = time.perf_counter()
    f2 = factors(w, 2, progress)
    s2, k2 = reconstruct(f2, threshold)
    b2 = pool(s2, key)
    del s2
    time2 = time.perf_counter() - t
    t = time.perf_counter()
    f4 = factors(w, 4, progress)
    s4, k4 = reconstruct(f4, threshold)
    residual = w - s4
    error = max(float(np.max(np.abs(s4[i:i+128] + residual[i:i+128] - w[i:i+128])))
                for i in range(0, w.shape[0], 128))
    assert error < max(float(np.max(np.abs(w))) * 1e-5, 1e-7)
    b4, c4 = pool(s4, key), pool(residual, key)
    energy = float(np.sum(f4[1][:k4] ** 2) / fro2)
    del s4, residual
    time4 = time.perf_counter() - t
    threshold_checks = []
    for factor in (.8, 1, 1.2):
        s, count = reconstruct(f4, threshold * factor)
        values = pool(s, key)
        threshold_checks.append({"factor": factor, "retained": count, "rank_capped": count == K,
                                 "pooled_relative_l2_vs_default": float(np.linalg.norm(values - b4) / max(np.linalg.norm(b4), 1e-30)),
                                 "raw_statistics": stats(values)})
        del s
    channels = {"full": full, "spectral": b4, "residual": c4}
    for v in channels.values():
        assert v.shape == GRID and np.isfinite(v).all() and (v >= 0).all()
    convergence = {"power2_retained": k2, "power4_retained": k4,
                   "max_singular_relative_change": float(np.max(np.abs(f4[1] - f2[1]) / f4[1])),
                   "spectral_pool_relative_l2_change": float(np.linalg.norm(b4 - b2) / max(np.linalg.norm(b4), 1e-30)),
                   "power2_seconds": time2, "power4_seconds": time4}
    reference = 2 * mean_abs
    metadata = {**info, "grid": list(GRID), "weights_per_cell": w.size // int(np.prod(GRID)),
                "reference_white": reference, "reference_rule": "2 * mean(abs(original W)); shared by all variants",
                "spectral_threshold": float(threshold), "retained": k4, "rank_capped": k4 == K,
                "retained_energy_fraction": energy, "reconstruction_max_error": error,
                "convergence": convergence, "threshold_sensitivity": threshold_checks,
                "folding": ("rows = 16 segments * 512; x=segment, y=within-segment rows, z=input columns"
                            if key == "attention" else "columns = 48 * 256; x=3-segment group, y=output row group, z=within-segment column group"),
                "raw_stats": {n: stats(v) for n, v in channels.items()}}
    npz = folder / f"{key}.npz"
    with npz.open("xb") as file:
        np.savez_compressed(file, **channels, singular_values=f4[1], singular_values_power2=f2[1],
                            u=f4[0], vt=f4[2], spectral_power2=b2)
    metadata["npz_sha256"] = hashlib.sha256(npz.read_bytes()).hexdigest()
    payload = {**metadata, "channels": {n: v.ravel().tolist() for n, v in channels.items()},
               "gray_fixture": {"input": [0, reference * .25, reference, reference * 2],
                                "gain": 1.3, "threshold": .1, "gamma": .7,
                                "output": gray(np.array([0, reference*.25, reference, reference*2]), reference, 1.3, .1, .7).tolist()}}
    write_json(folder / f"{key}.json", payload)
    write_json(folder / f"{key}.sensitivity.json", sensitivity(channels, reference))
    metadata["total_seconds"] = time.perf_counter() - begin
    progress.emit("张量完成", **metadata)
    return metadata


def self_test():
    # 小数组验证端点、灰度参数拒绝与相邻池化；不读大权重。
    np.testing.assert_allclose(gray(np.array([0., .25, .5, 1.]), 1), [0, .25, .5, 1])
    np.testing.assert_allclose(gray(np.array([0., .25, .5, 1.]), 1, 1, .5), [0, 0, 0, 1])
    a = np.arange(64, dtype=np.float32).reshape(4, 4, 4)
    np.testing.assert_allclose(coarse(a).mean(), a.mean())
    for bad in ((0, 1, 0, 1), (1, 1, 1, 1), (1, 1, 0, 0)):
        try:
            gray(a, *bad)
        except ValueError:
            continue
        raise AssertionError("未拒绝无效参数")
    # 一次空间脉冲的折叠位置验证，确保无重复、无遗漏。
    for key, (_, shape, _) in TARGETS.items():
        a = np.zeros(shape, dtype=np.float32)
        a[0, 0] = 1
        a[-1, -1] = 2
        b = pool(a, key)
        count = a.size // b.size
        np.testing.assert_allclose(b.sum() * count, 3)
        np.testing.assert_allclose(b[0, 0, 0] * count, 1)
        np.testing.assert_allclose(b[-1, -1, -1] * count, 2)
        del a
    print("基础测试通过：曲线端点、输入边界、池化守恒、两种折叠首尾归属", flush=True)


def check(folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    for sample in manifest["samples"]:
        key = sample["key"]
        payload = json.loads((folder / f"{key}.json").read_text(encoding="utf-8"))
        assert hashlib.sha256((folder / f"{key}.npz").read_bytes()).hexdigest() == sample["npz_sha256"]
        with np.load(folder / f"{key}.npz", allow_pickle=False) as z:
            for name in ("full", "spectral", "residual"):
                a = np.asarray(payload["channels"][name], dtype=np.float32).reshape(GRID)
                np.testing.assert_array_equal(a, z[name])
                assert np.isfinite(a).all() and (a >= 0).all()
            np.testing.assert_allclose(z["full"].mean() * 2, sample["reference_white"], rtol=1e-6)
            assert sample["retained"] == int((z["singular_values"] > sample["spectral_threshold"]).sum())
        print(json.dumps({"verified": key, "retained": sample["retained"], "energy": sample["retained_energy_fraction"],
                          "rank_capped": sample["rank_capped"], "convergence": sample["convergence"]}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--probe", action="store_true")
    group.add_argument("--run", action="store_true")
    group.add_argument("--check", type=Path)
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.check:
        check(args.check.resolve())
        return
    if args.self_test:
        self_test()
        return
    from gguf import GGUFReader
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    folder = BASE / (("probe-" if args.probe else "run-") + stamp)
    folder.mkdir(parents=True, exist_ok=False)
    progress = Progress(folder, 60 if args.probe else 180)
    try:
        reader = GGUFReader(str(SOURCE), "r")
        with threadpool_limits(limits=4):
            environment = {"python": sys.version, "platform": platform.platform(),
                           "packages": {n: importlib.metadata.version(n) for n in ("numpy", "gguf", "threadpoolctl")},
                           "blas": threadpool_info()}
            progress.emit("运行环境", **environment)
            if args.probe:
                w, info = decode(reader, "attention", progress)
                rng = np.random.default_rng(SEED)
                omega = rng.standard_normal((w.shape[1], K + 16), dtype=np.float32)
                t = time.perf_counter()
                y = w @ omega
                mat_time = time.perf_counter() - t
                t = time.perf_counter()
                b = pool(w, "attention")
                pool_time = time.perf_counter() - t
                result = {"status": "probe_complete", "source": str(SOURCE.relative_to(ROOT)),
                          "source_bytes": SOURCE.stat().st_size, "tensor": info,
                          "matmul_seconds": mat_time, "pool_seconds": pool_time,
                          "working_matrix_mib": w.nbytes / 1024**2, "environment": environment,
                          "finite": bool(np.isfinite(y).all() and np.isfinite(b).all())}
                write_json(folder / "probe.json", result)
                progress.emit("探针完成", **result)
            else:
                samples = []
                for key in TARGETS:
                    progress.deadline = time.perf_counter() + 180
                    w, info = decode(reader, key, progress)
                    samples.append(tensor_run(w, info, folder, progress))
                    del w
                write_json(folder / "manifest.json", {"schema": "snowglass.gray-samples.v1", "status": "complete",
                    "created": stamp, "source": str(SOURCE.relative_to(ROOT)), "source_bytes": SOURCE.stat().st_size,
                    "source_mtime_ns": SOURCE.stat().st_mtime_ns, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "method": {"rank_limit": K, "oversampling": 16, "seed": SEED, "power_iterations": 4,
                               "default_blend": .15, "no_random_point_sampling": True, "no_gray_floor": True},
                    "environment": environment, "samples": samples})
                check(folder)
            progress.emit("结果目录", directory=str(folder.relative_to(ROOT)))
    except Exception as error:
        progress.emit("运行失败", error=repr(error))
        raise
    finally:
        progress.stop.set()


if __name__ == "__main__":
    main()

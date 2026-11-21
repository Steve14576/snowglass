# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2,<3", "gguf==0.19.0", "threadpoolctl>=3,<4"]
# ///
"""不覆盖首批结果的收敛核验；同两张矩阵，256 个方向，8/12 次幂迭代。

方法与首批证据见 docs/weight_sample_comparison.md。复用只读的 compare_gray_samples.py。
"""
import hashlib
import importlib.metadata
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from gguf import GGUFReader
from threadpoolctl import threadpool_limits, threadpool_info

import compare_gray_samples as c

RANK = 256


def main():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    folder = c.BASE / ("run-" + stamp)
    folder.mkdir(parents=True, exist_ok=False)
    progress = c.Progress(folder, 180)
    samples = []
    try:
        reader = GGUFReader(str(c.SOURCE), "r")
        with threadpool_limits(limits=4):
            for key in c.TARGETS:
                progress.deadline = time.perf_counter() + 180
                start = time.perf_counter()
                w, info = c.decode(reader, key, progress)
                full = c.pool(w, key)
                mean_abs = float(np.abs(w).mean(dtype=np.float64))
                np.testing.assert_allclose(full.mean(dtype=np.float64), mean_abs, rtol=1e-6)
                fro2 = float(np.einsum("ij,ij->", w, w, dtype=np.float64))
                threshold = np.sqrt(fro2 / w.size) * sum(np.sqrt(w.shape))
                first = c.factors(w, 8, progress, rank=RANK)
                reconstruction, k8 = c.reconstruct(first, threshold)
                b8 = c.pool(reconstruction, key)
                del reconstruction
                final = c.factors(w, 12, progress, rank=RANK)
                reconstruction, count = c.reconstruct(final, threshold)
                residual = w - reconstruction
                error = max(float(np.max(np.abs(reconstruction[i:i+128] + residual[i:i+128] - w[i:i+128])))
                            for i in range(0, w.shape[0], 128))
                assert error < 1e-6
                b, r = c.pool(reconstruction, key), c.pool(residual, key)
                del reconstruction, residual
                checks = []
                for factor in (.8, 1, 1.2):
                    value, k = c.reconstruct(final, threshold * factor)
                    pooled = c.pool(value, key)
                    checks.append({"factor": factor, "retained": k, "rank_capped": k == RANK,
                                   "pooled_relative_l2_vs_default": float(np.linalg.norm(pooled-b)/np.linalg.norm(b)),
                                   "raw_statistics": c.stats(pooled)})
                    del value
                channels = {"full": full, "spectral": b, "residual": r}
                for value in channels.values():
                    assert value.shape == c.GRID and np.isfinite(value).all() and (value >= 0).all()
                reference = 2 * mean_abs
                meta = {**info, "grid": list(c.GRID), "weights_per_cell": w.size // b.size,
                        "reference_white": reference, "spectral_threshold": float(threshold),
                        "retained": count, "rank_capped": count == RANK,
                        "retained_energy_fraction": float(np.sum(final[1][:count]**2)/fro2),
                        "reconstruction_max_error": error, "threshold_sensitivity": checks,
                        "convergence": {"power8_retained": k8, "power12_retained": count,
                            "max_singular_relative_change": float(np.max(np.abs(final[1]-first[1])/final[1])),
                            "spectral_pool_relative_l2_change": float(np.linalg.norm(b-b8)/np.linalg.norm(b))},
                        "raw_stats": {name: c.stats(v) for name, v in channels.items()},
                        "total_seconds": time.perf_counter()-start}
                npz = folder / f"{key}.npz"
                with npz.open("xb") as f:
                    np.savez_compressed(f, **channels, singular_values=final[1], singular_values_power8=first[1],
                                        u=final[0], vt=final[2], spectral_power8=b8)
                meta["npz_sha256"] = hashlib.sha256(npz.read_bytes()).hexdigest()
                fixture = [0, reference*.25, reference, reference*2]
                c.write_json(folder / f"{key}.json", {**meta,
                    "channels": {name: v.ravel().tolist() for name, v in channels.items()},
                    "gray_fixture": {"input": fixture, "gain": 1.3, "threshold": .1, "gamma": .7,
                        "output": c.gray(np.array(fixture), reference, 1.3, .1, .7).tolist()}})
                c.write_json(folder / f"{key}.sensitivity.json", c.sensitivity(channels, reference))
                progress.emit("高精度核验完成", **meta)
                samples.append(meta)
                del w, first, final
            c.write_json(folder / "manifest.json", {"schema": "snowglass.gray-samples.v1", "status": "complete",
                "created": stamp, "source": str(c.SOURCE.relative_to(c.ROOT)), "source_bytes": c.SOURCE.stat().st_size,
                "method": {"rank_limit": RANK, "oversampling": 16, "seed": c.SEED, "power_iterations": 12,
                           "convergence_comparison_power": 8, "default_blend": .15, "no_random_point_sampling": True,
                           "no_gray_floor": True}, "samples": samples,
                "environment": {"python": sys.version, "blas": threadpool_info(),
                                "packages": {n: importlib.metadata.version(n) for n in ("numpy", "gguf", "threadpoolctl")}},
                "script_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (Path(__file__), Path(c.__file__))}})
            c.check(folder)
            progress.emit("结果目录", directory=str(folder.relative_to(c.ROOT)))
    finally:
        progress.stop.set()


if __name__ == "__main__":
    main()

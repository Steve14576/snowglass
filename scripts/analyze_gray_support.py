# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2,<3"]
# ///
"""只分析已有谱池化缓存的空间选取；不读权重、不求 SVD。

说明及结果：docs/weight_sample_comparison.md 的“第二轮”。每次输出新目录。
"""
from __future__ import annotations
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "prototype/data/gray_samples/run-20261121-211150-652530"
THRESHOLDS = [0, .05, .08, .09, .1, .11, .12, .13, .15, .18, .19, .2,
              .21, .22, .23, .24, .25, .26, .27, .28, .3, .34, .4]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coarse(a):
    x, y, z = a.shape
    return a.reshape(x//2, 2, y//2, 2, z//2, 2).mean(axis=(1, 3, 5))


def jaccard(a, b):
    union = int(np.count_nonzero(a | b))
    return float(np.count_nonzero(a & b) / union) if union else None


def regions(mask):
    """六邻接只用于描述，不删除任何连通块，不作形态学操作。"""
    nx, ny, nz = mask.shape
    flat = mask.ravel()
    visited = np.zeros(flat.size, dtype=bool)
    groups = []
    yz = ny*nz
    for start in np.flatnonzero(flat):
        if visited[start]:
            continue
        stack = [int(start)]
        visited[start] = True
        count, lo, hi = 0, [nx, ny, nz], [0, 0, 0]
        while stack:
            i = stack.pop()
            x, remainder = divmod(i, yz)
            y, z = divmod(remainder, nz)
            count += 1
            for axis, v in enumerate((x, y, z)):
                lo[axis], hi[axis] = min(lo[axis], v), max(hi[axis], v)
            neighbors = []
            if x: neighbors.append(i-yz)
            if x+1<nx: neighbors.append(i+yz)
            if y: neighbors.append(i-nz)
            if y+1<ny: neighbors.append(i+nz)
            if z: neighbors.append(i-1)
            if z+1<nz: neighbors.append(i+1)
            for other in neighbors:
                if flat[other] and not visited[other]:
                    visited[other] = True
                    stack.append(other)
        groups.append({"cells": count, "bounds": [lo, hi]})
    groups.sort(key=lambda v: v["cells"], reverse=True)
    return groups


def measure(x, threshold):
    mask = x > threshold
    count = int(mask.sum())
    groups = regions(mask)
    assert sum(g["cells"] for g in groups) == count
    layer_counts = [mask.sum(axis=tuple(j for j in range(3) if j != axis)).tolist() for axis in range(3)]
    assert all(sum(v) == count for v in layer_counts)
    g = np.clip(x, 0, 1)
    legacy = np.clip((x-threshold)/(1-threshold), 0, 1)
    return {"threshold": threshold, "cells": mask.size, "retained": count,
            "occupied_fraction": count/mask.size, "axis_counts": layer_counts,
            "component_count": len(groups), "largest_component": groups[0] if groups else None,
            "largest_fraction_of_retained": groups[0]["cells"]/count if count else None,
            "all_component_sizes": [v["cells"] for v in groups],
            "original_selected_mean_gray": float(g[mask].mean()) if count else None,
            "legacy_selected_mean_gray": float(legacy[mask].mean()) if count else None,
            "threshold_minus_001_jaccard": jaccard(mask, x > max(0,threshold-.01)),
            "threshold_plus_001_jaccard": jaccard(mask, x > threshold+.01)}


def self_test():
    a = np.zeros((3,3,3), dtype=bool)
    assert regions(a) == [] and jaccard(a,a) is None
    a[0,0,0] = a[1,1,1] = True
    assert len(regions(a)) == 2, "对角接触不算六邻接"
    a[1,0,0] = a[1,1,0] = True
    assert len(regions(a)) == 1
    a = np.zeros((2,2,2)); a[0,0,0] = .25; a[1,1,1] = .3
    assert measure(a,.25)["retained"] == 1, "门槛相等不保留"
    assert measure(a,0)["retained"] == 2
    assert np.isclose(coarse(np.arange(64.).reshape(4,4,4)).mean(),31.5)


def main():
    start = time.perf_counter()
    self_test()
    folder = SOURCE.parent / ("support-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    folder.mkdir(exist_ok=False)
    tracked = [SOURCE / "manifest.json"] + [SOURCE / f"{key}.{ext}" for key in ("attention","mlp") for ext in ("json","npz")]
    before = {str(p.relative_to(ROOT)):sha(p) for p in tracked}
    results = []
    for key in ("attention", "mlp"):
        doc = json.loads((SOURCE/f"{key}.json").read_text(encoding="utf-8"))
        dims = tuple(doc["grid"])
        raw = np.asarray(doc["channels"]["spectral"], dtype=np.float64).reshape(dims)
        with np.load(SOURCE/f"{key}.npz", allow_pickle=False) as z:
            np.testing.assert_array_equal(raw,z["spectral"])
            previous = z["spectral_power8"].astype(np.float64)
        x = raw / doc["reference_white"]
        x8 = previous / doc["reference_white"]
        c, c8 = coarse(x), coarse(x8)
        samples = {"fine":[], "coarse":[]}
        for resolution, values, earlier in (("fine",x,x8),("coarse",c,c8)):
            for tau in THRESHOLDS:
                record = measure(values,tau)
                record["power8_vs_power12_jaccard"] = jaccard(values>tau,earlier>tau)
                expanded = (c>tau).repeat(2,0).repeat(2,1).repeat(2,2)
                record["fine_vs_expanded_coarse_jaccard"] = jaccard(x>tau,expanded)
                samples[resolution].append(record)
        results.append({"key":key,"grid":list(dims),"normalized_range":[float(x.min()),float(x.max())],
                        "reference_white":doc["reference_white"],"measurements":samples})
        print(json.dumps({"tensor":key,"seconds":round(time.perf_counter()-start,2),
                          "examples":[r for r in samples["fine"] if r["threshold"] in (.1,.24,.25,.26)]},ensure_ascii=False),flush=True)
    after = {str(p.relative_to(ROOT)):sha(p) for p in tracked}
    assert before == after, "源缓存意外变化"
    report = {"schema":"snowglass.support-analysis.v1","source":str(SOURCE.relative_to(ROOT)),
              "source_hashes":before,"script_sha256":sha(Path(__file__)),"thresholds":THRESHOLDS,
              "criterion":"spectral/reference_white > threshold; not an importance or significance test",
              "connectivity":6,"numpy":np.__version__,"results":results,
              "elapsed_seconds":time.perf_counter()-start}
    with (folder/"analysis.json").open("x",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,allow_nan=False,indent=2)
    # 小型跨语言验证例，不依赖用浏览器复算大张量。
    test = np.zeros((3,3,3));test[0,0,0]=.25;test[1,1,1]=.3
    with (folder/"fixture.json").open("x",encoding="utf-8") as f:
        json.dump({"dims":[3,3,3],"values":test.ravel().tolist(),"expected":measure(test,.2)},f,allow_nan=False)
    print(json.dumps({"output":str(folder),"source_unchanged":True,"seconds":report["elapsed_seconds"]},ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()

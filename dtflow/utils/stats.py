"""数值分布的纯函数: 分位数 / 标准差 / 摘要 / 等宽直方图。

dt describe 与 token-stats 共用 (后者保留取整的输出), 不 import CLI 层。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

PERCENTILES = (25, 50, 75, 90, 99)


def percentile(sorted_vals: Sequence[float], p: float) -> float:
    """线性插值分位数; sorted_vals 必须已升序。空序列返回 0.0。"""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    idx = (n - 1) * p / 100
    lower = int(idx)
    upper = min(lower + 1, n - 1)
    weight = idx - lower
    return sorted_vals[lower] * (1 - weight) + sorted_vals[upper] * weight


def std(vals: Sequence[float], mean: float) -> float:
    """总体标准差; 少于 2 个值为 0.0。"""
    if len(vals) < 2:
        return 0.0
    return (sum((x - mean) ** 2 for x in vals) / len(vals)) ** 0.5


def summarize(vals: Sequence[float]) -> Dict[str, Optional[float]]:
    """n / min / max / mean / std / p25 / p50 / p75 / p90 / p99; 空序列除 n=0 外全为 None。"""
    if not vals:
        return {"n": 0, "min": None, "max": None, "mean": None, "std": None} | {
            f"p{p}": None for p in PERCENTILES
        }
    s = sorted(vals)
    mean = sum(s) / len(s)
    integral = all(float(v).is_integer() for v in s)  # 整数数据的 min/max 别输出 2.0
    out: Dict[str, Optional[float]] = {
        "n": len(s),
        "min": int(s[0]) if integral else s[0],
        "max": int(s[-1]) if integral else s[-1],
        "mean": round(mean, 4),
        "std": round(std(s, mean), 4),
    }
    for p in PERCENTILES:
        out[f"p{p}"] = round(percentile(s, p), 4)
    return out


def histogram(vals: Sequence[float], bins: int = 10) -> List[Tuple[float, float, int]]:
    """等宽直方图 [(lo, hi, count)…]; 全部相等时只有一个桶。最后一桶右闭。"""
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if lo == hi or bins < 1:
        return [(lo, hi, len(vals))]
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        i = min(int((v - lo) / width), bins - 1)
        counts[i] += 1
    return [(lo + i * width, lo + (i + 1) * width, c) for i, c in enumerate(counts)]


def render_histogram_lines(hist: Sequence[Tuple[float, float, int]], width: int = 30) -> List[str]:
    """直方图 → 文本行 ``[lo, hi)  count  ████``; 桶边界按整数或 2 位小数显示。"""
    if not hist:
        return []
    peak = max(c for _, _, c in hist) or 1
    is_int = all(float(lo).is_integer() and float(hi).is_integer() for lo, hi, _ in hist)

    def num(v: float) -> str:
        return f"{int(v)}" if is_int else f"{v:.2f}"

    labels = [
        f"[{num(lo)}, {num(hi)}{']' if i == len(hist) - 1 else ')'}"
        for i, (lo, hi, _) in enumerate(hist)
    ]
    lw = max(len(x) for x in labels)
    cw = max(len(str(c)) for _, _, c in hist)
    return [
        f"{lab:<{lw}}  {c:>{cw}}  {'█' * round(c / peak * width)}"
        for lab, (_, _, c) in zip(labels, hist, strict=True)
    ]

"""
transform.py -- value transforms applied before scaling.

Two families:
  * per-series sequence transforms (cumulative sum, rolling mean, ...) that
    preserve row order, used by line / area / scatter charts;
  * group aggregation (sum / mean / count / ...) used by bar charts.

Missing values are carried as None and skipped rather than treated as zero,
so a gap in the CSV does not silently drag a cumulative curve down.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .spec import (T_CUMMAX, T_CUMSUM, T_INDEX100, T_NONE, T_ROLLMEAN, T_ROLLSUM)

Num = Optional[float]


def _filled(values: Sequence[Num]) -> List[float]:
    """Forward-fill for transforms that need a continuous stream."""
    out: List[float] = []
    last = 0.0
    for v in values:
        if v is not None:
            last = v
        out.append(last)
    return out


def cumulative_sum(values: Sequence[Num]) -> List[Num]:
    run = 0.0
    out: List[Num] = []
    for v in values:
        if v is not None:
            run += v
        out.append(run)
    return out


def cumulative_max(values: Sequence[Num]) -> List[Num]:
    run: Optional[float] = None
    out: List[Num] = []
    for v in values:
        if v is not None:
            run = v if run is None else max(run, v)
        out.append(run)
    return out


def rolling_mean(values: Sequence[Num], window: int) -> List[Num]:
    window = max(1, int(window))
    out: List[Num] = []
    for i in range(len(values)):
        lo = max(0, i - window + 1)
        chunk = [v for v in values[lo:i + 1] if v is not None]
        out.append(sum(chunk) / len(chunk) if chunk else None)
    return out


def rolling_sum(values: Sequence[Num], window: int) -> List[Num]:
    window = max(1, int(window))
    out: List[Num] = []
    for i in range(len(values)):
        lo = max(0, i - window + 1)
        chunk = [v for v in values[lo:i + 1] if v is not None]
        out.append(sum(chunk) if chunk else None)
    return out


def index_to_100(values: Sequence[Num]) -> List[Num]:
    base: Optional[float] = None
    for v in values:
        if v is not None and v != 0:
            base = v
            break
    if base is None:
        return list(values)
    return [None if v is None else v / base * 100.0 for v in values]


def apply_transform(values: Sequence[Num], kind: str, window: int = 8) -> List[Num]:
    if kind == T_CUMSUM:
        return cumulative_sum(values)
    if kind == T_CUMMAX:
        return cumulative_max(values)
    if kind == T_ROLLMEAN:
        return rolling_mean(values, window)
    if kind == T_ROLLSUM:
        return rolling_sum(values, window)
    if kind == T_INDEX100:
        return index_to_100(values)
    return list(values)


# ---------------------------------------------------------------------------
# aggregation (bar charts)
# ---------------------------------------------------------------------------
def _median(xs: List[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0


_AGG: Dict[str, Callable[[List[float]], float]] = {
    "sum": lambda xs: sum(xs),
    "mean": lambda xs: sum(xs) / len(xs) if xs else 0.0,
    "median": _median,
    "count": lambda xs: float(len(xs)),
    "min": lambda xs: min(xs) if xs else 0.0,
    "max": lambda xs: max(xs) if xs else 0.0,
}


def aggregate_groups(labels: Sequence[str], values: Sequence[Num],
                     how: str = "sum") -> List[Tuple[str, float]]:
    """Group by label preserving first-seen order, then aggregate."""
    order: List[str] = []
    buckets: Dict[str, List[float]] = {}
    for lab, val in zip(labels, values):
        if lab not in buckets:
            buckets[lab] = []
            order.append(lab)
        if val is not None:
            buckets[lab].append(val)
    fn = _AGG.get(how, _AGG["sum"])
    return [(lab, fn(buckets[lab])) for lab in order]


def sort_rows(keys: Sequence[Num], ascending: bool = True) -> List[int]:
    """Stable argsort tolerant of Nones (which sink to the end)."""
    idx = list(range(len(keys)))
    big = math.inf

    def keyf(i: int):
        v = keys[i]
        return (v if v is not None else big)

    idx.sort(key=keyf, reverse=not ascending)
    return idx

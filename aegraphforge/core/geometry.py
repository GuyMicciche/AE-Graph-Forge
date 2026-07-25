"""
geometry.py -- pixel path construction for After Effects shape layers.

Verified against Source3.jsx / Source5.jsx with ZERO error:

    out_tangent[i] = (P[i+1] - P[i-1]) / 6
    in_tangent[i]  = -out_tangent[i]
    endpoints      = [0, 0]
    ARC[i]         = cumulative CHORD length / total chord length

That is a uniform Catmull-Rom converted to cubic Bezier control offsets,
which is exactly what AE's Shape.inTangents / outTangents expect (they are
offsets *relative to* the vertex, not absolute control points).

ARC feeds the Trim Paths "End" property. AE trims by true arc length, so
`arc_mode="bezier"` is offered as a more precise alternative; "chord" is the
default because it reproduces the reference scripts exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

Pt = Tuple[float, float]


# ---------------------------------------------------------------------------
# tangents
# ---------------------------------------------------------------------------
def catmull_rom_tangents(points: Sequence[Pt], smooth: bool = True
                         ) -> Tuple[List[Pt], List[Pt]]:
    """Return (in_tangents, out_tangents) as vertex-relative offsets."""
    n = len(points)
    ins: List[Pt] = [(0.0, 0.0)] * n
    outs: List[Pt] = [(0.0, 0.0)] * n
    if not smooth or n < 3:
        return ins, outs
    ins = list(ins)
    outs = list(outs)
    for i in range(1, n - 1):
        ox = (points[i + 1][0] - points[i - 1][0]) / 6.0
        oy = (points[i + 1][1] - points[i - 1][1]) / 6.0
        outs[i] = (ox, oy)
        ins[i] = (-ox, -oy)
    return ins, outs


# ---------------------------------------------------------------------------
# arc length
# ---------------------------------------------------------------------------
def _bezier_point(p0: Pt, c1: Pt, c2: Pt, p3: Pt, t: float) -> Pt:
    u = 1.0 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * p0[0] + b * c1[0] + c * c2[0] + d * p3[0],
            a * p0[1] + b * c1[1] + c * c2[1] + d * p3[1])


def segment_lengths(points: Sequence[Pt], ins: Sequence[Pt], outs: Sequence[Pt],
                    mode: str = "chord", steps: int = 24) -> List[float]:
    n = len(points)
    lens: List[float] = []
    for i in range(n - 1):
        p0, p3 = points[i], points[i + 1]
        if mode == "chord":
            lens.append(math.hypot(p3[0] - p0[0], p3[1] - p0[1]))
            continue
        c1 = (p0[0] + outs[i][0], p0[1] + outs[i][1])
        c2 = (p3[0] + ins[i + 1][0], p3[1] + ins[i + 1][1])
        total = 0.0
        prev = p0
        for s in range(1, steps + 1):
            cur = _bezier_point(p0, c1, c2, p3, s / steps)
            total += math.hypot(cur[0] - prev[0], cur[1] - prev[1])
            prev = cur
        lens.append(total)
    return lens


def arc_fractions(points: Sequence[Pt], ins: Sequence[Pt], outs: Sequence[Pt],
                  mode: str = "chord", decimals: int = 5) -> List[float]:
    """Cumulative 0..1 length fraction at each vertex (len == len(points))."""
    if len(points) < 2:
        return [0.0] * len(points)
    lens = segment_lengths(points, ins, outs, mode)
    total = sum(lens)
    if total <= 0:
        n = len(points)
        return [i / (n - 1) for i in range(n)]
    out = [0.0]
    run = 0.0
    for L in lens:
        run += L
        out.append(round(run / total, decimals))
    out[-1] = 1.0
    return out


# ---------------------------------------------------------------------------
# path bundle
# ---------------------------------------------------------------------------
@dataclass
class PathGeometry:
    """Everything the JSX needs for one drawn line."""
    points: List[Pt] = field(default_factory=list)
    in_tangents: List[Pt] = field(default_factory=list)
    out_tangents: List[Pt] = field(default_factory=list)
    arc: List[float] = field(default_factory=list)
    closed: bool = False

    @property
    def n(self) -> int:
        return len(self.points)

    @property
    def xs(self) -> List[float]:
        return [p[0] for p in self.points]

    @property
    def ys(self) -> List[float]:
        return [p[1] for p in self.points]

    # -- sampling used by the previewer to draw a partial reveal ---------
    def point_at_progress(self, progress: float) -> Pt:
        """Linear interpolation by *index*, matching the tip-dot expression."""
        n = self.n
        if n == 0:
            return (0.0, 0.0)
        if n == 1:
            return self.points[0]
        idx = (progress / 100.0) * (n - 1)
        i = int(math.floor(min(max(idx, 0.0), n - 2)))
        frac = idx - i
        p, q = self.points[i], self.points[i + 1]
        return (p[0] + (q[0] - p[0]) * frac, p[1] + (q[1] - p[1]) * frac)

    def trim_at_progress(self, progress: float) -> float:
        """0..100 Trim Paths End value, matching the trim expression."""
        n = self.n
        if n < 2:
            return 100.0
        idx = (progress / 100.0) * (n - 1)
        i = int(math.floor(min(max(idx, 0.0), n - 2)))
        frac = idx - i
        return (self.arc[i] + (self.arc[i + 1] - self.arc[i]) * frac) * 100.0


def build_path(points: Sequence[Pt], smooth: bool = True,
               arc_mode: str = "chord", closed: bool = False) -> PathGeometry:
    pts = [(float(x), float(y)) for x, y in points]
    ins, outs = catmull_rom_tangents(pts, smooth=smooth)
    arc = arc_fractions(pts, ins, outs, mode=arc_mode)
    return PathGeometry(points=pts, in_tangents=ins, out_tangents=outs,
                        arc=arc, closed=closed)


# ---------------------------------------------------------------------------
# rounding helpers so emitted JSX stays compact and diffable
# ---------------------------------------------------------------------------
def r2(v: float) -> float:
    return round(v + 0.0, 2)


def r6(v: float) -> float:
    """Six significant figures, matching the reference tangent arrays."""
    if v == 0:
        return 0.0
    return float(f"{v:.6g}")


def fmt_num(v: float) -> str:
    """Emit the shortest exact-enough literal (no trailing .0 noise)."""
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(round(v, 6))


def fmt_pairs(pairs: Sequence[Pt], rounder=r2) -> str:
    return "[" + ",".join(f"[{fmt_num(rounder(x))},{fmt_num(rounder(y))}]"
                          for x, y in pairs) + "]"


def fmt_list(vals: Sequence[float], rounder=r2) -> str:
    return "[" + ",".join(fmt_num(rounder(v)) for v in vals) + "]"

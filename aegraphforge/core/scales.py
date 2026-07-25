"""
scales.py -- data-space to pixel-space mapping and tick generation.

Pixel convention matches the reference scripts exactly:
    x_pix = PLOT_L + t * (PLOT_R - PLOT_L)
    y_pix = PLOT_B + t * (PLOT_T - PLOT_B)     # PLOT_T < PLOT_B, so this flips
where t is the normalised 0..1 position of the value inside [vmin, vmax].
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .spec import AxisSpec, SCALE_LINEAR, SCALE_LOG, SCALE_SQRT

_LOG_FLOOR = 1e-9


@dataclass
class Scale:
    vmin: float
    vmax: float
    p0: float          # pixel at vmin
    p1: float          # pixel at vmax
    kind: str = SCALE_LINEAR

    # -- forward ---------------------------------------------------------
    def _fwd(self, v: float) -> float:
        if self.kind == SCALE_LOG:
            return math.log10(max(v, _LOG_FLOOR))
        if self.kind == SCALE_SQRT:
            return math.copysign(math.sqrt(abs(v)), v)
        return v

    def norm(self, v: float) -> float:
        a, b = self._fwd(self.vmin), self._fwd(self.vmax)
        if b == a:
            return 0.0
        return (self._fwd(v) - a) / (b - a)

    def px(self, v: float) -> float:
        return self.p0 + self.norm(v) * (self.p1 - self.p0)

    def px_clamped(self, v: float) -> float:
        t = min(max(self.norm(v), 0.0), 1.0)
        return self.p0 + t * (self.p1 - self.p0)

    # -- inverse (used by the previewer's cursor readout) -----------------
    def value_at_px(self, p: float) -> float:
        if self.p1 == self.p0:
            return self.vmin
        t = (p - self.p0) / (self.p1 - self.p0)
        a, b = self._fwd(self.vmin), self._fwd(self.vmax)
        f = a + t * (b - a)
        if self.kind == SCALE_LOG:
            return 10.0 ** f
        if self.kind == SCALE_SQRT:
            return math.copysign(f * f, f)
        return f


def make_scale(axis: AxisSpec, p0: float, p1: float,
               data_lo: float, data_hi: float) -> Scale:
    """Resolve auto min/max against the data, then build the scale."""
    lo = data_lo if axis.auto_min else axis.vmin
    hi = data_hi if axis.auto_max else axis.vmax
    if axis.scale == SCALE_LOG:
        lo = max(lo, _LOG_FLOOR)
        hi = max(hi, lo * 10)
    if hi <= lo:
        hi = lo + (abs(lo) * 0.1 or 1.0)
    return Scale(vmin=lo, vmax=hi, p0=p0, p1=p1, kind=axis.scale)


# ---------------------------------------------------------------------------
# tick generation
# ---------------------------------------------------------------------------
def _nice_num(x: float, round_it: bool) -> float:
    if x <= 0:
        return 1.0
    exp = math.floor(math.log10(x))
    frac = x / (10 ** exp)
    if round_it:
        nf = 1.0 if frac < 1.5 else 2.0 if frac < 3.0 else 5.0 if frac < 7.0 else 10.0
    else:
        nf = 1.0 if frac <= 1.0 else 2.0 if frac <= 2.0 else 5.0 if frac <= 5.0 else 10.0
    return nf * (10 ** exp)


def nice_bounds(lo: float, hi: float, target: int = 6) -> Tuple[float, float, float]:
    """Return (nice_lo, nice_hi, step) covering [lo, hi].

    Deliberately skips the extra nice_num() on the raw range that the classic
    Heckbert routine applies. That pre-rounding inflates the span and pushes
    the tick count well below the target (a 0..5872 axis came out as
    0/2000/4000/6000 instead of the 1000-step ladder you actually want)."""
    if hi <= lo:
        hi = lo + (abs(lo) * 0.1 or 1.0)
    target = max(2, target)
    step = _nice_num((hi - lo) / (target - 1), True)
    if step <= 0:
        step = 1.0
    nlo = math.floor(lo / step + 1e-9) * step
    nhi = math.ceil(hi / step - 1e-9) * step
    return nlo, nhi, step


def ticks_from_step(lo: float, hi: float, step: float) -> List[float]:
    """Ticks on an exact step grid, so bounds and ticks can never disagree."""
    if step <= 0 or hi <= lo:
        return [lo, hi]
    out: List[float] = []
    k = math.ceil(lo / step - 1e-9)
    guard = 0
    while k * step <= hi + step * 1e-6 and guard < 1000:
        v = k * step
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        k += 1
        guard += 1
    return out or [lo, hi]


def zero_baseline_ok(lo: float, hi: float) -> bool:
    """True when anchoring the axis at zero will not squash the data."""
    if lo < 0 or hi <= 0:
        return False
    return lo <= 0.35 * hi


def resolve_range(axis: AxisSpec, data_lo: float, data_hi: float,
                  zero_base: bool = False, pad: float = 0.0
                  ) -> Tuple[float, float, float]:
    """Fold data range + user overrides + niceing into one (lo, hi, step).

    Called exactly once per axis so nothing gets rounded twice."""
    lo, hi = float(data_lo), float(data_hi)
    if hi <= lo:
        hi = lo + (abs(lo) * 0.1 or 1.0)
    if axis.scale == SCALE_LOG:
        # a log axis can never be anchored at zero, so skip zero-basing
        # entirely and just round out to the enclosing decades
        lo = max(lo, _LOG_FLOOR)
        hi = max(hi, lo * 10)
        if axis.nice_ticks:
            lo = 10.0 ** math.floor(math.log10(lo))
            hi = 10.0 ** math.ceil(math.log10(hi))
        if not axis.auto_min:
            lo = max(axis.vmin, _LOG_FLOOR)
        if not axis.auto_max:
            hi = max(axis.vmax, lo * 10)
        return lo, hi, 0.0
    if zero_base and zero_baseline_ok(lo, hi):
        lo = 0.0
    elif pad > 0:
        span = hi - lo
        lo -= span * pad
        hi += span * pad
        if data_lo >= 0 and lo < 0:
            lo = 0.0
    if axis.nice_ticks:
        lo, hi, step = nice_bounds(lo, hi, axis.tick_count)
    else:
        step = (hi - lo) / max(1, axis.tick_count - 1)
    if not axis.auto_min:
        lo = axis.vmin
    if not axis.auto_max:
        hi = axis.vmax
    if hi <= lo:
        hi = lo + (abs(lo) * 0.1 or 1.0)
    return lo, hi, step


def linear_ticks(lo: float, hi: float, count: int, nice: bool) -> List[float]:
    if hi <= lo:
        return [lo]
    count = max(2, count)
    if not nice:
        step = (hi - lo) / (count - 1)
        return [lo + i * step for i in range(count)]
    _, _, step = nice_bounds(lo, hi, count)
    out: List[float] = []
    start = math.ceil(lo / step - 1e-9) * step
    v = start
    guard = 0
    while v <= hi + step * 1e-6 and guard < 500:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
        guard += 1
    return out or [lo, hi]


def log_ticks(lo: float, hi: float, count: int) -> List[float]:
    lo = max(lo, _LOG_FLOOR)
    e0, e1 = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
    decades = list(range(int(e0), int(e1) + 1))
    if len(decades) <= count:
        return [10.0 ** e for e in decades if lo <= 10.0 ** e <= hi * 1.0001] or [lo, hi]
    stride = max(1, len(decades) // max(1, count - 1))
    return [10.0 ** e for e in decades[::stride]]


def axis_ticks(axis: AxisSpec, scale: Scale, step: float = 0.0) -> List[float]:
    if axis.scale == SCALE_LOG:
        return log_ticks(scale.vmin, scale.vmax, axis.tick_count)
    if step and step > 0:
        return ticks_from_step(scale.vmin, scale.vmax, step)
    return linear_ticks(scale.vmin, scale.vmax, axis.tick_count, axis.nice_ticks)


# ---------------------------------------------------------------------------
# label formatting
# ---------------------------------------------------------------------------
def auto_decimals(values: Sequence[float]) -> int:
    if not values:
        return 0
    span = max(values) - min(values)
    if span <= 0:
        span = abs(values[0]) or 1.0
    step = span / max(1, len(values) - 1)
    if step >= 100:
        return 0
    if step >= 10:
        return 0
    if step >= 1:
        return 0 if all(abs(v - round(v)) < 1e-9 for v in values) else 1
    if step >= 0.1:
        return 1
    if step >= 0.01:
        return 2
    return 3


def format_value(v: float, decimals: int, thousands: bool) -> str:
    if decimals < 0:
        decimals = 0
    if abs(v) >= 1e6 and decimals == 0:
        # keep big numbers readable but still exact-ish
        s = f"{v:,.0f}" if thousands else f"{v:.0f}"
        return s
    s = f"{v:,.{decimals}f}" if thousands else f"{v:.{decimals}f}"
    if decimals > 0:
        s = s.rstrip("0").rstrip(".") if "." in s else s
    return s


def format_ticks(ticks: Sequence[float], axis: AxisSpec) -> List[str]:
    if axis.scale == SCALE_LOG:
        # decade ticks span orders of magnitude, so a single shared decimal
        # count would print most of them as "0"
        out = []
        for t in ticks:
            dec = 0 if t >= 1 else max(0, int(round(-math.log10(max(t, _LOG_FLOOR)))))
            out.append(format_value(t, dec, axis.thousands_sep))
        return out
    dec = axis.decimals if axis.decimals >= 0 else auto_decimals(list(ticks))
    return [format_value(t, dec, axis.thousands_sep) for t in ticks]


def year_tick_labels(ticks: Sequence[float]) -> List[str]:
    return [str(int(round(t))) for t in ticks]

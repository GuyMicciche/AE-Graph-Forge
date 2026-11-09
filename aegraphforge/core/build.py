"""
build.py -- turns (Dataset, ChartSpec) into a fully resolved RenderModel.

This is the crux of the whole app. The previewer draws the RenderModel and
the JSX generator serialises the RenderModel. They cannot drift apart,
because neither one does any of its own maths.

Everything in a RenderModel is already in composition pixel space.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from . import scales as sc
from .dataset import CATEGORY, DATE, Dataset, NUMERIC
from .geometry import PathGeometry, Pt, build_path
from .layout import LegendLayout, pack_legend
from .spec import (AREA, BAR, CONNECTED_SCATTER, ChartSpec, DONUT, GROUPED_BAR,
                   HBAR, LINE, LOLLIPOP, RGB, STACKED_AREA, STACKED_BAR,
                   STEP_LINE, SORT_DATA, SORT_LABEL, SORT_VALUE_ASC,
                   D_ALL, D_NAME, D_NAME_VAL, D_PCT, D_VALUE,
                   SCATTER, SeriesSpec, palette_color)
from .transform import aggregate_groups, apply_transform, sort_rows


# ---------------------------------------------------------------------------
# resolved pieces
# ---------------------------------------------------------------------------
@dataclass
class TickModel:
    value: float
    pixel: float
    label: str


@dataclass
class DotModel:
    x: float
    y: float
    diameter: float
    color: RGB
    reveal_at: float          # progress 0..100 where this dot starts revealing
    reveal_span: float = 0.0  # progress units the reveal takes
    label: str = ""


@dataclass
class SeriesModel:
    spec: SeriesSpec
    label: str
    color: RGB
    axis: str
    path: Optional[PathGeometry] = None
    dots: List[DotModel] = field(default_factory=list)
    values: List[Optional[float]] = field(default_factory=list)   # post-transform
    baseline_pixel: float = 0.0
    # For a stacked area the fill closes against the series below
    # rather than a flat baseline, so that boundary is kept here.
    lower_points: List[Pt] = field(default_factory=list)
    safe_name: str = "SERIES"


@dataclass
class BarModel:
    label: str                # category name, shown on the category axis
    value: float
    x: float                  # centre (BAR) / left edge (HBAR)
    y: float
    width: float
    height: float
    color: RGB
    reveal_at: float          # progress where this bar finishes growing
    base: float               # pixel of the zero baseline
    reveal_span: float = 0.0  # progress units the growth takes
    value_label: str = ""     # formatted number, rides the end of the bar


@dataclass
class LegendEntry:
    label: str
    color: RGB
    kind: str = "swatch"      # "swatch" | "circle"
    diameter: float = 20.0


@dataclass
class SegmentModel:
    """One wedge of a donut or pie, measured as a fraction of the ring.

    `start` and `end` already have the inter-slice gap cut out of them, and
    the label position is resolved here rather than at draw time, so the
    preview and the generated script place every wedge and caption alike.
    """
    label: str
    value: float
    start: float              # 0..1 clockwise from twelve o'clock
    end: float
    color: RGB
    reveal_at: float
    reveal_span: float
    value_label: str = ""
    pct_label: str = ""
    fraction: float = 0.0     # share of the total, before the gap is cut
    text: str = ""            # the caption as configured, ready to draw
    label_x: float = 0.0
    label_y: float = 0.0
    label_just: str = "left"  # "left" | "right" | "center"
    show_label: bool = True


@dataclass
class RenderModel:
    spec: ChartSpec
    ok: bool = True
    error: str = ""
    warnings: List[str] = field(default_factory=list)

    n_points: int = 0
    x_ticks: List[TickModel] = field(default_factory=list)
    y_ticks: List[TickModel] = field(default_factory=list)
    y2_ticks: List[TickModel] = field(default_factory=list)
    series: List[SeriesModel] = field(default_factory=list)
    bars: List[BarModel] = field(default_factory=list)
    legend: List[LegendEntry] = field(default_factory=list)
    size_legend: List[Tuple[str, float]] = field(default_factory=list)
    legend_layout: LegendLayout = field(default_factory=LegendLayout)
    segments: List[SegmentModel] = field(default_factory=list)
    donut_cx: float = 0.0
    donut_cy: float = 0.0
    # r_outer / r_inner are what the reader sees. radius / thickness are the
    # stroked-ellipse form the renderers actually draw, derived from the pair:
    # a stroke of width (outer - inner) centred on a path of radius
    # (outer + inner) / 2 fills exactly the band between them, and collapses
    # to a solid pie when inner is 0.
    donut_r_outer: float = 0.0
    donut_r_inner: float = 0.0
    donut_radius: float = 0.0
    donut_thickness: float = 0.0
    donut_gap_frac: float = 0.0    # gap between slices, as a fraction of the circle
    readout_values: List[float] = field(default_factory=list)
    readout_labels: List[str] = field(default_factory=list)
    x_scale: Optional[sc.Scale] = None
    y_scale: Optional[sc.Scale] = None
    y2_scale: Optional[sc.Scale] = None
    row_order: List[int] = field(default_factory=list)

    @property
    def plot_rect(self) -> Tuple[float, float, float, float]:
        c = self.spec.comp
        return (c.plot_left, c.plot_top, c.plot_right, c.plot_bottom)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _safe(name: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_").upper()
    return out or "SERIES"


def _data_range(values: Sequence[Optional[float]]) -> Tuple[float, float]:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if not vals:
        return (0.0, 1.0)
    lo, hi = min(vals), max(vals)
    if lo == hi:
        pad = abs(lo) * 0.1 or 1.0
        return (lo - pad, hi + pad)
    return (lo, hi)


def _padded(lo: float, hi: float, frac: float = 0.05) -> Tuple[float, float]:
    span = hi - lo
    if span <= 0:
        span = abs(hi) or 1.0
    return (lo - span * frac, hi + span * frac)


def _ticks_for(axis, scale: sc.Scale, is_date: bool, step: float = 0.0) -> List[TickModel]:
    if not axis.show_grid and axis.tick_count <= 0:
        return []
    raw = sc.axis_ticks(axis, scale, step)
    labels = (sc.year_tick_labels(raw) if is_date else sc.format_ticks(raw, axis))
    return [TickModel(value=v, pixel=scale.px(v), label=lab)
            for v, lab in zip(raw, labels)]


def _dual_align(axis, scale: sc.Scale, n_ticks: int, step: float) -> List[TickModel]:
    """Emit exactly n_ticks evenly spaced across the right-hand axis so its
    labels sit on the same gridlines as the left-hand axis."""
    if n_ticks < 2:
        return _ticks_for(axis, scale, False, step)
    vals = [scale.vmin + (scale.vmax - scale.vmin) * i / (n_ticks - 1)
            for i in range(n_ticks)]
    labels = sc.format_ticks(vals, axis)
    return [TickModel(value=v, pixel=scale.px(v), label=lab)
            for v, lab in zip(vals, labels)]


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------
def _reveal_span(n: int, spec: ChartSpec) -> float:
    """Width in Progress units of one item's reveal window."""
    if n <= 1:
        return 100.0
    return 100.0 / n if spec.style.reveal_from_zero else 0.0


def _reveal_at(i: int, n: int, spec: ChartSpec) -> float:
    """Progress at which item i STARTS revealing.

    With reveal_from_zero the N items divide the timeline into N slots, so item
    0 occupies [0, 100/N] and nothing is on screen at Progress 0. Without it,
    item i sits exactly on i/(N-1), which puts item 0 at Progress 0 already
    fully drawn, matching the original hand-written scripts.
    """
    if n <= 1:
        return 0.0
    if spec.style.reveal_from_zero:
        return (i / n) * 100.0
    return (i / (n - 1)) * 100.0


def _bar_reveal_at(i: int, n: int, spec: ChartSpec) -> float:
    """Progress at which bar i FINISHES growing (bars grow up to their mark)."""
    if n <= 1:
        return 100.0 if spec.style.reveal_from_zero else 0.0
    if spec.style.reveal_from_zero:
        return ((i + 1) / n) * 100.0
    return (i / (n - 1)) * 100.0


def build_model(ds: Dataset, spec: ChartSpec) -> RenderModel:
    m = RenderModel(spec=spec)
    try:
        if ds is None or ds.n_rows == 0:
            m.ok = False
            m.error = "No data loaded."
            return m
        if spec.chart_type == DONUT:
            m = _build_donut(ds, spec, m)
        elif spec.is_bar:
            m = _build_bars(ds, spec, m)
        else:
            m = _build_points(ds, spec, m)
        if m.ok:
            _finalize_legend(m)
        return m
    except Exception as exc:                      # keep the UI alive
        m.ok = False
        m.error = f"{type(exc).__name__}: {exc}"
        return m


# ---------------------------------------------------------------------------
# point-based charts: line / area / scatter / connected scatter
# ---------------------------------------------------------------------------
def _build_points(ds: Dataset, spec: ChartSpec, m: RenderModel) -> RenderModel:
    comp = spec.comp
    L, R, T, B = comp.plot_left, comp.plot_right, comp.plot_top, comp.plot_bottom

    xcol = ds.col(spec.x_column)
    if xcol is None or not xcol.is_plottable:
        m.ok = False
        m.error = "Pick a numeric or date column for X."
        return m
    if not spec.series:
        m.ok = False
        m.error = "Add at least one Y series."
        return m

    # ---- row order -----------------------------------------------------
    sort_name = spec.sort_column or spec.x_column
    scol = ds.col(sort_name)
    if scol is not None and scol.is_plottable:
        order = sort_rows(scol.numeric, spec.sort_ascending)
    else:
        order = list(range(ds.n_rows))

    # drop rows with no X
    order = [i for i in order if xcol.numeric[i] is not None]
    if len(order) < 2:
        m.ok = False
        m.error = "Need at least 2 rows with a valid X value."
        return m
    m.row_order = order
    m.n_points = len(order)
    xs_data = [xcol.numeric[i] for i in order]

    # ---- per-series values (transform applied in row order) ------------
    resolved: List[Tuple[SeriesSpec, List[Optional[float]]]] = []
    for s in spec.series:
        col = ds.col(s.column)
        if col is None or col.kind not in (NUMERIC, DATE):
            m.warnings.append(f"Series '{s.column}' is not numeric; skipped.")
            continue
        raw = [col.numeric[i] for i in order]
        resolved.append((s, apply_transform(raw, s.transform, s.window)))
    if not resolved:
        m.ok = False
        m.error = "No usable numeric series."
        return m

    # ---- stacking ------------------------------------------------------
    # Done before the scales are resolved so the Y axis covers the stacked
    # totals rather than the tallest single series.
    # A stacked area accumulates each series on top of the one before, so the
    # value a series plots is its own value plus everything beneath it.
    if spec.chart_type == STACKED_AREA and len(resolved) > 1:
        running = [0.0] * len(order)
        stacked: List[Tuple[SeriesSpec, List[Optional[float]]]] = []
        lowers: List[List[Optional[float]]] = []
        for s_spec, vals in resolved:
            low = list(running)
            top: List[Optional[float]] = []
            for k in range(len(order)):
                v = vals[k]
                if v is None:
                    top.append(None)
                else:
                    running[k] += v
                    top.append(running[k])
            stacked.append((s_spec, top))
            lowers.append([x for x in low])
        resolved = stacked
        m.stack_lowers = lowers

    # ---- scales (resolved exactly once per axis) -----------------------
    scatterish = spec.chart_type in (SCATTER, CONNECTED_SCATTER)
    xd_lo, xd_hi = _data_range(xs_data)
    # A date/sequence X axis should never be dragged down to zero; a plain
    # numeric X on a scatter usually reads better anchored there.
    x_zero = scatterish and xcol.kind == NUMERIC
    xlo, xhi, xstep = sc.resolve_range(
        spec.x_axis, xd_lo, xd_hi,
        zero_base=x_zero, pad=0.0 if x_zero else (0.04 if scatterish else 0.0))
    m.x_scale = sc.Scale(vmin=xlo, vmax=xhi, p0=L, p1=R, kind=spec.x_axis.scale)

    left = [(s, v) for s, v in resolved if s.axis == "left"]
    right = [(s, v) for s, v in resolved if s.axis == "right"]
    if not left:
        left, right = right, []

    def axis_range(group, axis):
        pool: List[Optional[float]] = []
        for _, vals in group:
            pool.extend(vals)
        lo, hi = _data_range(pool)
        return sc.resolve_range(axis, lo, hi, zero_base=True, pad=0.03)

    ylo, yhi, ystep = axis_range(left, spec.y_axis)
    m.y_scale = sc.Scale(vmin=ylo, vmax=yhi, p0=B, p1=T, kind=spec.y_axis.scale)
    y2step = 0.0
    if right:
        y2lo, y2hi, y2step = axis_range(right, spec.y2_axis)
        m.y2_scale = sc.Scale(vmin=y2lo, vmax=y2hi, p0=B, p1=T, kind=spec.y2_axis.scale)

    # ---- ticks ---------------------------------------------------------
    m.x_ticks = _ticks_for(spec.x_axis, m.x_scale, xcol.kind == DATE, xstep)
    m.y_ticks = _ticks_for(spec.y_axis, m.y_scale, False, ystep)
    if m.y2_scale:
        # share the tick COUNT across both axes so the gridlines line up,
        # which is what makes a dual-axis chart readable at all
        m.y2_ticks = _dual_align(spec.y2_axis, m.y2_scale, len(m.y_ticks), y2step)

    # ---- category colours ---------------------------------------------
    catcol = ds.col(spec.category.column) if spec.category.enabled else None
    if catcol is not None and catcol.kind != CATEGORY:
        m.warnings.append(f"'{spec.category.column}' is not categorical; colour mapping ignored.")
        catcol = None
    cat_colors: Dict[str, RGB] = {}
    if catcol is not None:
        for i, lev in enumerate(catcol.categories):
            cat_colors[lev] = tuple(spec.category.colors.get(lev, palette_color(i + 1)))

    # ---- size mapping --------------------------------------------------
    sizecol = ds.col(spec.size.column) if spec.size.enabled else None
    if sizecol is not None and sizecol.kind != NUMERIC:
        m.warnings.append(f"'{spec.size.column}' is not numeric; size mapping ignored.")
        sizecol = None
    diam_of = _diameter_mapper(sizecol, order, spec)

    # ---- build each series --------------------------------------------
    n = len(order)
    for si, (s, vals) in enumerate(resolved):
        scale_y = m.y2_scale if (s.axis == "right" and m.y2_scale) else m.y_scale
        pts: List[Pt] = []
        keep: List[int] = []
        for k in range(n):
            v = vals[k]
            if v is None:
                continue
            pts.append((m.x_scale.px(xs_data[k]), scale_y.px(v)))
            keep.append(k)
        if len(pts) < 2:
            m.warnings.append(f"Series '{s.display_label()}' has too few points.")
            continue

        sm = SeriesModel(
            spec=s,
            label=s.display_label(),
            color=tuple(s.color),
            axis=s.axis,
            values=vals,
            safe_name=_safe(s.display_label()),
        )
        sm.baseline_pixel = scale_y.px_clamped(0.0)
        if spec.chart_type == STACKED_AREA:
            lows = getattr(m, "stack_lowers", None)
            if lows and si < len(lows):
                sm.lower_points = [(pts[j][0], scale_y.px(lows[si][k] or 0.0))
                                   for j, k in enumerate(keep)]
        if spec.chart_type != SCATTER and s.show_line:
            path_pts = _step_points(pts) if spec.chart_type == STEP_LINE else pts
            smooth = False if spec.chart_type == STEP_LINE else s.smooth
            sm.path = build_path(path_pts, smooth=smooth, arc_mode=spec.arc_mode)

        want_dots = s.show_dots or spec.chart_type in (SCATTER, CONNECTED_SCATTER) \
            or (catcol is not None) or (sizecol is not None)
        if want_dots:
            for j, k in enumerate(keep):
                row = order[k]
                if catcol is not None:
                    lev = catcol.category_of(row)
                    col = cat_colors.get(lev, sm.color)
                else:
                    col = sm.color
                d = diam_of(k) if sizecol is not None else s.dot_size
                sm.dots.append(DotModel(
                    x=pts[j][0], y=pts[j][1], diameter=d, color=col,
                    reveal_at=_reveal_at(k, n, spec),
                    reveal_span=_reveal_span(n, spec),
                    label=catcol.category_of(row) if catcol is not None else "",
                ))
        m.series.append(sm)

    if not m.series:
        m.ok = False
        m.error = "Nothing plottable after filtering."
        return m

    # ---- legend --------------------------------------------------------
    if spec.style.show_legend:
        if catcol is not None and spec.category.show_legend:
            for lev in catcol.categories:
                m.legend.append(LegendEntry(label=lev, color=cat_colors[lev]))
        if len(m.series) > 1 or catcol is None:
            for sm in m.series:
                m.legend.append(LegendEntry(label=sm.label, color=sm.color))
        if sizecol is not None and spec.size.show_legend:
            m.size_legend = _size_legend(sizecol, order, spec, diam_of)

    # ---- readout -------------------------------------------------------
    if spec.readout.enabled:
        rcol = ds.col(spec.readout.column)
        if rcol is not None and rcol.numeric:
            m.readout_values = [rcol.numeric[i] if rcol.numeric[i] is not None else 0.0
                                for i in order]
            m.readout_labels = [rcol.display_at(i) for i in order]
        else:
            m.warnings.append("Readout column is not usable; disabled.")
    return m


def _step_points(pts: List[Pt]) -> List[Pt]:
    """Insert a corner between each pair so the line moves in right angles.

    The result holds the original points at even indices, so the leading edge
    still passes through every data point at the same Progress it would on a
    straight line chart.
    """
    if len(pts) < 2:
        return list(pts)
    out: List[Pt] = [pts[0]]
    for i in range(1, len(pts)):
        out.append((pts[i][0], pts[i - 1][1]))   # travel horizontally first
        out.append(pts[i])
    return out


def _diameter_mapper(sizecol, order, spec: ChartSpec):
    if sizecol is None:
        return lambda k: spec.size.min_diameter
    vals = [sizecol.numeric[i] for i in order]
    lo, hi = _data_range(vals)
    d0, d1 = spec.size.min_diameter, spec.size.max_diameter

    def f(k: int) -> float:
        v = vals[k]
        if v is None:
            return d0
        t = 0.0 if hi == lo else (v - lo) / (hi - lo)
        t = min(max(t, 0.0), 1.0)
        if spec.size.sqrt_scale:
            t = math.sqrt(t)
        return round(d0 + t * (d1 - d0), 2)
    return f


def _size_legend(sizecol, order, spec: ChartSpec, diam_of) -> List[Tuple[str, float]]:
    vals = [v for v in (sizecol.numeric[i] for i in order) if v is not None]
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    d0, d1 = spec.size.min_diameter, spec.size.max_diameter
    out = []
    for frac in (0.0, 0.5, 1.0):
        v = lo + (hi - lo) * frac
        t = math.sqrt(frac) if spec.size.sqrt_scale else frac
        out.append((sc.format_value(v, 0, True), round(d0 + t * (d1 - d0), 2)))
    return out


# ---------------------------------------------------------------------------
# bar charts
# ---------------------------------------------------------------------------
def _build_bars(ds: Dataset, spec: ChartSpec, m: RenderModel) -> RenderModel:
    comp = spec.comp
    L, R, T, B = comp.plot_left, comp.plot_right, comp.plot_top, comp.plot_bottom

    if not spec.series:
        m.ok = False
        m.error = "Add a value column for the bars."
        return m
    s = spec.series[0]
    vcol = ds.col(s.column)
    if vcol is None:
        m.ok = False
        m.error = "Bar value column not found."
        return m

    gcol = ds.col(spec.group_column) if spec.group_column else None
    if gcol is not None:
        labels = [gcol.display_at(i) for i in range(ds.n_rows)]
        pairs = aggregate_groups(labels, vcol.numeric, spec.aggregation)
    else:
        lab_col = ds.col(spec.x_column)
        labels = ([lab_col.display_at(i) for i in range(ds.n_rows)]
                  if lab_col else [str(i + 1) for i in range(ds.n_rows)])
        pairs = [(lab, v) for lab, v in zip(labels, vcol.numeric) if v is not None]

    if not pairs:
        m.ok = False
        m.error = "No values to aggregate."
        return m

    # Grouped and stacked bars need one value per (group, series), so the
    # single-series aggregation above becomes a matrix keyed on the same
    # ordered labels.
    multi = spec.chart_type in (GROUPED_BAR, STACKED_BAR) and len(spec.series) > 1
    series_vals: Dict[str, List[float]] = {}
    if multi:
        label_src = gcol if gcol is not None else ds.col(spec.x_column)
        row_labels = ([label_src.display_at(i) for i in range(ds.n_rows)]
                      if label_src else [str(i + 1) for i in range(ds.n_rows)])
        for ss in spec.series:
            c = ds.col(ss.column)
            if c is None or not c.numeric:
                m.warnings.append(f"Series '{ss.column}' is not numeric; skipped.")
                continue
            agg = dict(aggregate_groups(row_labels, c.numeric, spec.aggregation))
            series_vals[ss.column] = agg
        if not series_vals:
            m.ok = False
            m.error = "No usable numeric series for the bars."
            return m
        keys = list(dict.fromkeys(lab for lab, _ in pairs))
        totals = [(k, sum(series_vals[c].get(k, 0.0) for c in series_vals)) for k in keys]
        pairs = totals

    if spec.max_bars > 0 and len(pairs) > spec.max_bars:
        # trim by size first so the cut always keeps the biggest groups,
        # then apply whatever display order was asked for
        m.warnings.append(f"Showing top {spec.max_bars} of {len(pairs)} groups.")
        keep = {lab for lab, _ in sorted(pairs, key=lambda p: p[1],
                                         reverse=True)[:spec.max_bars]}
        pairs = [(lab, v) for lab, v in pairs if lab in keep]
    pairs = _sorted_pairs(pairs, spec.slice_sort)
    if spec.chart_type == HBAR:
        pairs = pairs[::-1]

    values = [v for _, v in pairs]
    lo, hi = _data_range(values)
    axis = spec.y_axis
    lo, hi, bstep = sc.resolve_range(axis, min(0.0, lo), hi, zero_base=True, pad=0.0)

    n = len(pairs)
    m.n_points = n
    vdec = axis.decimals if axis.decimals >= 0 else sc.auto_decimals(values)
    cat_colors = {lab: tuple(spec.category.colors.get(lab, s.color)) for lab, _ in pairs}

    if multi:
        return _build_multi_bars(spec, m, pairs, series_vals, axis, lo, hi, bstep, vdec)

    if spec.chart_type in (BAR, GROUPED_BAR, STACKED_BAR, LOLLIPOP):
        m.y_scale = sc.make_scale(axis, B, T, lo, hi)
        m.x_scale = sc.Scale(vmin=0, vmax=max(1, n), p0=L, p1=R)
        slot = (R - L) / n
        w = (spec.lollipop_stem if spec.chart_type == LOLLIPOP
             else slot * (1.0 - spec.bar_gap))
        base = m.y_scale.px(0.0)
        for i, (lab, v) in enumerate(pairs):
            cx = L + slot * (i + 0.5)
            top = m.y_scale.px(v)
            m.bars.append(BarModel(
                label=lab, value=v, x=cx, y=min(top, base), width=w,
                height=abs(base - top), color=cat_colors[lab],
                reveal_at=_bar_reveal_at(i, n, spec),
                reveal_span=_reveal_span(n, spec), base=base,
                value_label=sc.format_value(v, vdec, axis.thousands_sep)))
        m.y_ticks = _ticks_for(axis, m.y_scale, False, bstep)
        m.x_ticks = [TickModel(value=i, pixel=L + slot * (i + 0.5), label=lab)
                     for i, (lab, _) in enumerate(pairs)]
    else:
        m.x_scale = sc.make_scale(axis, L, R, lo, hi)
        m.y_scale = sc.Scale(vmin=0, vmax=max(1, n), p0=B, p1=T)
        slot = (B - T) / n
        h = slot * (1.0 - spec.bar_gap)
        base = m.x_scale.px(0.0)
        for i, (lab, v) in enumerate(pairs):
            cy = B - slot * (i + 0.5)
            end = m.x_scale.px(v)
            m.bars.append(BarModel(
                label=lab, value=v, x=min(base, end), y=cy, width=abs(end - base),
                height=h, color=cat_colors[lab],
                reveal_at=_bar_reveal_at(n - 1 - i, n, spec),
                reveal_span=_reveal_span(n, spec), base=base,
                value_label=sc.format_value(v, vdec, axis.thousands_sep)))
        m.x_ticks = _ticks_for(axis, m.x_scale, False, bstep)
        m.y_ticks = [TickModel(value=i, pixel=B - slot * (i + 0.5), label=lab)
                     for i, (lab, _) in enumerate(pairs)]

    if spec.style.show_legend and spec.category.enabled and spec.category.colors:
        seen = set()
        for lab, _ in pairs:
            if lab in seen:
                continue
            seen.add(lab)
            m.legend.append(LegendEntry(label=lab, color=cat_colors[lab]))
    return m


def _finalize_legend(m: RenderModel) -> None:
    """Resolve legend geometry once, so preview and JSX cannot disagree."""
    s = m.spec
    if not s.style.show_legend or (not m.legend and not m.size_legend):
        m.legend_layout = LegendLayout()
        return
    entries = []
    for le in m.legend:
        ckey = f"cat_color_{le.label}"
        entries.append((le.label, le.color, ckey))
    m.legend_layout = pack_legend(
        entries=entries,
        size_entries=m.size_legend,
        size_title=(s.size.column or "SIZE").upper() if m.size_legend else "",
        left=s.comp.plot_left,
        right=s.comp.plot_right,
        base_y=s.comp.height - 60.0,
        label_size=s.style.legend_size,
    )


def _build_multi_bars(spec: ChartSpec, m: RenderModel, pairs, series_vals,
                      axis, lo: float, hi: float, bstep: float,
                      vdec: int) -> RenderModel:
    """Grouped or stacked bars, one sub-bar per (group, series).

    Both share the same slot arithmetic; the difference is only whether the
    sub-bars sit side by side inside the slot or accumulate upward from the
    baseline.
    """
    comp = spec.comp
    L, R, T, B = comp.plot_left, comp.plot_right, comp.plot_top, comp.plot_bottom
    stacked = spec.chart_type == STACKED_BAR
    cols = [ss for ss in spec.series if ss.column in series_vals]
    k = len(cols)
    n = len(pairs)

    if stacked:
        top_total = max((sum(series_vals[c.column].get(lab, 0.0) for c in cols)
                         for lab, _ in pairs), default=1.0)
        lo, hi, bstep = sc.resolve_range(axis, 0.0, top_total, zero_base=True, pad=0.0)

    m.y_scale = sc.make_scale(axis, B, T, lo, hi)
    m.x_scale = sc.Scale(vmin=0, vmax=max(1, n), p0=L, p1=R)
    slot = (R - L) / n
    inner = slot * (1.0 - spec.bar_gap)
    base = m.y_scale.px(0.0)

    for i, (lab, _total) in enumerate(pairs):
        cx = L + slot * (i + 0.5)
        at = _bar_reveal_at(i, n, spec)
        span = _reveal_span(n, spec)
        running = 0.0
        for j, ss in enumerate(cols):
            v = series_vals[ss.column].get(lab, 0.0)
            if stacked:
                y0 = m.y_scale.px(running)
                running += v
                y1 = m.y_scale.px(running)
                bx, bw = cx, inner
                seg_base = y0
            else:
                sub = inner / k
                bx = cx - inner / 2.0 + sub * (j + 0.5)
                bw = sub
                y1 = m.y_scale.px(v)
                seg_base = base
            last = (j == k - 1)
            m.bars.append(BarModel(
                label=lab, value=v, x=bx, y=min(y1, seg_base), width=bw,
                height=abs(seg_base - y1), color=tuple(ss.color),
                reveal_at=at, reveal_span=span, base=seg_base,
                value_label=(sc.format_value(running if stacked else v, vdec,
                                             axis.thousands_sep)
                             if (last or not stacked) else "")))

    m.y_ticks = _ticks_for(axis, m.y_scale, False, bstep)
    m.x_ticks = [TickModel(value=i, pixel=L + slot * (i + 0.5), label=lab)
                 for i, (lab, _) in enumerate(pairs)]
    if spec.style.show_legend:
        for ss in cols:
            m.legend.append(LegendEntry(label=ss.display_label(), color=tuple(ss.color)))
    return m


def _sorted_pairs(pairs: List[Tuple[str, float]], how: str) -> List[Tuple[str, float]]:
    """Order aggregated (label, value) pairs. `data` keeps first-seen order."""
    if how == SORT_VALUE_ASC:
        return sorted(pairs, key=lambda p: p[1])
    if how == SORT_LABEL:
        return sorted(pairs, key=lambda p: str(p[0]).lower())
    if how == SORT_DATA:
        return list(pairs)
    return sorted(pairs, key=lambda p: p[1], reverse=True)


def _segment_text(spec: ChartSpec, label: str, value_label: str,
                  pct_label: str) -> str:
    """The caption for one wedge, in the configured mode."""
    mode = spec.donut_label_mode
    if mode == D_VALUE:
        return value_label
    if mode == D_PCT:
        return pct_label
    if mode == D_NAME:
        return label
    if mode == D_NAME_VAL:
        return f"{label}  {value_label}"
    if mode == D_ALL:
        return f"{label}  {value_label}  ({pct_label})"
    return f"{label}  {pct_label}"      # D_NAME_PCT


def _build_donut(ds: Dataset, spec: ChartSpec, m: RenderModel) -> RenderModel:
    """A ring of wedges sized by share of total.

    Each wedge is one stroked ellipse trimmed to its span, which is why the
    generated script can animate the whole thing with nothing but Trim Paths.
    The ring is specified as an outer and an inner radius; the stroke geometry
    that both renderers consume falls out of that pair, so inner = 0 is a
    solid pie rather than a separate code path.
    """
    comp = spec.comp
    L, R, T, B = comp.plot_left, comp.plot_right, comp.plot_top, comp.plot_bottom

    if not spec.series:
        m.ok = False
        m.error = "Add a value column for the donut."
        return m
    vcol = ds.col(spec.series[0].column)
    if vcol is None or not vcol.numeric:
        m.ok = False
        m.error = "Donut value column is not numeric."
        return m

    # Slices come from the group column when one is set. Falling back to the
    # X column is only sensible when that column actually repeats; a per-row
    # id or a date gives one wedge per row, which is never what was wanted.
    lcol = ds.col(spec.group_column) if spec.group_column else ds.col(spec.x_column)
    labels = ([lcol.display_at(i) for i in range(ds.n_rows)] if lcol
              else [str(i + 1) for i in range(ds.n_rows)])
    pairs = [(lab, v) for lab, v in aggregate_groups(labels, vcol.numeric,
                                                     spec.aggregation) if v > 0]
    if not pairs:
        m.ok = False
        m.error = "No positive values to chart."
        return m
    if not spec.group_column and len(pairs) > max(12, spec.max_bars):
        m.warnings.append(
            f"'{spec.x_column}' has {len(pairs)} distinct values. Set 'Group by' "
            "to a category column for readable slices.")

    pairs = _sorted_pairs(pairs, spec.slice_sort)
    other = 0.0
    n_merged = 0
    if spec.max_bars > 0 and len(pairs) > spec.max_bars:
        # 'Largest first' is the only order where truncating keeps the biggest
        # slices, so rank by value for the cut regardless of display order.
        keep = {lab for lab, _ in sorted(pairs, key=lambda p: p[1],
                                         reverse=True)[:spec.max_bars]}
        head = [(lab, v) for lab, v in pairs if lab in keep]
        other += sum(v for lab, v in pairs if lab not in keep)
        n_merged += len(pairs) - len(head)
        pairs = head

    grand = sum(v for _, v in pairs) + other
    if spec.donut_label_min_pct <= 0 or grand <= 0:
        min_share = 0.0
    else:
        min_share = spec.donut_label_min_pct / 100.0

    if other > 0:
        pairs = pairs + [(spec.donut_other_label, other)]
        m.warnings.append(
            f"Grouped {n_merged} small slices into '{spec.donut_other_label}'.")

    total = sum(v for _, v in pairs) or 1.0
    n = len(pairs)
    m.n_points = n

    m.donut_cx = (L + R) / 2.0
    m.donut_cy = (T + B) / 2.0
    half = min(R - L, B - T) / 2.0
    m.donut_r_outer = max(1.0, half * spec.donut_radius_frac)
    inner_frac = min(max(spec.donut_inner_frac, 0.0), 0.98)
    m.donut_r_inner = m.donut_r_outer * inner_frac
    m.donut_radius = (m.donut_r_outer + m.donut_r_inner) / 2.0
    m.donut_thickness = m.donut_r_outer - m.donut_r_inner

    # A gap wider than the smallest slice would invert that wedge, so cap it.
    gap = max(0.0, spec.donut_gap_deg) / 360.0
    smallest = min((v / total for _, v in pairs), default=1.0)
    m.donut_gap_frac = min(gap, smallest * 0.6)

    axis = spec.y_axis
    vdec = axis.decimals if axis.decimals >= 0 else sc.auto_decimals([v for _, v in pairs])
    inside = spec.donut_label_place == "inside"
    cursor = 0.0
    for i, (lab, v) in enumerate(pairs):
        frac = v / total
        color = tuple(spec.category.colors.get(lab, palette_color(i)))
        start = cursor + m.donut_gap_frac / 2.0
        end = cursor + frac - m.donut_gap_frac / 2.0
        pct = f"{frac * 100:.1f}%"
        vlabel = sc.format_value(v, vdec, axis.thousands_sep)
        seg = SegmentModel(
            label=lab, value=v, start=start, end=max(start, end), color=color,
            reveal_at=_reveal_at(i, n, spec), reveal_span=_reveal_span(n, spec),
            value_label=vlabel, pct_label=pct, fraction=frac,
            text=_segment_text(spec, lab, vlabel, pct),
            show_label=spec.donut_show_labels and frac >= min_share)
        _place_segment_label(m, seg, inside)
        m.segments.append(seg)
        cursor += frac

    if spec.style.show_legend:
        for seg in m.segments:
            m.legend.append(LegendEntry(label=seg.label, color=seg.color))
    return m


def _place_segment_label(m: RenderModel, seg: SegmentModel, inside: bool) -> None:
    """Resolve one wedge caption's anchor, once, for both renderers.

    Outside labels sit just beyond the ring and read outward from the wedge.
    Inside labels are centred on the band; on a solid pie there is no band, so
    they fall back to two thirds of the way out from the centre.
    """
    mid = (seg.start + seg.end) / 2.0
    ang = mid * 2.0 * math.pi - math.pi / 2.0
    if inside:
        if m.donut_r_inner > 1.0:
            rad = (m.donut_r_outer + m.donut_r_inner) / 2.0
        else:
            rad = m.donut_r_outer * 0.66
        just = "center"
    else:
        rad = m.donut_r_outer + 34.0
        just = "left" if math.cos(ang) >= 0 else "right"
    seg.label_x = m.donut_cx + math.cos(ang) * rad
    seg.label_y = m.donut_cy + math.sin(ang) * rad + 8.0
    seg.label_just = just

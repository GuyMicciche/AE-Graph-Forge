"""
spec.py -- the chart specification.

This is the single source of truth. The preview canvas and the JSX generator
both consume the *same* built model derived from this spec, so what you see
in the previewer is what After Effects builds. Nothing is computed twice by
two different code paths.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

RGB = Tuple[float, float, float]

# ---------------------------------------------------------------------------
# chart types
# ---------------------------------------------------------------------------
LINE = "line"                            # one or more lines vs a continuous X
AREA = "area"                            # line + fill to baseline
CONNECTED_SCATTER = "connected_scatter"  # X vs Y, path follows a sort order
SCATTER = "scatter"                      # dots only, sequential reveal
BAR = "bar"                              # vertical bars, grow on progress
HBAR = "hbar"                            # horizontal bars

CHART_TYPES = [
    (LINE, "Line / Multi-line"),
    (AREA, "Area"),
    (CONNECTED_SCATTER, "Connected scatter"),
    (SCATTER, "Scatter"),
    (BAR, "Bar (vertical)"),
    (HBAR, "Bar (horizontal)"),
]

# ---------------------------------------------------------------------------
# per-series transforms
# ---------------------------------------------------------------------------
T_NONE = "none"
T_CUMSUM = "cumulative_sum"
T_ROLLMEAN = "rolling_mean"
T_ROLLSUM = "rolling_sum"
T_CUMMAX = "cumulative_max"
T_INDEX100 = "index_100"

TRANSFORMS = [
    (T_NONE, "Raw values"),
    (T_CUMSUM, "Cumulative sum"),
    (T_CUMMAX, "Cumulative max"),
    (T_ROLLMEAN, "Rolling mean"),
    (T_ROLLSUM, "Rolling sum"),
    (T_INDEX100, "Index to 100"),
]

# aggregations used by BAR/HBAR when grouping by a category column
AGGREGATIONS = [
    ("sum", "Sum"),
    ("mean", "Mean"),
    ("median", "Median"),
    ("count", "Count"),
    ("min", "Min"),
    ("max", "Max"),
]

SCALE_LINEAR = "linear"
SCALE_LOG = "log"
SCALE_SQRT = "sqrt"
SCALES = [(SCALE_LINEAR, "Linear"), (SCALE_LOG, "Log10"), (SCALE_SQRT, "Square root")]


@dataclass
class AxisSpec:
    title: str = ""
    unit: str = ""
    auto_min: bool = True
    auto_max: bool = True
    vmin: float = 0.0
    vmax: float = 1.0
    scale: str = SCALE_LINEAR
    tick_count: int = 6
    nice_ticks: bool = True
    decimals: int = -1          # -1 = auto
    thousands_sep: bool = True
    show_grid: bool = True
    label_size: float = 22.0
    # for the second (right-hand) axis in dual-axis line charts
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SeriesSpec:
    column: str = ""
    label: str = ""
    color: RGB = (0.95, 0.95, 0.95)
    axis: str = "left"                 # "left" | "right"
    transform: str = T_NONE
    window: int = 8                    # for rolling transforms
    stroke_width: float = 4.0
    show_line: bool = True
    show_dots: bool = False
    dot_size: float = 10.0
    fill_opacity: float = 0.0          # >0 draws an area fill under the line
    smooth: bool = True                # Catmull-Rom tangents vs straight

    def display_label(self) -> str:
        return self.label or self.column

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["color"] = list(self.color)
        return d


@dataclass
class CategorySpec:
    """Optional column that colours dots by class (the LEO/MEO/GEO pattern)."""
    column: str = ""
    enabled: bool = False
    colors: Dict[str, RGB] = field(default_factory=dict)
    show_legend: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "column": self.column,
            "enabled": self.enabled,
            "colors": {k: list(v) for k, v in self.colors.items()},
            "show_legend": self.show_legend,
        }


@dataclass
class SizeSpec:
    """Optional column mapped to dot diameter (sqrt-scaled so area reads true)."""
    column: str = ""
    enabled: bool = False
    min_diameter: float = 10.0
    max_diameter: float = 46.0
    sqrt_scale: bool = True
    show_legend: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CompSpec:
    name: str = "DATA_CHART"
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    duration: float = 14.0
    plot_left: float = 220.0
    plot_right: float = 1800.0
    plot_top: float = 170.0
    plot_bottom: float = 860.0
    progress_start: float = 1.0
    progress_end: float = 12.0
    ease_influence: float = 33.0
    open_in_viewer: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StyleSpec:
    bg_color: RGB = (0.0, 0.0, 0.0)
    grid_color: RGB = (0.25, 0.25, 0.27)
    grid_opacity: float = 45.0
    grid_width: float = 2.0
    axis_text_color: RGB = (0.75, 0.78, 0.82)
    title_color: RGB = (0.95, 0.95, 0.95)
    subtitle_color: RGB = (0.65, 0.65, 0.68)
    caption_color: RGB = (0.60, 0.63, 0.67)
    title: str = "DATA CHART"
    subtitle: str = ""
    caption: str = ""
    title_size: float = 46.0
    subtitle_size: float = 22.0
    caption_size: float = 20.0
    # font_family is the PostScript name tried first. font_stack is the
    # fallback chain AE walks if that name is not installed on the machine
    # running the script.
    font_family: str = ""
    font_stack: List[str] = field(default_factory=lambda: [
        "Arial-BoldMT", "Arial-Bold", "Arial,Bold", "ArialMT", "Arial"])
    font_faux_bold: bool = False
    show_legend: bool = True
    legend_size: float = 20.0
    show_playhead: bool = True
    playhead_opacity: float = 35.0
    show_tip_dot: bool = True
    tip_dot_size: float = 16.0
    dot_reveal_lead: float = 0.0       # extra progress units before the point
    dot_reveal_lag: float = 0.0        # extra progress units after
    # When true, item i reveals across the window [i/N, (i+1)/N] of Progress,
    # so at Progress 0 nothing is on screen and even the first point animates
    # in. When false, item i sits at i/(N-1) and the first point is already
    # fully drawn at Progress 0, matching the original hand-written scripts.
    reveal_from_zero: bool = True
    dot_opacity: float = 100.0
    max_dot_layers: int = 400          # guard against 10k-layer comps
    bind_to_controls: bool = True      # wire look properties to MASTER_CONTROLS

    def resolved_fonts(self) -> List[str]:
        """Font candidates in the order the generated setFont() should try."""
        out: List[str] = []
        fam = (self.font_family or "").strip()
        if fam:
            out.append(fam)
            # AE wants PostScript names. Offer the usual bold spellings too,
            # so picking "Futura" in the UI still lands on a bold face.
            base = fam.replace(" ", "")
            for variant in (base + "-Bold", base + "-BoldMT", fam + ",Bold", base):
                if variant not in out:
                    out.append(variant)
        for f in self.font_stack:
            if f not in out:
                out.append(f)
        return out

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k in ("bg_color", "grid_color", "axis_text_color", "title_color",
                  "subtitle_color", "caption_color"):
            d[k] = list(getattr(self, k))
        return d


@dataclass
class ReadoutSpec:
    """Live text that interpolates a column value as Progress sweeps."""
    enabled: bool = False
    column: str = ""
    prefix: str = ""
    suffix: str = ""
    decimals: int = 0
    size: float = 30.0
    color: RGB = (0.95, 0.95, 0.95)
    corner: str = "top_right"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["color"] = list(self.color)
        return d


@dataclass
class ChartSpec:
    chart_type: str = LINE
    x_column: str = ""
    sort_column: str = ""             # blank = keep CSV row order
    sort_ascending: bool = True
    group_column: str = ""            # BAR/HBAR: category to group by
    aggregation: str = "sum"          # BAR/HBAR
    max_bars: int = 20
    series: List[SeriesSpec] = field(default_factory=list)
    x_axis: AxisSpec = field(default_factory=lambda: AxisSpec())
    y_axis: AxisSpec = field(default_factory=lambda: AxisSpec())
    y2_axis: AxisSpec = field(default_factory=lambda: AxisSpec(enabled=False))
    category: CategorySpec = field(default_factory=CategorySpec)
    size: SizeSpec = field(default_factory=SizeSpec)
    comp: CompSpec = field(default_factory=CompSpec)
    style: StyleSpec = field(default_factory=StyleSpec)
    readout: ReadoutSpec = field(default_factory=ReadoutSpec)
    arc_mode: str = "chord"           # "chord" | "bezier"
    bar_gap: float = 0.28             # fraction of slot

    # -- convenience --------------------------------------------------------
    @property
    def is_bar(self) -> bool:
        return self.chart_type in (BAR, HBAR)

    @property
    def uses_path(self) -> bool:
        return self.chart_type in (LINE, AREA, CONNECTED_SCATTER)

    def left_series(self) -> List[SeriesSpec]:
        return [s for s in self.series if s.axis == "left"]

    def right_series(self) -> List[SeriesSpec]:
        return [s for s in self.series if s.axis == "right"]

    # -- persistence --------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chart_type": self.chart_type,
            "x_column": self.x_column,
            "sort_column": self.sort_column,
            "sort_ascending": self.sort_ascending,
            "group_column": self.group_column,
            "aggregation": self.aggregation,
            "max_bars": self.max_bars,
            "arc_mode": self.arc_mode,
            "bar_gap": self.bar_gap,
            "series": [s.to_dict() for s in self.series],
            "x_axis": self.x_axis.to_dict(),
            "y_axis": self.y_axis.to_dict(),
            "y2_axis": self.y2_axis.to_dict(),
            "category": self.category.to_dict(),
            "size": self.size.to_dict(),
            "comp": self.comp.to_dict(),
            "style": self.style.to_dict(),
            "readout": self.readout.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChartSpec":
        spec = cls()
        for key in ("chart_type", "x_column", "sort_column", "sort_ascending",
                    "group_column", "aggregation", "max_bars", "arc_mode", "bar_gap"):
            if key in d:
                setattr(spec, key, d[key])
        spec.series = []
        for sd in d.get("series", []):
            s = SeriesSpec()
            for k, v in sd.items():
                if hasattr(s, k):
                    setattr(s, k, tuple(v) if k == "color" else v)
            spec.series.append(s)
        for key, klass in (("x_axis", AxisSpec), ("y_axis", AxisSpec), ("y2_axis", AxisSpec),
                           ("category", CategorySpec), ("size", SizeSpec),
                           ("comp", CompSpec), ("style", StyleSpec), ("readout", ReadoutSpec)):
            sub = d.get(key)
            if not sub:
                continue
            obj = klass()
            for k, v in sub.items():
                if not hasattr(obj, k):
                    continue
                if k == "colors":
                    v = {ck: tuple(cv) for ck, cv in v.items()}
                elif k.endswith("color") and isinstance(v, list):
                    v = tuple(v)
                setattr(obj, k, v)
            setattr(spec, key, obj)
        return spec

    @classmethod
    def from_json(cls, s: str) -> "ChartSpec":
        return cls.from_dict(json.loads(s))


# ---------------------------------------------------------------------------
# palette used when auto-assigning series / category colours
# ---------------------------------------------------------------------------
PALETTE: List[RGB] = [
    (0.95, 0.95, 0.95),
    (0.40, 0.85, 0.90),
    (0.95, 0.70, 0.35),
    (0.90, 0.45, 0.65),
    (0.55, 0.80, 0.55),
    (0.70, 0.60, 0.95),
    (0.95, 0.85, 0.45),
    (0.45, 0.65, 0.95),
    (0.90, 0.55, 0.40),
    (0.60, 0.63, 0.67),
]


def palette_color(i: int) -> RGB:
    return PALETTE[i % len(PALETTE)]

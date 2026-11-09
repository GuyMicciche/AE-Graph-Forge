"""
jsxgen.py -- emits an ExtendScript (.jsx) file that builds the chart in AE.

Style is deliberately faithful to the reference scripts: an IIFE wrapped in
beginUndoGroup/endUndoGroup, a CONFIG block, precomputed pixel-space data
arrays, a set of small helper functions, then the build.

The one architectural upgrade over the references is MASTER_CONTROLS. Instead
of a lone "Progress" slider, the null carries a full rig -- Progress, Line
Weight, Dot Scale, Dot Opacity, Reveal Softness, Grid Opacity, Labels
Opacity, Playhead Opacity, Tip Size, plus one Color control per series and
per category. Every layer in the comp reads its look from that null, so the
whole graph is art-directable from a single controller after the build.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from typing import Dict, List, Optional, Sequence, Tuple

from .build import BarModel, DotModel, RenderModel, SeriesModel
from .geometry import fmt_list, fmt_num, fmt_pairs, r2, r6
from .spec import (AREA, BAR, CONNECTED_SCATTER, ChartSpec, DONUT, GROUPED_BAR,
                   HBAR, LINE, LOLLIPOP, STACKED_AREA, STACKED_BAR, STEP_LINE, RGB,
                   SCATTER)

IND = "    "


# ---------------------------------------------------------------------------
# small emitters
# ---------------------------------------------------------------------------
def jstr(s: str) -> str:
    """JavaScript string literal, safely escaped."""
    out = (str(s).replace("\\", "\\\\").replace('"', '\\"')
           .replace("\n", "\\n").replace("\r", "").replace("\t", "\\t"))
    return f'"{out}"'


def _sq(text: str, newline: bool = False) -> str:
    """Single-quoted JS literal, used when building an expression by
    concatenation inside a generated loop."""
    esc = str(text).replace("\\", "\\\\").replace("'", "\\'")
    return "'" + esc + ("\\n" if newline else "") + "'"


def jcolor(c: Sequence[float]) -> str:
    return "[" + ", ".join(f"{float(v):.4f}" for v in c[:3]) + "]"


def fx_name(s: str) -> str:
    """Effect names must survive AE's property lookup by name."""
    cleaned = re.sub(r"[^A-Za-z0-9 _\-\.]", " ", str(s)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or "Item")[:31]


def layer_name(s: str, fallback: str = "LAYER") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(s)).strip("_").upper()
    return cleaned or fallback


def expr(lines: Sequence[str]) -> str:
    """Wrap a list of JS lines as a joinExpr([...]) call in the output."""
    body = (",\n" + IND).join(jstr(l) for l in lines)
    return "joinExpr([\n" + IND + body + "\n])"


CTRL = 'var ctrl = thisComp.layer("MASTER_CONTROLS");'
PROG = 'var progress = ctrl.effect("Progress")("Slider");'


# ---------------------------------------------------------------------------
# generator
# ---------------------------------------------------------------------------
class JSXGenerator:
    def __init__(self, model: RenderModel, spec: Optional[ChartSpec] = None):
        self.m = model
        self.s = spec or model.spec
        self.lines: List[str] = []
        self._ctrl_names: Dict[str, str] = {}   # logical key -> effect name
        self._used_fx: set = set()

    # -- buffer helpers --------------------------------------------------
    def w(self, text: str = "", indent: int = 1) -> None:
        if text == "":
            self.lines.append("")
        else:
            for ln in text.split("\n"):
                self.lines.append((IND * indent + ln).rstrip())

    def section(self, title: str, indent: int = 1) -> None:
        self.w("")
        self.w("// " + "-" * 63, indent)
        self.w(f"// {title}", indent)
        self.w("// " + "-" * 63, indent)

    # -- control naming --------------------------------------------------
    def ctrl(self, key: str, pretty: Optional[str] = None) -> str:
        if key in self._ctrl_names:
            return self._ctrl_names[key]
        base = fx_name(pretty or key)
        name, i = base, 2
        while name in self._used_fx:
            name = f"{base} {i}"[:31]
            i += 1
        self._used_fx.add(name)
        self._ctrl_names[key] = name
        return name

    def read(self, key: str, kind: str = "Slider") -> str:
        return f'ctrl.effect("{self._ctrl_names[key]}")("{kind}")'

    # =====================================================================
    def generate(self) -> str:
        m, s = self.m, self.s
        if not m.ok:
            raise ValueError(m.error or "Model is not valid.")

        self._plan_controls()
        self._header()
        self.w("(function buildChart() {", 0)
        self.w("")
        self.w(f'app.beginUndoGroup({jstr("Build " + s.comp.name)});')
        self.w("")
        self.w("try {")
        self.w("")
        self._config()
        self._data()
        self._helpers()
        self._comp_and_controls()
        if s.chart_type != DONUT:
            self._grid_and_axes()
        self._titles()
        self._legend()
        if s.chart_type == DONUT:
            self._donut()
        elif s.is_bar:
            self._bars()
        else:
            self._series()
            self._playhead_and_tip()
        self._readout()
        self._finish()
        self.w("")
        self.w("} catch (err) {")
        self.w('alert("Build failed: " + err.toString() + "\\nLine: " '
               '+ (err.line || "unknown") + "\\nFile: " + (err.fileName || "unknown"));')
        self.w("throw err;")
        self.w("} finally {")
        self.w("app.endUndoGroup();")
        self.w("}")
        self.w("")
        self.w("})();", 0)
        return "\n".join(self.lines) + "\n"

    # -- which controls exist -------------------------------------------
    def _plan_controls(self) -> None:
        m, s = self.m, self.s
        self.ctrl("progress", "Progress")
        if s.style.bind_to_controls:
            if not s.is_bar:
                self.ctrl("line_weight", "Line Weight")
            self.ctrl("dot_scale", "Dot Scale")
            self.ctrl("dot_opacity", "Dot Opacity")
            self.ctrl("softness", "Reveal Softness")
            self.ctrl("grid_opacity", "Grid Opacity")
            self.ctrl("grid_width", "Grid Width")
            self.ctrl("labels_opacity", "Labels Opacity")
            self.ctrl("title_opacity", "Title Opacity")
            self.ctrl("legend_opacity", "Legend Opacity")
            if s.chart_type in (AREA, STACKED_AREA) or any(
                    sm.spec.fill_opacity > 0 for sm in m.series):
                self.ctrl("area_opacity", "Area Opacity")
            if s.is_bar:
                self.ctrl("bar_width", "Bar Width")
                self.ctrl("bar_round", "Bar Roundness")
            if s.chart_type == DONUT:
                # Outer as a percentage of the built size, inner as a
                # percentage of the outer, so dragging Ring Inner to 0 turns
                # the donut into a pie without touching anything else.
                self.ctrl("ring_outer", "Ring Outer")
                self.ctrl("ring_inner", "Ring Inner")
                self.ctrl("ring_gap", "Ring Gap")
            if s.readout.enabled:
                self.ctrl("readout_opacity", "Readout Opacity")
            if s.style.show_playhead and not s.is_bar:
                self.ctrl("playhead_opacity", "Playhead Opacity")
                self.ctrl("playhead_width", "Playhead Width")
            if s.style.show_tip_dot and not s.is_bar:
                self.ctrl("tip_size", "Tip Size")
            for i, sm in enumerate(m.series):
                self.ctrl(f"series_color_{i}", f"{sm.label} Color")
            for le in m.legend:
                key = f"cat_color_{le.label}"
                if key not in self._ctrl_names and self._is_category(le.label):
                    self.ctrl(key, f"{le.label} Color")

    def _is_category(self, label: str) -> bool:
        """Does this legend entry stand for a group that has its own layers?

        Only those get a colour control, so a plain multi-series legend does
        not sprout duplicates of the per-series colours. Donut wedges and bar
        groups qualify: each is a layer whose fill can be rewired live.
        """
        if any(label == d.label for sm in self.m.series for d in sm.dots):
            return True
        if any(label == g.label for g in self.m.segments):
            return True
        return False

    # -- header ----------------------------------------------------------
    def _header(self) -> None:
        m, s = self.m, self.s
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        kind = {LINE: "line chart", AREA: "area chart", STEP_LINE: "step line chart",
                STACKED_AREA: "stacked area chart",
                CONNECTED_SCATTER: "connected scatterplot", SCATTER: "scatterplot",
                BAR: "bar chart", HBAR: "horizontal bar chart",
                GROUPED_BAR: "grouped bar chart", STACKED_BAR: "stacked bar chart",
                LOLLIPOP: "lollipop chart",
                DONUT: "donut chart"}.get(s.chart_type, "chart")
        title = s.style.title or s.comp.name
        series_txt = ", ".join(sm.label for sm in m.series) or "-"
        self.w("// " + "=" * 71, 0)
        self.w(f"// {title.upper()}", 0)
        self.w("// " + "-" * 71, 0)
        self.w(f"// A {kind} built from {m.n_points} data points. Generated by", 0)
        self.w(f"// AE Graph Forge on {stamp}.", 0)
        self.w("//", 0)
        self.w(f"// X: {s.x_column or '(index)'}", 0)
        self.w(f"// Y: {series_txt}", 0)
        if s.category.enabled and s.category.column:
            self.w(f"// Colour: {s.category.column}", 0)
        if s.size.enabled and s.size.column:
            self.w(f"// Size:   {s.size.column}", 0)
        self.w("//", 0)
        self.w("// Run this in After Effects: File > Scripts > Run Script File...", 0)
        self.w("// It builds one new composition and does not touch anything else in", 0)
        self.w("// your project. Every look property is wired to MASTER_CONTROLS --", 0)
        self.w('// scrub "Progress" to drive the reveal, and use the other controls', 0)
        self.w("// on that null to re-art-direct the whole graph after the build.", 0)
        self.w("// " + "=" * 71, 0)
        self.w("")

    # -- config ----------------------------------------------------------
    def _config(self) -> None:
        s = self.s
        c = s.comp
        self.section("CONFIG")
        self.w(f"var COMP_NAME = {jstr(c.name)};")
        self.w(f"var COMP_W = {int(c.width)}, COMP_H = {int(c.height)}, "
               f"COMP_FPS = {fmt_num(c.fps)}, COMP_DUR = {fmt_num(c.duration)};")
        self.w(f"var PROGRESS_START_T = {fmt_num(c.progress_start)};")
        self.w(f"var PROGRESS_END_T   = {fmt_num(c.progress_end)};")
        self.w("")
        self.w(f"var PLOT_L = {fmt_num(c.plot_left)}, PLOT_R = {fmt_num(c.plot_right)};")
        self.w(f"var PLOT_T = {fmt_num(c.plot_top)}, PLOT_B = {fmt_num(c.plot_bottom)};")
        self.w("")
        self.w(f"var N = {self.m.n_points};")
        self.w("")
        st = s.style
        self.w(f"var BG_COLOR    = {jcolor(st.bg_color)};")
        self.w(f"var GRID_COLOR  = {jcolor(st.grid_color)};")
        self.w(f"var AXIS_COLOR  = {jcolor(st.axis_text_color)};")
        self.w(f"var TITLE_COLOR = {jcolor(st.title_color)};")
        self.w(f"var SUB_COLOR   = {jcolor(st.subtitle_color)};")
        self.w(f"var CAP_COLOR   = {jcolor(st.caption_color)};")

    # -- data ------------------------------------------------------------
    def _data(self) -> None:
        m, s = self.m, self.s
        if s.is_bar:
            return
        self.section("PIXEL-SPACE GEOMETRY (precomputed from the CSV)")
        self.w("// VERTICES / tangents form a Catmull-Rom-smoothed bezier path:")
        self.w("//     out[i] = (P[i+1] - P[i-1]) / 6,  in[i] = -out[i]")
        self.w("// ARC is the cumulative length fraction at each vertex, so a")
        self.w("// Trim Paths reveal stays in step with a uniform one-point-at-a-time")
        self.w("// sweep of the Progress slider.")
        self.w("")
        for i, sm in enumerate(m.series):
            p = sm.path
            tag = f"S{i}"
            if p is not None:
                self.w(f"// --- {sm.label} ---")
                self.w(f"var {tag}_VERTICES = {fmt_pairs(p.points, r2)};")
                self.w(f"var {tag}_IN  = {fmt_pairs(p.in_tangents, r6)};")
                self.w(f"var {tag}_OUT = {fmt_pairs(p.out_tangents, r6)};")
                self.w(f"var {tag}_ARC = {fmt_list(p.arc, lambda v: round(v, 5))};")
                self.w(f"var {tag}_PX = {fmt_list(p.xs, r2)};")
                self.w(f"var {tag}_PY = {fmt_list(p.ys, r2)};")
            if sm.dots:
                self.w(f"var {tag}_DOT_X = {fmt_list([d.x for d in sm.dots], r2)};")
                self.w(f"var {tag}_DOT_Y = {fmt_list([d.y for d in sm.dots], r2)};")
                if s.size.enabled:
                    self.w(f"var {tag}_DIAM = {fmt_list([d.diameter for d in sm.dots], r2)};")
            self.w("")
        # NOTE: readout values are NOT emitted as a script-scope var. An AE
        # expression evaluates in its own scope and cannot see anything the
        # build script declared, so the array has to be inlined into the
        # expression text itself (which is what the reference scripts do).

    # -- helpers ---------------------------------------------------------
    def _helpers(self) -> None:
        s = self.s
        fonts = ", ".join(jstr(f) for f in s.style.resolved_fonts())
        gw = int(max(1, round(s.style.grid_width)))
        self.section("SHARED HELPERS")
        self.w(f"""
function joinExpr(lines) {{
    return lines.join("\\n");
}}

// ---------------------------------------------------------------------------
// Shape property lookup.
//
// After Effects invalidates a stored shape-property reference as soon as more
// items are added to the same vector group, so a handle grabbed mid-build goes
// stale even though the layer is still perfectly valid. Nothing below ever
// caches a property object: every vector property is given a name at creation
// time and looked back up by name at the moment it is used.
// ---------------------------------------------------------------------------
function vgroup(layer, groupName) {{
    var contents = layer.property("Contents");
    for (var i = 1; i <= contents.numProperties; i++) {{
        if (contents.property(i).name === groupName) return contents.property(i);
    }}
    return null;
}}

function vprop(layer, groupName, propName) {{
    var g = vgroup(layer, groupName);
    if (g === null) return null;
    var c = g.property("Contents");
    for (var i = 1; i <= c.numProperties; i++) {{
        if (c.property(i).name === propName) return c.property(i);
    }}
    return null;
}}

function addSlider(layer, name, value) {{
    var fx = layer.property("Effects").addProperty("ADBE Slider Control");
    fx.name = name;
    fx.property("Slider").setValue(value);
    return fx;
}}

function addColor(layer, name, rgb) {{
    var fx = layer.property("Effects").addProperty("ADBE Color Control");
    fx.name = name;
    fx.property("Color").setValue([rgb[0], rgb[1], rgb[2], 1]);
    return fx;
}}

function spanLayer(layer) {{
    layer.inPoint = 0;
    layer.outPoint = comp.duration;
    return layer;
}}

// Vertices are precomputed in COMPOSITION pixel space, so the layer and its
// vector group both need an identity transform or the graph lands offset from
// the text and gridlines. Setting anchor and position to the same point gives
// that identity while leaving the pivot at comp centre, so scaling or rotating
// the finished graph behaves the way you would expect.
function centerShapeLayer(layer, groupName) {{
    var cx = COMP_W / 2;
    var cy = COMP_H / 2;
    var tr = layer.property("Transform");
    tr.property("Anchor Point").setValue([cx, cy]);
    tr.property("Position").setValue([cx, cy]);
    var g = vgroup(layer, groupName);
    if (g !== null) {{
        var gt = g.property("Transform");
        gt.property("Anchor Point").setValue([cx, cy]);
        gt.property("Position").setValue([cx, cy]);
    }}
    return layer;
}}

function setFont(td) {{
    var fontCandidates = [{fonts}];
    for (var f = 0; f < fontCandidates.length; f++) {{
        try {{ td.font = fontCandidates[f]; break; }} catch (e) {{}}
    }}
}}

function makeText(str, size, color, pos, justify) {{
    var t = spanLayer(comp.layers.addText(str));
    var td = t.property("Source Text").value;
    td.fontSize = size;
    td.fillColor = color;
    setFont(td);
    try {{
        if (justify === "left") {{
            td.justification = ParagraphJustification.LEFT_JUSTIFY;
        }} else if (justify === "right") {{
            td.justification = ParagraphJustification.RIGHT_JUSTIFY;
        }} else {{
            td.justification = ParagraphJustification.CENTER_JUSTIFY;
        }}
    }} catch (e) {{}}
    t.property("Source Text").setValue(td);
    t.property("Transform").property("Position").setValue(pos);
    t.property("Transform").property("Anchor Point").setValue([0, 0]);
    return t;
}}

function addHGridline(y, w) {{
    var g = spanLayer(comp.layers.addSolid(GRID_COLOR, "Gridline", Math.max(1, Math.round(w)), {gw}, 1));
    g.property("Transform").property("Anchor Point").setValue([0, 0]);
    g.property("Transform").property("Position").setValue([PLOT_L + w / 2, y]);
    g.property("Transform").property("Opacity").setValue({fmt_num(s.style.grid_opacity)});
    return g;
}}

function addVGridline(x, h) {{
    var g = spanLayer(comp.layers.addSolid(GRID_COLOR, "Gridline", {gw}, Math.max(1, Math.round(h)), 1));
    g.property("Transform").property("Position").setValue([x, PLOT_T + h / 2]);
    g.property("Transform").property("Opacity").setValue({fmt_num(s.style.grid_opacity)});
    return g;
}}

function addLegendSwatch(x, y, color) {{
    var layer = spanLayer(comp.layers.addShape());
    layer.name = "LegendSwatch";
    var group = layer.property("Contents").addProperty("ADBE Vector Group");
    group.name = "SwatchGroup";
    var rect = group.property("Contents").addProperty("ADBE Vector Shape - Rect");
    rect.name = "SwatchRect";
    rect.property("Size").setValue([20, 20]);
    var fill = group.property("Contents").addProperty("ADBE Vector Graphic - Fill");
    fill.name = "SwatchFill";
    fill.property("Color").setValue(color);
    layer.property("Transform").property("Anchor Point").setValue([0, 0]);
    layer.property("Transform").property("Position").setValue([x, y]);
    return layer;
}}

function addLegendCircle(x, y, diameter) {{
    var layer = spanLayer(comp.layers.addShape());
    layer.name = "LegendCircle";
    var group = layer.property("Contents").addProperty("ADBE Vector Group");
    group.name = "CircleGroup";
    var ellipse = group.property("Contents").addProperty("ADBE Vector Shape - Ellipse");
    ellipse.name = "CircleShape";
    ellipse.property("Size").setValue([diameter, diameter]);
    var stroke = group.property("Contents").addProperty("ADBE Vector Graphic - Stroke");
    stroke.name = "CircleStroke";
    stroke.property("Color").setValue(AXIS_COLOR);
    stroke.property("Stroke Width").setValue(1.5);
    layer.property("Transform").property("Anchor Point").setValue([0, 0]);
    layer.property("Transform").property("Position").setValue([x, y]);
    return layer;
}}

function buildLineLayer(name, vertices, inT, outT, color, strokeWidth, closed) {{
    var layer = spanLayer(comp.layers.addShape());
    layer.name = name;

    var group = layer.property("Contents").addProperty("ADBE Vector Group");
    group.name = "LineGroup";

    var pathProp = group.property("Contents").addProperty("ADBE Vector Shape - Group");
    pathProp.name = "LinePath";

    var shape = new Shape();
    shape.vertices = vertices;
    shape.inTangents = inT;
    shape.outTangents = outT;
    shape.closed = (closed === true);
    pathProp.property("Path").setValue(shape);

    var stroke = group.property("Contents").addProperty("ADBE Vector Graphic - Stroke");
    stroke.name = "LineStroke";
    stroke.property("Color").setValue(color);
    stroke.property("Stroke Width").setValue(strokeWidth);
    stroke.property("Line Cap").setValue(2);
    stroke.property("Line Join").setValue(2);

    var trim = group.property("Contents").addProperty("ADBE Vector Filter - Trim");
    trim.name = "Trim";

    // group construction is finished, so it is now safe to place the layer
    centerShapeLayer(layer, "LineGroup");
    return layer;
}}

function buildAreaLayer(name, vertices, inT, outT, color, opacity) {{
    var layer = spanLayer(comp.layers.addShape());
    layer.name = name;
    var group = layer.property("Contents").addProperty("ADBE Vector Group");
    group.name = "AreaGroup";
    var pathProp = group.property("Contents").addProperty("ADBE Vector Shape - Group");
    pathProp.name = "AreaPath";
    var shape = new Shape();
    shape.vertices = vertices;
    shape.inTangents = inT;
    shape.outTangents = outT;
    shape.closed = true;
    pathProp.property("Path").setValue(shape);
    var fill = group.property("Contents").addProperty("ADBE Vector Graphic - Fill");
    fill.name = "AreaFill";
    fill.property("Color").setValue(color);
    fill.property("Opacity").setValue(opacity);
    centerShapeLayer(layer, "AreaGroup");
    return layer;
}}

function buildDot(name, diameter, color) {{
    var layer = spanLayer(comp.layers.addShape());
    layer.name = name;
    var group = layer.property("Contents").addProperty("ADBE Vector Group");
    group.name = "Dot";
    var ellipse = group.property("Contents").addProperty("ADBE Vector Shape - Ellipse");
    ellipse.name = "DotShape";
    ellipse.property("Size").setValue([diameter, diameter]);
    var fill = group.property("Contents").addProperty("ADBE Vector Graphic - Fill");
    fill.name = "DotFill";
    fill.property("Color").setValue(color);
    // A dot is placed by Position, so its anchor stays at the shape centre and
    // Scale pivots on the dot itself.
    layer.property("Transform").property("Anchor Point").setValue([0, 0]);
    return layer;
}}

function buildBar(name, w, h, color) {{
    var layer = spanLayer(comp.layers.addShape());
    layer.name = name;
    var group = layer.property("Contents").addProperty("ADBE Vector Group");
    group.name = "Bar";
    var rect = group.property("Contents").addProperty("ADBE Vector Shape - Rect");
    rect.name = "BarRect";
    rect.property("Size").setValue([w, h]);
    var fill = group.property("Contents").addProperty("ADBE Vector Graphic - Fill");
    fill.name = "BarFill";
    fill.property("Color").setValue(color);
    // A bar grows from its baseline, so the anchor stays there rather than at
    // comp centre.
    layer.property("Transform").property("Anchor Point").setValue([0, 0]);
    return layer;
}}

function buildRing(name, radius, thickness, color) {{
    var layer = spanLayer(comp.layers.addShape());
    layer.name = name;
    var group = layer.property("Contents").addProperty("ADBE Vector Group");
    group.name = "RingGroup";
    var ellipse = group.property("Contents").addProperty("ADBE Vector Shape - Ellipse");
    ellipse.name = "RingShape";
    ellipse.property("Size").setValue([radius * 2, radius * 2]);
    var stroke = group.property("Contents").addProperty("ADBE Vector Graphic - Stroke");
    stroke.name = "RingStroke";
    stroke.property("Color").setValue(color);
    stroke.property("Stroke Width").setValue(thickness);
    stroke.property("Line Cap").setValue(1);
    var trim = group.property("Contents").addProperty("ADBE Vector Filter - Trim");
    trim.name = "RingTrim";
    layer.property("Transform").property("Anchor Point").setValue([0, 0]);
    return layer;
}}

function easyEase(prop, idx) {{
    var ease = new KeyframeEase(0, {fmt_num(s.comp.ease_influence)});
    prop.setTemporalEaseAtKey(idx, [ease], [ease]);
}}

function buildPlayhead() {{
    var ph = spanLayer(comp.layers.addSolid([0.95, 0.95, 0.95], "Playhead", 2,
                       Math.max(1, Math.round(PLOT_B - PLOT_T)), 1));
    ph.property("Transform").property("Opacity").setValue({fmt_num(s.style.playhead_opacity)});
    return ph;
}}
""".strip("\n"))

    # -- comp + controls -------------------------------------------------
    def _comp_and_controls(self) -> None:
        m, s = self.m, self.s
        self.section("COMP + BACKGROUND")
        self.w("var comp = app.project.items.addComp(COMP_NAME, COMP_W, COMP_H, 1, COMP_DUR, COMP_FPS);")
        if s.comp.open_in_viewer:
            self.w("comp.openInViewer();")
        self.w('var bg = spanLayer(comp.layers.addSolid(BG_COLOR, "BG", COMP_W, COMP_H, 1));')

        self.section("MASTER_CONTROLS  -- one null drives the entire graph")
        self.w("var controls = spanLayer(comp.layers.addNull());")
        self.w('controls.name = "MASTER_CONTROLS";')
        self.w(f'addSlider(controls, {jstr(self._ctrl_names["progress"])}, 0);')

        def slider(key: str, value: float) -> None:
            if key in self._ctrl_names:
                self.w(f'addSlider(controls, {jstr(self._ctrl_names[key])}, {fmt_num(value)});')

        st = s.style
        slider("line_weight", 100)
        slider("grid_width", 100)
        slider("title_opacity", 100)
        slider("legend_opacity", 100)
        slider("readout_opacity", 100)
        slider("playhead_width", 100)
        slider("bar_width", 100)
        slider("bar_round", 0)
        slider("area_opacity", 100)
        slider("ring_outer", 100)
        slider("ring_inner", round(
            (m.donut_r_inner / m.donut_r_outer * 100.0) if m.donut_r_outer else 0.0, 2))
        # the configured gap is already cut into SEG_START / SEG_END, so this
        # slider starts at zero and only adds to it
        slider("ring_gap", 0)
        slider("dot_scale", 100)
        slider("dot_opacity", st.dot_opacity)
        slider("softness", st.dot_reveal_lead)
        slider("grid_opacity", st.grid_opacity)
        slider("labels_opacity", 100)
        slider("playhead_opacity", st.playhead_opacity)
        slider("tip_size", st.tip_dot_size)

        for i, sm in enumerate(m.series):
            key = f"series_color_{i}"
            if key in self._ctrl_names:
                self.w(f'addColor(controls, {jstr(self._ctrl_names[key])}, {jcolor(sm.color)});')
        for le in m.legend:
            key = f"cat_color_{le.label}"
            if key in self._ctrl_names:
                self.w(f'addColor(controls, {jstr(self._ctrl_names[key])}, {jcolor(le.color)});')

        self.w("")
        self.w('var progressSlider = controls.property("Effects")'
               f'.property({jstr(self._ctrl_names["progress"])}).property("Slider");')
        self.w("progressSlider.setValueAtTime(PROGRESS_START_T, 0);")
        self.w("progressSlider.setValueAtTime(PROGRESS_END_T, 100);")
        self.w("easyEase(progressSlider, 1);")
        self.w("easyEase(progressSlider, 2);")

        if s.style.bind_to_controls:
            self.w("")
            self.w("// Re-usable snippets so every layer reads the same rig.")
            self.w(f"var GRID_OP_EXPR = {expr([CTRL, self._line('grid_opacity')])};")
            self.w(f"var LABEL_OP_EXPR = {expr([CTRL, self._line('labels_opacity')])};")

    def _line(self, key: str) -> str:
        return f'ctrl.effect("{self._ctrl_names[key]}")("Slider");'

    # -- gridlines + axes ------------------------------------------------
    def _grid_and_axes(self) -> None:
        m, s = self.m, self.s
        bind = s.style.bind_to_controls
        self.section("GRIDLINES + AXIS LABELS")

        show_h = s.y_axis.show_grid and (m.y_ticks or m.y2_ticks)
        if m.y_ticks:
            self.w("var yTickPix = " + fmt_list([t.pixel for t in m.y_ticks], r2) + ";")
            self.w("var yTickLab = [" + ", ".join(jstr(t.label) for t in m.y_ticks) + "];")
            if m.y2_ticks:
                self.w("var y2TickLab = [" + ", ".join(jstr(t.label) for t in m.y2_ticks) + "];")
            self.w("for (var g = 0; g < yTickPix.length; g++) {", 1)
            if show_h and (not s.is_bar or s.chart_type == BAR):
                self.w("var gl = addHGridline(yTickPix[g], PLOT_R - PLOT_L);", 2)
                if bind:
                    self.w('gl.property("Transform").property("Opacity").expression = GRID_OP_EXPR;', 2)
            self.w(f"var lab = makeText(yTickLab[g], {fmt_num(s.y_axis.label_size)}, AXIS_COLOR, "
                   f"[PLOT_L - 20, yTickPix[g] + 8], \"right\");", 2)
            if bind:
                self.w('lab.property("Transform").property("Opacity").expression = LABEL_OP_EXPR;', 2)
            if m.y2_ticks:
                self.w(f"var lab2 = makeText(y2TickLab[g], {fmt_num(s.y2_axis.label_size)}, AXIS_COLOR, "
                       f"[PLOT_R + 20, yTickPix[g] + 8], \"left\");", 2)
                if bind:
                    self.w('lab2.property("Transform").property("Opacity").expression = LABEL_OP_EXPR;', 2)
            self.w("}", 1)

        if m.x_ticks:
            self.w("")
            self.w("var xTickPix = " + fmt_list([t.pixel for t in m.x_ticks], r2) + ";")
            self.w("var xTickLab = [" + ", ".join(jstr(t.label) for t in m.x_ticks) + "];")
            self.w("for (var xt = 0; xt < xTickPix.length; xt++) {", 1)
            if s.x_axis.show_grid and s.chart_type in (SCATTER, CONNECTED_SCATTER, HBAR):
                self.w("var vg = addVGridline(xTickPix[xt], PLOT_B - PLOT_T);", 2)
                if bind:
                    self.w('vg.property("Transform").property("Opacity").expression = GRID_OP_EXPR;', 2)
            self.w(f"var xlab = makeText(xTickLab[xt], {fmt_num(s.x_axis.label_size)}, AXIS_COLOR, "
                   f"[xTickPix[xt], PLOT_B + 45], \"center\");", 2)
            if s.chart_type == BAR and self._long_labels():
                self.w('xlab.property("Transform").property("Rotation").setValue(-38);', 2)
            if bind:
                self.w('xlab.property("Transform").property("Opacity").expression = LABEL_OP_EXPR;', 2)
            self.w("}", 1)

        # axis titles
        self.w("")
        # On a horizontal bar chart the value axis runs along the bottom, so the
        # configured y-axis title belongs there instead of up the left side.
        bottom_title = s.y_axis.title if s.chart_type == HBAR else s.x_axis.title
        side_title = "" if s.chart_type == HBAR else s.y_axis.title
        bt_size = (s.y_axis if s.chart_type == HBAR else s.x_axis).title_size
        st_size = s.y_axis.title_size
        if bottom_title:
            self.w(f"makeText({jstr(bottom_title)}, {fmt_num(bt_size)}, AXIS_COLOR, "
                   f"[(PLOT_L + PLOT_R) / 2, PLOT_B + 95], \"center\");")
        if side_title:
            self.w(f"var yTitle = makeText({jstr(side_title)}, {fmt_num(st_size)}, "
                   f"AXIS_COLOR, [PLOT_L - 95, (PLOT_T + PLOT_B) / 2], \"center\");")
            self.w('yTitle.property("Transform").property("Rotation").setValue(-90);')
        if m.y2_ticks and s.y2_axis.title:
            self.w(f"var y2Title = makeText({jstr(s.y2_axis.title)}, 22, AXIS_COLOR, "
                   f"[PLOT_R + 95, (PLOT_T + PLOT_B) / 2], \"center\");")
            self.w('y2Title.property("Transform").property("Rotation").setValue(90);')
        if s.y_axis.unit:
            self.w(f"makeText({jstr(s.y_axis.unit)}, {fmt_num(s.y_axis.unit_size)}, "
                   f"CAP_COLOR, [PLOT_L - 20, PLOT_T - 30], \"right\");")
        if m.y2_ticks and s.y2_axis.unit:
            self.w(f"makeText({jstr(s.y2_axis.unit)}, {fmt_num(s.y2_axis.unit_size)}, "
                   f"CAP_COLOR, [PLOT_R + 20, PLOT_T - 30], \"left\");")
        # The X unit sits just past the right-hand end of the value axis, which
        # is where a reader looks after scanning the tick labels.
        if s.x_axis.unit:
            self.w(f"makeText({jstr(s.x_axis.unit)}, {fmt_num(s.x_axis.unit_size)}, "
                   f"CAP_COLOR, [PLOT_R + 20, PLOT_B + 45], \"left\");")

    def _long_labels(self) -> bool:
        return any(len(t.label) > 6 for t in self.m.x_ticks)

    # -- titles ----------------------------------------------------------
    def _titles(self) -> None:
        s = self.s
        st = s.style
        self.section("TITLE / SUBTITLE / CAPTION")
        y = 80.0
        if st.title:
            self.w(f"makeText({jstr(st.title)}, {fmt_num(st.title_size)}, TITLE_COLOR, "
                   f"[PLOT_L, {fmt_num(y)}], \"left\");")
            y += st.title_size * 0.85
        if st.subtitle:
            self.w(f"makeText({jstr(st.subtitle)}, {fmt_num(st.subtitle_size)}, SUB_COLOR, "
                   f"[PLOT_L, {fmt_num(y)}], \"left\");")
            y += st.subtitle_size * 1.5
        if st.caption:
            self.w(f"makeText({jstr(st.caption)}, {fmt_num(st.caption_size)}, CAP_COLOR, "
                   f"[PLOT_L, {fmt_num(y)}], \"left\");")

    # -- legend ----------------------------------------------------------
    def _legend(self) -> None:
        m, s = self.m, self.s
        lay = m.legend_layout
        if not lay.items:
            return
        self.section("LEGEND")
        if lay.title:
            self.w(f"makeText({jstr(lay.title)}, 18, CAP_COLOR, "
                   f"[{fmt_num(lay.title_x)}, {fmt_num(lay.title_y)}], \"left\");")
        n = 0
        for it in lay.items:
            if it.kind == "swatch":
                self.w(f"var sw{n} = addLegendSwatch({fmt_num(it.x)}, {fmt_num(it.y)}, "
                       f"{jcolor(it.color)});")
                if s.style.bind_to_controls and it.ctrl_key in self._ctrl_names:
                    bind_expr = expr([
                        CTRL,
                        f'ctrl.effect({jstr(self._ctrl_names[it.ctrl_key])})("Color");'])
                    self.w(f'vprop(sw{n}, "SwatchGroup", "SwatchFill")'
                           f'.property("Color").expression = {bind_expr};')
                self.w(f"makeText({jstr(it.label)}, {fmt_num(it.label_size)}, "
                       f"[0.85, 0.85, 0.85], "
                       f"[{fmt_num(it.label_x)}, {fmt_num(it.label_y)}], \"left\");")
            else:
                self.w(f"addLegendCircle({fmt_num(it.x)}, {fmt_num(it.y)}, "
                       f"{fmt_num(it.diameter)});")
                self.w(f"makeText({jstr(it.label)}, {fmt_num(it.label_size)}, AXIS_COLOR, "
                       f"[{fmt_num(it.label_x)}, {fmt_num(it.label_y)}], \"left\");")
            n += 1

    # -- series (lines, areas, dots) -------------------------------------
    def _series(self) -> None:
        m, s = self.m, self.s
        bind = s.style.bind_to_controls
        for i, sm in enumerate(m.series):
            tag = f"S{i}"
            self.section(f"SERIES {i + 1}: {sm.label}")
            ckey = f"series_color_{i}"
            color_expr = None
            if bind and ckey in self._ctrl_names:
                color_expr = expr([CTRL, f'ctrl.effect({jstr(self._ctrl_names[ckey])})("Color");'])

            # area fill
            if sm.path is not None and (s.chart_type == AREA or sm.spec.fill_opacity > 0):
                self._emit_area(tag, sm, i, color_expr)

            # the line
            if sm.path is not None:
                self.w(f"var line{i} = buildLineLayer({jstr(sm.safe_name + '_LINE')}, "
                       f"{tag}_VERTICES, {tag}_IN, {tag}_OUT, {jcolor(sm.color)}, "
                       f"{fmt_num(sm.spec.stroke_width)}, false);")
                self.w(f'vprop(line{i}, "LineGroup", "Trim").property("End").expression = '
                       + expr([
                    CTRL, PROG,
                    f"var N = {sm.path.n};",
                    f"var arc = {fmt_list(sm.path.arc, lambda v: round(v, 5))};",
                    "var idx = (progress/100)*(N-1);",
                    "var i = Math.floor(Math.min(Math.max(idx,0), N-2));",
                    "var frac = idx - i;",
                    "(arc[i] + (arc[i+1]-arc[i])*frac) * 100;",
                ]) + ";")
                if bind:
                    self.w(f'vprop(line{i}, "LineGroup", "LineStroke")'
                           f'.property("Stroke Width").expression = ' + expr([
                        CTRL,
                        f"var w = {fmt_num(sm.spec.stroke_width)};",
                        f'w * {self.read("line_weight")} / 100;',
                    ]) + ";")
                    if color_expr:
                        self.w(f'vprop(line{i}, "LineGroup", "LineStroke")'
                               f'.property("Color").expression = {color_expr};')

            # dots
            if sm.dots:
                self._emit_dots(tag, sm, i, color_expr)

    def _emit_area(self, tag: str, sm: SeriesModel, i: int, color_expr: Optional[str]) -> None:
        s = self.s
        p = sm.path
        base = sm.baseline_pixel
        if sm.lower_points:
            # A stacked band closes along the top of the series beneath it
            # rather than along a flat baseline.
            low = list(reversed(sm.lower_points))
            verts = list(p.points) + low
            pad = [(0.0, 0.0)] * len(low)
        else:
            verts = list(p.points) + [(p.points[-1][0], base), (p.points[0][0], base)]
            pad = [(0.0, 0.0), (0.0, 0.0)]
        ins = list(p.in_tangents) + pad
        outs = list(p.out_tangents) + pad
        op = sm.spec.fill_opacity if sm.spec.fill_opacity > 0 else 28.0
        self.w(f"var area{i} = buildAreaLayer({jstr(sm.safe_name + '_AREA')}, "
               f"{fmt_pairs(verts, r2)}, {fmt_pairs(ins, r6)}, {fmt_pairs(outs, r6)}, "
               f"{jcolor(sm.color)}, {fmt_num(op)});")
        self.w("// Reveal the fill with a Linear Wipe locked to the line's leading edge.")
        self.w(f'var wipe{i} = area{i}.property("Effects").addProperty("ADBE Linear Wipe");')
        self.w(f'wipe{i}.property("Wipe Angle").setValue(-90);')
        self.w(f'wipe{i}.property("Feather").setValue(0);')
        self.w(f'wipe{i}.property("Transition Completion").expression = ' + expr([
            CTRL, PROG,
            f"var N = {p.n};",
            f"var px = {fmt_list(p.xs, r2)};",
            "var idx = (progress/100)*(N-1);",
            "var i = Math.floor(Math.min(Math.max(idx,0), N-2));",
            "var frac = idx - i;",
            "var x = px[i] + (px[i+1]-px[i])*frac;",
            f"var t = (x - {fmt_num(s.comp.plot_left)}) / "
            f"({fmt_num(s.comp.plot_right)} - {fmt_num(s.comp.plot_left)});",
            "100 - Math.min(Math.max(t, 0), 1) * 100;",
        ]) + ";")
        if color_expr:
            self.w(f'vprop(area{i}, "AreaGroup", "AreaFill")'
                   f'.property("Color").expression = {color_expr};')
        if "area_opacity" in self._ctrl_names:
            self.w(f'vprop(area{i}, "AreaGroup", "AreaFill").property("Opacity")'
                   f'.expression = ' + expr([
                       CTRL,
                       f"var base = {fmt_num(op)};",
                       f'base * {self.read("area_opacity")} / 100;',
                   ]) + ";")

    # -- runtime-assembled expressions ------------------------------------
    def _emit_expr_assign(self, target: str, lines, indent: int = 1) -> None:
        """Emit `target.expression = 'a\\n' + 'b\\n' + ...;`.

        A line may be a plain string (emitted as a literal) or a list of
        pieces where any piece prefixed with '~' is raw JS concatenated in.
        That is how per-layer values such as `revealAt` get baked into an
        expression built inside a JS loop, exactly as the reference scripts do.
        """
        self.w(f"{target}.expression =", indent)
        rows: List[str] = []
        for i, ln in enumerate(lines):
            last = (i == len(lines) - 1)
            pieces = list(ln) if isinstance(ln, (list, tuple)) else [ln]
            if isinstance(pieces[-1], str) and pieces[-1].startswith("~"):
                pieces.append("")
            parts: List[str] = []
            for k, pc in enumerate(pieces):
                is_last = (k == len(pieces) - 1)
                if isinstance(pc, str) and pc.startswith("~"):
                    parts.append(pc[1:])
                elif pc == "" and not is_last:
                    continue
                else:
                    parts.append(_sq(pc, newline=(is_last and not last)))
            rows.append(" + ".join(parts))
        for i, row in enumerate(rows):
            self.w(IND + row + (";" if i == len(rows) - 1 else " +"), indent)

    def _emit_dots(self, tag: str, sm: SeriesModel, si: int, color_expr: Optional[str]) -> None:
        m, s = self.m, self.s
        bind = s.style.bind_to_controls
        dots = sm.dots
        step = 1
        self.w("")
        if s.style.max_dot_layers > 0 and len(dots) > s.style.max_dot_layers:
            step = math.ceil(len(dots) / s.style.max_dot_layers)
            self.w(f"// {len(dots)} points exceeds the {s.style.max_dot_layers}-layer dot budget,")
            self.w(f"// so every {step}th point gets a dot. Raise 'Max dot layers' to draw them all.")

        colors = [tuple(d.color) for d in dots]
        uniq: List[RGB] = []
        for c in colors:
            if c not in uniq:
                uniq.append(c)
        need_table = len(uniq) > 1 or s.size.enabled

        # colour slot -> MASTER_CONTROLS colour control, where one exists
        slot_ctrl: Dict[int, str] = {}
        for le in m.legend:
            key = f"cat_color_{le.label}"
            if key in self._ctrl_names and tuple(le.color) in uniq:
                slot_ctrl[uniq.index(tuple(le.color))] = self._ctrl_names[key]

        if need_table:
            self.w(f"var {tag}_COLORS = [" + ", ".join(jcolor(c) for c in uniq) + "];")
            self.w(f"var {tag}_CIDX = " + fmt_list([uniq.index(c) for c in colors], int) + ";")
        col_ref = f"{tag}_COLORS[{tag}_CIDX[k]]" if need_table else jcolor(uniq[0])
        diam_ref = f"{tag}_DIAM[k]" if s.size.enabled else fmt_num(dots[0].diameter)

        self.w(f"for (var k = 0; k < {tag}_DOT_X.length; k += {step}) {{", 1)
        self.w(f"var dot = buildDot({jstr(sm.safe_name + '_DOT')} + \"_\" + k, "
               f"{diam_ref}, {col_ref});", 2)
        self.w('dot.property("Transform").property("Position")'
               f".setValue([{tag}_DOT_X[k], {tag}_DOT_Y[k]]);", 2)
        span = dots[0].reveal_span if dots else 0.0
        if s.style.reveal_from_zero:
            self.w(f"// Each point owns a slot of the timeline, so at Progress 0")
            self.w(f"// nothing is drawn and even the first point animates in.", 2)
            self.w(f"var revealAt = (k / {tag}_DOT_X.length) * 100;", 2)
        else:
            self.w(f"var revealAt = (k / ({tag}_DOT_X.length - 1)) * 100;", 2)
        self.w(f"var revealSpan = {fmt_num(round(span, 6))};", 2)

        # colour binding
        if bind and slot_ctrl:
            names = [slot_ctrl.get(i, "") for i in range(len(uniq))]
            self.w("var colorCtrl = [" + ", ".join(jstr(n) for n in names)
                   + f"][{tag}_CIDX[k]];", 2)
            self.w('if (colorCtrl !== "") {', 2)
            self._emit_expr_assign('vprop(dot, "Dot", "DotFill").property("Color")', [
                'var ctrl = thisComp.layer("MASTER_CONTROLS");',
                ['ctrl.effect("', "~colorCtrl", '")("Color");'],
            ], indent=3)
            self.w("}", 2)
        elif color_expr:
            self.w(f'vprop(dot, "Dot", "DotFill").property("Color").expression = '
                   f'{color_expr};', 2)

        # opacity reveal
        if bind:
            self._emit_expr_assign('dot.property("Transform").property("Opacity")', [
                'var ctrl = thisComp.layer("MASTER_CONTROLS");',
                f'var progress = ctrl.effect("{self._ctrl_names["progress"]}")("Slider");',
                f'var soft = ctrl.effect("{self._ctrl_names["softness"]}")("Slider");',
                f'var op = ctrl.effect("{self._ctrl_names["dot_opacity"]}")("Slider");',
                ["var at = ", "~revealAt", ";"],
                ["var span = ", "~revealSpan", ";"],
                "var lo = Math.max(0, at - soft);",
                "var hi = Math.max(lo + 0.001, at + span + soft * 0.33);",
                "linear(progress, lo, hi, 0, op);",
            ], indent=2)
            self.w('dot.property("Transform").property("Scale").expression = ' + expr([
                CTRL,
                f'var sc = ctrl.effect("{self._ctrl_names["dot_scale"]}")("Slider");',
                "[sc, sc];",
            ]) + ";", 2)
        else:
            self._emit_expr_assign('dot.property("Transform").property("Opacity")', [
                'var ctrl = thisComp.layer("MASTER_CONTROLS");',
                f'var progress = ctrl.effect("{self._ctrl_names["progress"]}")("Slider");',
                ["var at = ", "~revealAt", ";"],
                ["var span = ", "~revealSpan", ";"],
                f"var lo = Math.max(0, at - {fmt_num(s.style.dot_reveal_lead)});",
                f"var hi = Math.max(lo + 0.001, at + span + {fmt_num(s.style.dot_reveal_lag)});",
                f"linear(progress, lo, hi, 0, {fmt_num(s.style.dot_opacity)});",
            ], indent=2)
        self.w("}", 1)

    # -- playhead + tip --------------------------------------------------
    def _playhead_and_tip(self) -> None:
        m, s = self.m, self.s
        bind = s.style.bind_to_controls
        paths = [sm for sm in m.series if sm.path is not None]
        if not paths or s.chart_type == SCATTER:
            if not (s.style.show_tip_dot and paths):
                return
        lead = paths[0] if paths else None
        if lead is None:
            return
        p = lead.path

        self.section("PLAYHEAD + LEADING TIP DOT")
        self.w("var fadeExpr = " + expr([
            CTRL, PROG,
            "linear(progress, 0, 2, 0, 100) * (progress < 99.5 ? 1 : "
            "linear(progress, 99.5, 100, 1, 0));",
        ]) + ";")

        if s.style.show_playhead:
            self.w("")
            self.w("var playhead = buildPlayhead();")
            self.w('playhead.property("Transform").property("Position").expression = ' + expr([
                CTRL, PROG,
                f"var N = {p.n};",
                f"var px = {fmt_list(p.xs, r2)};",
                "var idx = (progress/100)*(N-1);",
                "var i = Math.floor(Math.min(Math.max(idx,0), N-2));",
                "var frac = idx - i;",
                "var x = px[i] + (px[i+1]-px[i])*frac;",
                "[x, (PLOT_T + PLOT_B) / 2];".replace("PLOT_T", fmt_num(s.comp.plot_top))
                                             .replace("PLOT_B", fmt_num(s.comp.plot_bottom)),
            ]) + ";")
            if "playhead_width" in self._ctrl_names:
                self.w('playhead.property("Transform").property("Scale").expression = ' + expr([
                    CTRL,
                    f'var k = {self.read("playhead_width")};',
                    "[k, 100];",
                ]) + ";")
            if bind:
                self.w('playhead.property("Transform").property("Opacity").expression = ' + expr([
                    CTRL, PROG,
                    f'var base = {self.read("playhead_opacity")}',
                    "base * linear(progress, 0, 2, 0, 1) * (progress < 99.5 ? 1 : "
                    "linear(progress, 99.5, 100, 1, 0));",
                ]) + ";")
            else:
                self.w('playhead.property("Transform").property("Opacity").expression = fadeExpr;')

        if s.style.show_tip_dot:
            self.w("")
            self.w(f"var tip = buildDot(\"TIP_DOT\", {fmt_num(s.style.tip_dot_size)}, "
                   f"{jcolor(lead.color)});")
            self.w('tip.property("Transform").property("Position").expression = ' + expr([
                CTRL, PROG,
                f"var N = {p.n};",
                f"var px = {fmt_list(p.xs, r2)};",
                f"var py = {fmt_list(p.ys, r2)};",
                "var idx = (progress/100)*(N-1);",
                "var i = Math.floor(Math.min(Math.max(idx,0), N-2));",
                "var frac = idx - i;",
                "[px[i] + (px[i+1]-px[i])*frac, py[i] + (py[i+1]-py[i])*frac];",
            ]) + ";")
            self.w('tip.property("Transform").property("Opacity").expression = fadeExpr;')
            if bind:
                self.w('tip.property("Transform").property("Scale").expression = ' + expr([
                    CTRL,
                    f'var d = {self.read("tip_size")}',
                    f"var base = {fmt_num(s.style.tip_dot_size)};",
                    "var k = base > 0 ? (d / base) * 100 : 100;",
                    "[k, k];",
                ]) + ";")

    # -- bars ------------------------------------------------------------
    def _bars(self) -> None:
        m, s = self.m, self.s
        bind = s.style.bind_to_controls
        horiz = s.chart_type == HBAR
        self.section("BARS")
        self.w("var BAR_X = " + fmt_list([b.x for b in m.bars], r2) + ";")
        self.w("var BAR_Y = " + fmt_list([b.y for b in m.bars], r2) + ";")
        self.w("var BAR_W = " + fmt_list([b.width for b in m.bars], r2) + ";")
        self.w("var BAR_H = " + fmt_list([b.height for b in m.bars], r2) + ";")
        self.w("var BAR_AT = " + fmt_list([b.reveal_at for b in m.bars], r2) + ";")
        self.w("var BAR_LABEL = [" + ", ".join(jstr(b.value_label or b.label)
                                               for b in m.bars) + "];")
        colors = [b.color for b in m.bars]
        uniq: List[RGB] = []
        for c in colors:
            if c not in uniq:
                uniq.append(c)
        self.w("var BAR_COLORS = [" + ", ".join(jcolor(c) for c in uniq) + "];")
        self.w("var BAR_CIDX = " + fmt_list([uniq.index(c) for c in colors], lambda v: int(v)) + ";")
        base = m.bars[0].base if m.bars else 0.0
        self.w(f"var BAR_BASE = {fmt_num(r2(base))};")
        self.w("")
        self.w("for (var b = 0; b < BAR_X.length; b++) {", 1)
        self.w('var bar = buildBar("BAR_" + b, BAR_W[b], BAR_H[b], BAR_COLORS[BAR_CIDX[b]]);', 2)
        if horiz:
            self.w('vprop(bar, "Bar", "BarRect").property("Position")'
                   '.setValue([BAR_W[b] / 2, 0]);', 2)
            self.w('bar.property("Transform").property("Anchor Point").setValue([0, 0]);', 2)
            self.w('bar.property("Transform").property("Position").setValue([BAR_BASE, BAR_Y[b] + BAR_H[b] / 2]);', 2)
            grow = "[g, 100];"
        else:
            self.w('vprop(bar, "Bar", "BarRect").property("Position")'
                   '.setValue([0, -BAR_H[b] / 2]);', 2)
            self.w('bar.property("Transform").property("Anchor Point").setValue([0, 0]);', 2)
            self.w('bar.property("Transform").property("Position").setValue([BAR_X[b], BAR_BASE]);', 2)
            grow = "[100, g];"
        soft_line = (f'var soft = ctrl.effect("{self._ctrl_names["softness"]}")("Slider");'
                     if bind else f"var soft = {fmt_num(s.style.dot_reveal_lead)};")
        bspan = m.bars[0].reveal_span if m.bars else 0.0
        self._emit_expr_assign('bar.property("Transform").property("Scale")', [
            'var ctrl = thisComp.layer("MASTER_CONTROLS");',
            f'var progress = ctrl.effect("{self._ctrl_names["progress"]}")("Slider");',
            soft_line,
            ["var at = ", "~BAR_AT[b]", ";"],
            f"var span = {fmt_num(round(bspan, 6))};",
            "var lo = Math.max(0, at - span - soft);",
            "var g = ease(progress, lo, Math.max(lo + 0.001, at), 0, 100);",
            grow,
        ], indent=2)

        if "bar_round" in self._ctrl_names:
            self.w('vprop(bar, "Bar", "BarRect").property("Roundness").expression = '
                   + expr([CTRL, f'{self.read("bar_round")};']) + ";", 2)
        if "bar_width" in self._ctrl_names:
            # BAR_W/BAR_H are script-scope arrays and an expression cannot see
            # them, so the two numbers are concatenated into the expression
            # text as the loop writes it.
            self._emit_expr_assign('vprop(bar, "Bar", "BarRect").property("Size")', [
                'var ctrl = thisComp.layer("MASTER_CONTROLS");',
                f'var k = ctrl.effect("{self._ctrl_names["bar_width"]}")("Slider") / 100;',
                ["var w = ", "~BAR_W[b]", ";"],
                ["var h = ", "~BAR_H[b]", ";"],
                ("[w, h * k];" if horiz else "[w * k, h];"),
            ], indent=2)

        self.w("")
        self.w("// value label riding the end of each bar", 2)
        if horiz:
            self.w('var vl = makeText(BAR_LABEL[b], 20, AXIS_COLOR, '
                   '[BAR_X[b] + BAR_W[b] + 16, BAR_Y[b] + BAR_H[b] / 2 + 7], "left");', 2)
        else:
            self.w('var vl = makeText(BAR_LABEL[b], 20, AXIS_COLOR, '
                   '[BAR_X[b], BAR_Y[b] - 16], "center");', 2)
        self._emit_expr_assign('vl.property("Transform").property("Opacity")', [
            'var ctrl = thisComp.layer("MASTER_CONTROLS");',
            f'var progress = ctrl.effect("{self._ctrl_names["progress"]}")("Slider");',
            ["var at = ", "~BAR_AT[b]", ";"],
            f"var span = {fmt_num(round(bspan, 6))};",
            "var lo = Math.max(0, at - span);",
            "linear(progress, lo, Math.max(lo + 0.001, at), 0, 100);",
        ], indent=2)
        self.w("}", 1)

        if s.chart_type == LOLLIPOP:
            self.w("")
            self.w("// lollipop heads, revealed with their stems")
            self.w("for (var q = 0; q < BAR_X.length; q++) {", 1)
            self.w(f'var head = buildDot("HEAD_" + q, {fmt_num(s.lollipop_dot)}, '
                   "BAR_COLORS[BAR_CIDX[q]]);", 2)
            self.w('head.property("Transform").property("Position")'
                   '.setValue([BAR_X[q], BAR_Y[q]]);', 2)
            self._emit_expr_assign('head.property("Transform").property("Scale")', [
                'var ctrl = thisComp.layer("MASTER_CONTROLS");',
                f'var progress = ctrl.effect("{self._ctrl_names["progress"]}")("Slider");',
                ["var at = ", "~BAR_AT[q]", ";"],
                f"var span = {fmt_num(round(bspan, 6))};",
                "var lo = Math.max(0, at - span);",
                "var g = ease(progress, lo, Math.max(lo + 0.001, at), 0, 100);",
                "[g, g];",
            ], indent=2)
            self.w("}", 1)

    # -- donut -----------------------------------------------------------
    def _donut(self) -> None:
        """Each wedge is one stroked ellipse trimmed to its own span.

        Trim Paths measures around the ellipse from twelve o'clock clockwise,
        which is exactly the coordinate a pie chart wants, so the sweep needs
        no path maths at all.

        The ring is described by an outer and an inner radius. A stroke of
        width (outer - inner) centred on a path of radius (outer + inner) / 2
        fills precisely that band, and when the inner radius is 0 the stroke
        reaches the centre, so a pie is the same layer setup as a donut with
        one slider moved. Both radii are bound to MASTER_CONTROLS, so the ring
        can be reshaped in After Effects without regenerating the script.
        """
        m, s = self.m, self.s
        self.section("DONUT SEGMENTS")
        self.w(f"var RING_CX = {fmt_num(r2(m.donut_cx))};")
        self.w(f"var RING_CY = {fmt_num(r2(m.donut_cy))};")
        self.w(f"var RING_OUTER = {fmt_num(r2(m.donut_r_outer))};")
        self.w(f"var RING_INNER = {fmt_num(r2(m.donut_r_inner))};")
        self.w("var RING_R = (RING_OUTER + RING_INNER) / 2;")
        self.w("var RING_W = RING_OUTER - RING_INNER;")
        self.w("var SEG_START = " + fmt_list([g.start * 100 for g in m.segments], r2) + ";")
        self.w("var SEG_END = " + fmt_list([g.end * 100 for g in m.segments], r2) + ";")
        self.w("var SEG_AT = " + fmt_list([g.reveal_at for g in m.segments], r2) + ";")
        self.w("var SEG_COLORS = [" + ", ".join(jcolor(g.color) for g in m.segments) + "];")
        self.w("var SEG_CTRL = [" + ", ".join(
            jstr(self._ctrl_names.get(f"cat_color_{g.label}", "")) for g in m.segments) + "];")
        span = m.segments[0].reveal_span if m.segments else 0.0
        bound = "ring_outer" in self._ctrl_names
        # Size and stroke width both need the same two numbers, so the
        # prologue that reads the sliders is written once and shared.
        geom = [
            CTRL,
            f"var ro = {fmt_num(r2(m.donut_r_outer))} * {self.read('ring_outer')} / 100;",
            f"var ri = ro * {self.read('ring_inner')} / 100;",
        ] if bound else []
        self.w("")
        self.w("for (var g = 0; g < SEG_START.length; g++) {", 1)
        self.w('var seg = buildRing("SEG_" + g, RING_R, RING_W, SEG_COLORS[g]);', 2)
        self.w('seg.property("Transform").property("Position")'
               ".setValue([RING_CX, RING_CY]);", 2)
        if bound:
            self.w('vprop(seg, "RingGroup", "RingShape").property("Size")'
                   ".expression = " + expr(geom + [
                       "var d = ro + ri;",
                       "[d, d];",
                   ]) + ";", 2)
            self.w('vprop(seg, "RingGroup", "RingStroke").property("Stroke Width")'
                   ".expression = " + expr(geom + [
                       "Math.max(0, ro - ri);",
                   ]) + ";", 2)
            self.w("if (SEG_CTRL[g] !== \"\") {", 2)
            self._emit_expr_assign(
                'vprop(seg, "RingGroup", "RingStroke").property("Color")', [
                    CTRL,
                    ['ctrl.effect("', "~SEG_CTRL[g]", '")("Color");'],
                ], indent=3)
            self.w("}", 2)
        gap = (f'var gap = {self.read("ring_gap")} * 0.1;' if "ring_gap" in self._ctrl_names
               else "var gap = 0;")
        self._emit_expr_assign('vprop(seg, "RingGroup", "RingTrim").property("Start")', [
            'var ctrl = thisComp.layer("MASTER_CONTROLS");',
            gap,
            ["var a = ", "~SEG_START[g]", ";"],
            "a + gap;",
        ], indent=2)
        self._emit_expr_assign('vprop(seg, "RingGroup", "RingTrim").property("End")', [
            'var ctrl = thisComp.layer("MASTER_CONTROLS");',
            f'var progress = ctrl.effect("{self._ctrl_names["progress"]}")("Slider");',
            gap,
            ["var a = ", "~SEG_START[g]", ";"],
            ["var b = ", "~SEG_END[g]", ";"],
            ["var at = ", "~SEG_AT[g]", ";"],
            f"var span = {fmt_num(round(span, 6))};",
            "var hi = Math.max(at + span, at + 0.001);",
            "a + gap + ease(progress, at, hi, 0, Math.max(0, b - a - gap));",
        ], indent=2)
        self.w("}", 1)

        if s.donut_show_labels:
            self._donut_labels()

    def _donut_labels(self) -> None:
        """Slice captions. Text and anchor both come straight off the model,
        so the script cannot disagree with the previewer about either."""
        m, s = self.m, self.s
        shown = [g for g in m.segments if g.show_label]
        if not shown:
            return
        self.w("")
        self.w("// slice labels, placed at each wedge midpoint")
        span = m.segments[0].reveal_span if m.segments else 0.0
        for i, g in enumerate(shown):
            self.w(f"var slab{i} = makeText({jstr(g.text)}, {fmt_num(s.style.legend_size)}, "
                   f"AXIS_COLOR, [{fmt_num(r2(g.label_x))}, {fmt_num(r2(g.label_y))}], "
                   f"{jstr(g.label_just)});")
            self.w(f'slab{i}.property("Transform").property("Opacity").expression = ' + expr([
                CTRL, PROG,
                f"var at = {fmt_num(g.reveal_at)};",
                f"var span = {fmt_num(round(span, 6))};",
                "linear(progress, at, Math.max(at + span, at + 0.001), 0, 100);",
            ]) + ";")

    # -- readout ---------------------------------------------------------
    def _readout(self) -> None:
        m, s = self.m, self.s
        if not m.readout_values:
            return
        r = s.readout
        self.section("LIVE READOUT")
        pos = {"top_right": "[PLOT_R, 100]", "top_left": "[PLOT_L, 100]",
               "bottom_right": "[PLOT_R, PLOT_B + 130]",
               "bottom_left": "[PLOT_L, PLOT_B + 130]"}.get(r.corner, "[PLOT_R, 100]")
        just = "right" if "right" in r.corner else "left"
        self.w(f"var readout = makeText(\"\", {fmt_num(r.size)}, {jcolor(r.color)}, {pos}, {jstr(just)});")
        self.w('readout.property("Source Text").expression = ' + expr([
            CTRL, PROG,
            f"var N = {len(m.readout_values)};",
            "var vals = " + fmt_list(m.readout_values, lambda v: round(v, 4)) + ";",
            "var idx = (progress/100)*(N-1);",
            "var i = Math.floor(Math.min(Math.max(idx,0), N-2));",
            "var frac = idx - i;",
            "var v = vals[i] + (vals[i+1]-vals[i])*frac;",
            (f"{jstr(r.prefix)} + Math.floor(v) + {jstr(r.suffix)};" if int(r.decimals) == 0
             else f"{jstr(r.prefix)} + v.toFixed({int(r.decimals)}) + {jstr(r.suffix)};"),
        ]) + ";")

    # -- finish ----------------------------------------------------------
    def _finish(self) -> None:
        m = self.m
        self.w("")
        self.w('alert("Built \\"" + COMP_NAME + "\\" (' + str(m.n_points) +
               ' points). Scrub Progress on MASTER_CONTROLS, or play the comp.");')


def generate_jsx(model: RenderModel, spec: Optional[ChartSpec] = None) -> str:
    return JSXGenerator(model, spec).generate()

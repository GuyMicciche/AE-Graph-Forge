"""Headless checks for the donut / pie pipeline.

Runs the same build_model -> generate_jsx path the app uses, so a regression
in the geometry, the label placement or the preset round-trip shows up here
rather than in After Effects. Run with: python tools/check_donut.py
"""

from __future__ import annotations

import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aegraphforge.core.build import build_model
from aegraphforge.core.dataset import Dataset
from aegraphforge.core.jsxgen import generate_jsx
from aegraphforge.core.spec import (ChartSpec, DONUT, D_ALL, D_NAME, D_NAME_PCT,
                                    D_NAME_VAL, D_PCT, D_VALUE, SORT_DATA,
                                    SORT_LABEL, SORT_VALUE_ASC, SORT_VALUE_DESC,
                                    SeriesSpec)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(HERE, "examples", "data.csv")

fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        fails.append(name)


def donut_spec(**kw) -> ChartSpec:
    s = ChartSpec()
    s.chart_type = DONUT
    s.x_column = "Launch_Date"
    s.group_column = "Orbit_Type"
    s.aggregation = "count"
    s.series = [SeriesSpec(column="Altitude_km", label="Altitude_km")]
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def main() -> int:
    ds = Dataset.from_csv(CSV)
    print(f"loaded {ds.n_rows} rows, {len(ds.columns)} columns\n")

    # -- grouping by a category column ------------------------------------
    print("grouping")
    m = build_model(ds, donut_spec())
    check("builds", m.ok, m.error)
    check("one slice per orbit type", len(m.segments) == 3,
          f"got {[g.label for g in m.segments]}")
    check("count aggregation totals the rows",
          abs(sum(g.value for g in m.segments) - ds.n_rows) < 1e-6,
          f"{sum(g.value for g in m.segments)} vs {ds.n_rows}")
    check("shares sum to 1",
          abs(sum(g.fraction for g in m.segments) - 1.0) < 1e-9)
    check("no Other slice when everything fits",
          not any(g.label == "Other" for g in m.segments))

    # -- ring geometry -----------------------------------------------------
    print("\ngeometry")
    s = donut_spec(donut_radius_frac=0.8, donut_inner_frac=0.5)
    m = build_model(ds, s)
    half = min(s.comp.plot_right - s.comp.plot_left,
               s.comp.plot_bottom - s.comp.plot_top) / 2.0
    check("outer radius follows the fraction",
          abs(m.donut_r_outer - half * 0.8) < 1e-6)
    check("inner radius is a share of the outer",
          abs(m.donut_r_inner - m.donut_r_outer * 0.5) < 1e-6)
    check("stroke spans exactly the band",
          abs((m.donut_radius - m.donut_thickness / 2) - m.donut_r_inner) < 1e-6
          and abs((m.donut_radius + m.donut_thickness / 2) - m.donut_r_outer) < 1e-6)

    pie = build_model(ds, donut_spec(donut_inner_frac=0.0))
    check("inner 0 closes the hole", pie.donut_r_inner == 0.0)
    check("pie stroke reaches the centre",
          abs(pie.donut_radius * 2 - pie.donut_thickness) < 1e-9,
          f"r={pie.donut_radius} w={pie.donut_thickness}")
    check("pie outer edge matches the donut's",
          abs(pie.donut_r_outer - build_model(ds, donut_spec()).donut_r_outer) < 1e-6)

    # -- slice gaps --------------------------------------------------------
    print("\ngaps")
    g0 = build_model(ds, donut_spec(donut_gap_deg=0.0))
    g6 = build_model(ds, donut_spec(donut_gap_deg=6.0))
    check("no gap leaves wedges touching",
          all(abs(g0.segments[i].end - g0.segments[i + 1].start) < 1e-9
              for i in range(len(g0.segments) - 1)))
    check("gap is cut out of each wedge",
          all(abs((g6.segments[i + 1].start - g6.segments[i].end) - 6.0 / 360.0) < 1e-9
              for i in range(len(g6.segments) - 1)))
    check("gap never inverts a wedge",
          all(g.end >= g.start for g in
              build_model(ds, donut_spec(donut_gap_deg=20.0)).segments))

    # -- labels ------------------------------------------------------------
    print("\nlabels")
    seen = {}
    for mode in (D_NAME, D_PCT, D_VALUE, D_NAME_PCT, D_NAME_VAL, D_ALL):
        mm = build_model(ds, donut_spec(donut_label_mode=mode))
        seen[mode] = mm.segments[0].text
    check("every label mode reads differently",
          len(set(seen.values())) == len(seen), json.dumps(seen))
    check("name only is just the name", seen[D_NAME] == "LEO" or "%" not in seen[D_NAME])
    check("percent only carries no name", "%" in seen[D_PCT] and " " not in seen[D_PCT])

    out = build_model(ds, donut_spec(donut_label_place="outside"))
    ins = build_model(ds, donut_spec(donut_label_place="inside"))
    r_out = math.hypot(out.segments[0].label_x - out.donut_cx,
                       out.segments[0].label_y - 8 - out.donut_cy)
    r_in = math.hypot(ins.segments[0].label_x - ins.donut_cx,
                      ins.segments[0].label_y - 8 - ins.donut_cy)
    check("outside labels clear the ring", r_out > out.donut_r_outer)
    check("inside labels sit on the band",
          ins.donut_r_inner < r_in < ins.donut_r_outer, f"r={r_in:.1f}")
    check("inside labels are centred", ins.segments[0].label_just == "center")

    hid = build_model(ds, donut_spec(group_column="Launch_Date", max_bars=20,
                                     donut_label_min_pct=4.0))
    check("small slices lose their label",
          any(not g.show_label for g in hid.segments)
          and all(g.show_label for g in hid.segments if g.fraction >= 0.04))

    # -- ordering and Other ------------------------------------------------
    print("\nordering")
    for how, ok in (
        (SORT_VALUE_DESC, lambda v: v == sorted(v, reverse=True)),
        (SORT_VALUE_ASC, lambda v: v == sorted(v)),
    ):
        mm = build_model(ds, donut_spec(slice_sort=how))
        check(f"{how} orders by value", ok([g.value for g in mm.segments]))
    lab = build_model(ds, donut_spec(slice_sort=SORT_LABEL))
    check("label sort is alphabetical",
          [g.label for g in lab.segments] == sorted(g.label for g in lab.segments))
    dat = build_model(ds, donut_spec(slice_sort=SORT_DATA))
    check("data order is first-seen", [g.label for g in dat.segments][0] == "LEO",
          str([g.label for g in dat.segments]))

    trim = build_model(ds, donut_spec(group_column="Launch_Date", max_bars=5))
    check("top-N merges the tail into Other",
          trim.segments[-1].label == "Other" and len(trim.segments) == 6,
          str([g.label for g in trim.segments]))
    check("Other keeps the total whole",
          abs(sum(g.fraction for g in trim.segments) - 1.0) < 1e-9)
    check("warns when the x column is not groupable",
          any("Group by" in w for w in
              build_model(ds, donut_spec(group_column="")).warnings))

    # -- generated script --------------------------------------------------
    print("\njsx")
    js = generate_jsx(build_model(ds, donut_spec()))
    check("emits both radii", "var RING_OUTER" in js and "var RING_INNER" in js)
    check("derives the stroke from the pair",
          "var RING_R = (RING_OUTER + RING_INNER) / 2;" in js
          and "var RING_W = RING_OUTER - RING_INNER;" in js)
    check("no stale thickness control", "Ring Thickness" not in js)
    check("exposes the radius sliders",
          '"Ring Outer"' in js and '"Ring Inner"' in js)
    check("binds a colour control per slice",
          all(f'"{g.label} Color"' in js for g in build_model(ds, donut_spec()).segments))
    check("balanced braces", js.count("{") == js.count("}"),
          f'{js.count("{")} vs {js.count("}")}')
    check("balanced parens", js.count("(") == js.count(")"))
    check("no python leaked in", "None" not in js and "True" not in js)

    pie_js = generate_jsx(build_model(ds, donut_spec(donut_inner_frac=0.0)))
    check("pie script sets inner to 0", "var RING_INNER = 0;" in pie_js)
    m_inner = re.search(r'addSlider\(controls, "Ring Inner", ([\d.]+)\)', pie_js)
    check("pie inner slider starts at 0",
          m_inner is not None and float(m_inner.group(1)) == 0.0,
          m_inner.group(1) if m_inner else "missing")

    labels_js = generate_jsx(build_model(ds, donut_spec(donut_label_mode=D_ALL)))
    seg0 = build_model(ds, donut_spec(donut_label_mode=D_ALL)).segments[0]
    check("script draws the model's caption verbatim", seg0.text in labels_js)

    # -- preset round-trip --------------------------------------------------
    print("\npresets")
    s = donut_spec(donut_radius_frac=0.66, donut_inner_frac=0.3,
                   donut_gap_deg=2.5, donut_label_mode=D_NAME_VAL,
                   donut_label_place="inside", slice_sort=SORT_LABEL)
    back = ChartSpec.from_json(s.to_json())
    check("new fields survive a save/load",
          (back.donut_radius_frac, back.donut_inner_frac, back.donut_gap_deg,
           back.donut_label_mode, back.donut_label_place, back.slice_sort)
          == (0.66, 0.3, 2.5, D_NAME_VAL, "inside", SORT_LABEL))

    legacy = {"chart_type": "donut", "donut_radius_frac": 0.78,
              "donut_thickness_frac": 0.22, "donut_label_mode": "percent"}
    old = ChartSpec.from_dict(legacy)
    check("legacy thickness converts to outer/inner",
          abs(old.donut_radius_frac - 0.78 * 1.22) < 1e-9
          and abs(old.donut_inner_frac - 0.78 / 1.22) < 1e-9,
          f"{old.donut_radius_frac} / {old.donut_inner_frac}")
    check("legacy label mode is remapped", old.donut_label_mode == D_NAME_PCT)

    pdir = os.path.join(HERE, "presets")
    for fn in sorted(os.listdir(pdir)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(pdir, fn)) as fh:
            sp = ChartSpec.from_dict(json.load(fh))
        mm = build_model(ds, sp)
        ok = mm.ok and bool(generate_jsx(mm))
        check(f"preset {fn} still builds", ok, mm.error)

    # -- other chart types still work --------------------------------------
    print("\nregression")
    for ct in ("line", "area", "scatter", "bar", "hbar", "lollipop",
               "stacked_bar", "grouped_bar", "step_line", "connected_scatter"):
        sp = ChartSpec()
        sp.chart_type = ct
        sp.x_column = "Launch_Date"
        sp.group_column = "Orbit_Type" if ct in ("bar", "hbar", "lollipop") else ""
        sp.series = [SeriesSpec(column="Altitude_km", label="Altitude_km"),
                     SeriesSpec(column="Latency_ms", label="Latency_ms")]
        mm = build_model(ds, sp)
        check(f"{ct} builds and generates", mm.ok and bool(generate_jsx(mm)), mm.error)

    print()
    if fails:
        print(f"{len(fails)} FAILED: {', '.join(fails)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

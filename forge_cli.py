#!/usr/bin/env python3
"""
forge_cli.py -- build a chart script without opening the GUI.

Useful for batching a folder of CSVs through one saved preset, or wiring the
generator into a render pipeline.

    # inspect a CSV
    python forge_cli.py inspect data.csv

    # generate using a preset saved from the app
    python forge_cli.py build data.csv --preset chart_preset.json -o chart.jsx

    # generate straight from flags, no preset
    python forge_cli.py build data.csv -o chart.jsx \\
        --type connected_scatter --x Latency_ms --y Bandwidth_Mbps \\
        --sort Launch_Date --color-by Orbit_Type --size-by Altitude_km \\
        --title "ORBITAL ALTITUDE" --comp SAT_Chart
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aegraphforge.core.build import build_model
from aegraphforge.core.dataset import CATEGORY, Dataset
from aegraphforge.core.jsxgen import generate_jsx
from aegraphforge.core.spec import (AGGREGATIONS, CHART_TYPES, CategorySpec,
                                    ChartSpec, DONUT_LABEL_MODES, ReadoutSpec,
                                    SLICE_SORTS, SeriesSpec, SizeSpec,
                                    TRANSFORMS, palette_color)


def cmd_inspect(args) -> int:
    ds = Dataset.from_csv(args.csv)
    print(f"{ds.path}\n{ds.n_rows} rows, {len(ds.columns)} columns\n")
    width = max(len(c.name) for c in ds.columns)
    for c in ds.columns:
        print(f"  {c.name:<{width}}  {c.kind:<9}  {c.summary()}")
    return 0


def cmd_build(args) -> int:
    ds = Dataset.from_csv(args.csv)

    if args.preset:
        with open(args.preset, "r", encoding="utf-8") as fh:
            spec = ChartSpec.from_json(fh.read())
    else:
        spec = ChartSpec()

    if args.type:
        spec.chart_type = args.type
    if args.x:
        spec.x_column = args.x
    if args.sort:
        spec.sort_column = args.sort
    # grouping, shared by every bar type, the lollipop and the donut
    if args.group_by:
        spec.group_column = args.group_by
    if args.agg:
        spec.aggregation = args.agg
    if args.order:
        spec.slice_sort = args.order
    if args.max_groups is not None:
        spec.max_bars = args.max_groups
    # donut / pie ring shape. Inner radius 0 gives a solid pie.
    if args.outer_radius is not None:
        spec.donut_radius_frac = args.outer_radius / 100.0
    if args.inner_radius is not None:
        spec.donut_inner_frac = args.inner_radius / 100.0
    if args.slice_gap is not None:
        spec.donut_gap_deg = args.slice_gap
    if args.slice_labels:
        spec.donut_label_mode = args.slice_labels
    if args.no_slice_labels:
        spec.donut_show_labels = False
    if args.y:
        spec.series = []
        for i, name in enumerate(args.y):
            col, _, transform = name.partition(":")
            spec.series.append(SeriesSpec(
                column=col, label=col, color=palette_color(i),
                transform=transform or "none",
                axis="right" if (args.right and col in args.right) else "left"))
    if args.color_by:
        col = ds.col(args.color_by)
        levels = col.categories if (col and col.kind == CATEGORY) else []
        spec.category = CategorySpec(
            column=args.color_by, enabled=True,
            colors={lev: palette_color(i + 1) for i, lev in enumerate(levels)})
    if args.size_by:
        spec.size = SizeSpec(column=args.size_by, enabled=True)
    if args.readout:
        spec.readout = ReadoutSpec(enabled=True, column=args.readout,
                                   prefix=args.readout_prefix or "")
    if args.title:
        spec.style.title = args.title
    if args.subtitle:
        spec.style.subtitle = args.subtitle
    if args.comp:
        spec.comp.name = args.comp
    if args.width:
        spec.comp.width = args.width
    if args.height:
        spec.comp.height = args.height
    if args.duration:
        spec.comp.duration = args.duration

    if not spec.x_column:
        plott = ds.plottable_names()
        spec.x_column = plott[0] if plott else ds.names[0]
    if not spec.series:
        nums = [n for n in ds.numeric_names() if n != spec.x_column]
        if not nums:
            print("error: no numeric column available for Y", file=sys.stderr)
            return 2
        spec.series = [SeriesSpec(column=nums[0], label=nums[0], color=palette_color(0))]
    if not spec.sort_column:
        spec.sort_column = spec.x_column

    model = build_model(ds, spec)
    if not model.ok:
        print(f"error: {model.error}", file=sys.stderr)
        return 1
    for w in model.warnings:
        print(f"warning: {w}", file=sys.stderr)

    js = generate_jsx(model)
    out = args.output or (spec.comp.name + ".jsx")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(js)
    print(f"wrote {out}  ({model.n_points} points, {len(js):,} bytes)")

    if args.save_preset:
        with open(args.save_preset, "w", encoding="utf-8") as fh:
            fh.write(spec.to_json())
        print(f"wrote {args.save_preset}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="forge_cli", description="Build After Effects chart scripts from CSV.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("inspect", help="show detected column types")
    pi.add_argument("csv")
    pi.set_defaults(func=cmd_inspect)

    pb = sub.add_parser("build", help="generate a .jsx")
    pb.add_argument("csv")
    pb.add_argument("-o", "--output")
    pb.add_argument("--preset", help="JSON preset saved from the app")
    pb.add_argument("--save-preset", help="write the resolved spec back out")
    pb.add_argument("--type", choices=[k for k, _ in CHART_TYPES])
    pb.add_argument("--x")
    pb.add_argument("--y", nargs="+",
                    help="one or more Y columns, optionally COLUMN:transform "
                         f"({', '.join(k for k, _ in TRANSFORMS)})")
    pb.add_argument("--right", nargs="+", help="Y columns to place on the right axis")
    pb.add_argument("--sort", help="column defining the reveal order")
    pb.add_argument("--group-by",
                    help="column whose values become the bars or slices; rows "
                         "sharing a value are combined with --agg")
    pb.add_argument("--agg", choices=[k for k, _ in AGGREGATIONS],
                    help="how rows in a group are combined (default sum). "
                         "'count' counts rows and ignores the value column")
    pb.add_argument("--order", choices=[k for k, _ in SLICE_SORTS],
                    help="display order for the groups (default value_desc)")
    pb.add_argument("--max-groups", type=int,
                    help="cap on groups drawn; the rest merge into Other on a "
                         "donut. 0 for no cap")
    pb.add_argument("--outer-radius", type=float, metavar="PCT",
                    help="donut outer radius, %% of half the shorter plot side")
    pb.add_argument("--inner-radius", type=float, metavar="PCT",
                    help="donut inner radius, %% of the outer. 0 for a solid pie")
    pb.add_argument("--slice-gap", type=float, metavar="DEG",
                    help="gap cut between neighbouring slices, in degrees")
    pb.add_argument("--slice-labels", choices=[k for k, _ in DONUT_LABEL_MODES],
                    help="what each slice label says")
    pb.add_argument("--no-slice-labels", action="store_true",
                    help="draw the ring without any slice labels")
    pb.add_argument("--color-by")
    pb.add_argument("--size-by")
    pb.add_argument("--readout")
    pb.add_argument("--readout-prefix")
    pb.add_argument("--title")
    pb.add_argument("--subtitle")
    pb.add_argument("--comp")
    pb.add_argument("--width", type=int)
    pb.add_argument("--height", type=int)
    pb.add_argument("--duration", type=float)
    pb.set_defaults(func=cmd_build)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

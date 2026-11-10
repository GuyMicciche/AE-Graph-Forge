# AE Graph Forge

Turn a CSV into an animated After Effects data chart driven by a single
Progress slider.

Point it at a spreadsheet, map columns to axes and encodings, watch a live
preview that is pixel-identical to what After Effects will build, then export a
`.jsx` you run from `File > Scripts > Run Script File...`. The script builds the
whole composition: comp, background, gridlines, labels, titles, legend, the
smoothed path, the dots, the playhead, and a `MASTER_CONTROLS` null that drives
every look parameter through expressions.

Written to match the style and geometry of the hand-authored `SAT_*` scripts,
so generated output drops into an existing project without looking foreign.

---

## Install and run

Requires **Python 3.9+** and **PySide6**. Nothing else.

```bash
pip install PySide6
python run.py
```

Open a CSV from the Data tab, or pass one on the command line:

```bash
python run.py data.csv
```

### Optional: validate output before it touches After Effects

If you have Node installed, the mock host will execute a generated script
against a stubbed AE object model and evaluate every expression it installs
across a full 0-100% Progress sweep:

```bash
node tools/ae_mock_check.js chart.jsx
```

```
PASS chart.jsx   357 expressions, 17 controls [Progress, Line Weight, Dot Scale, ...]
```

This catches things a plain syntax check cannot, such as an expression
referencing a variable that only exists in the build script's scope, or a
control name that does not match what was actually created.

---

## Workflow

1. **Data** tab. Load the CSV. Each column is typed automatically as numeric,
   date, category, or text. Check the inferred types here before mapping.

   Files can also be **dropped anywhere on the window**, or passed on the
   command line. Drop a `.csv`, `.tsv` or `.txt` to load data, a `.json` to
   apply a saved preset, or both at once to load the data and map it in one
   go. Dropping a file whose columns match the one already open keeps your
   current chart rather than auto-configuring a new one, so refreshing a
   dataset in place does not cost you the mapping.
2. **Mapping** tab. Choose the chart type, the X column, one or more Y series,
   and the sort column that defines reveal order. Optionally set a category
   column (drives colour), a size column (drives dot area), and a readout
   column (drives the live numeric display).
3. **Axes** tab. Min, max, and tick step are auto-populated from the data and
   pre-filled into the manual fields, so you can nudge a bound without typing
   the whole range. Linear, log, and sqrt scales; per-axis decimals, thousands
   separators, title size, unit, and unit size.

   **Shorten labels** divides tick text by a power of ten so a crowded axis
   reads cleanly: 4,500,000 becomes `4.5M`, 40,000 becomes `40K`. Auto picks
   the magnitude from the data, or force thousands, millions, or billions. The
   K/M/B suffix is optional, so you can drop it and put "millions" in the unit
   field instead. This is cosmetic only. Plotted geometry, axis ranges, and
   the live readout all keep working in the raw units.
4. **Style** tab. Colours, fonts, sizes, legend, gridlines, playhead, tip dot.
5. **Comp & Animation** tab. Comp name, resolution, frame rate, duration, plot
   rectangle, and the start and end times of the Progress keyframes.
6. Scrub the preview slider, or hit **Play** to watch it back at the comp
   frame rate. Playback maps time to Progress using the same keyframe times
   the generated script writes, so what you see is the timing you will get.
   Then **Export JSX**.

Presets save and load as JSON, so a chart definition is reusable across
datasets with the same column names.

---

## Chart types

Sixteen types, including continuous, grouped, distribution and matrix charts. The first five plot a value against a
continuous X; the rest aggregate rows into groups first.

| Type | Notes |
|---|---|
| `histogram` | Equal-width bins with count, probability or density heights. |
| `box_plot` | Grouped quartiles, median, 1.5 x IQR whiskers and optional outliers. |
| `heatmap` | Aggregate a numeric value across row/column categories; missing cells stay blank. |
| `candlestick` | Explicit Open, High, Low and Close mappings; up/down colours, wicks and doji bodies. Invalid OHLC rows are skipped with a warning. |
| `line` | One or many series. Any series can be sent to a right-hand axis. |
| `step_line` | Right-angled steps. The leading edge still crosses each data point at the same Progress a straight line would. |
| `area` | Line plus a fill revealed by a Linear Wipe locked to the leading edge. |
| `stacked_area` | Series accumulate. Each band closes on the one beneath rather than on a flat baseline, and the Y axis covers the stacked totals. |
| `connected_scatter` | Dots joined in sort order. Size and colour encodings apply. |
| `scatter` | Dots only, no path. |
| `bar` | Vertical. Groups and aggregates by a category column. |
| `hbar` | Horizontal. Same aggregation, value labels ride the bar ends. |
| `grouped_bar` | One sub-bar per series, side by side inside each slot. |
| `stacked_bar` | One sub-bar per series, accumulating upward. The total labels the top. |
| `lollipop` | Thin stem with a head at the value. Reads better than a bar when the bars would all be nearly full width. |
| `donut` | Wedges sized by share of total. Small slices past the cap merge into an Other slice. Inner radius 0 makes it a pie. |

The donut is worth a note: each wedge is a single stroked ellipse trimmed to
its own span, so the whole sweep animates on Trim Paths with no arc geometry
at all.

The ring is specified the way you look at it, as an **outer radius** and an
**inner radius**. The stroke the renderer actually draws falls out of the
pair: width `outer - inner`, centred on a path of radius `(outer + inner) / 2`.
That band is exactly the ring, and at an inner radius of 0 the stroke reaches
the centre, so a pie is a donut with one slider moved rather than a separate
code path. Both radii are bound to MASTER_CONTROLS, so the shape can be
reworked in After Effects without regenerating.

Slices can also carry a gap between them, measured in degrees and capped so it
can never invert the smallest wedge. Labels can read outside the ring or sit
inside the band, in any of six name/value/percent combinations, and a minimum
share threshold suppresses the labels on a long tail of thin slices.

### Grouping

Every bar type, the lollipop and the donut aggregate rows into groups before
anything is drawn. **Group by** picks the column whose values become the bars
or slices, **Aggregate** says how rows sharing a value are combined, and
**Order** sets the display order. The cap on group count always keeps the
largest groups whatever order they are shown in; on a donut the remainder
merges into an Other slice.

For a share-of-fleet chart, group by a category column and aggregate with
`count`: `Orbit_Type` with `count` gives one wedge per orbit carrying its share
of the satellites, rather than one wedge per row.

Each group gets its own colour swatch in the Mapping tab. The list is taken
from the chart that was just built, so it matches what is on screen exactly,
including the merged Other slice, and every swatch becomes a Color control on
MASTER_CONTROLS.

**Series transforms:** none, cumulative sum, cumulative max, rolling mean,
rolling sum, index to 100.

**Aggregations:** sum, mean, median, count, min, max.

**Slice / bar order:** largest first, smallest first, data order, label A-Z.

---

## The MASTER_CONTROLS rig

The reference scripts expose a single Progress slider. This generator keeps
that as the animation driver but adds art direction on top, so the look stays
adjustable after the build without regenerating anything.

Controls are added only where they apply, so a donut does not get a Line
Weight slider. Across all chart types the rig can carry:

- **Progress** the master driver, keyframed 0 to 100
- **Line Weight**, **Dot Scale**, **Dot Opacity**, **Tip Size**
- **Reveal Softness** how far ahead of the playhead points fade in
- **Grid Opacity**, **Grid Width**
- **Labels Opacity**, **Title Opacity**, **Legend Opacity**, **Readout Opacity**
- **Playhead Opacity**, **Playhead Width**
- **Area Opacity** on area and stacked area charts
- **Bar Width**, **Bar Roundness** on the bar family
- **Ring Outer**, **Ring Inner**, **Ring Gap** on donuts. Ring Outer is a
  percentage of the built radius and Ring Inner a percentage of the outer, so
  dragging Ring Inner to 0 collapses a donut into a pie live
- one **Color** control per series
- one **Color** control per category level or donut slice

That is up to twenty controls on one null.

Every layer reads from it by expression. Change the LEO colour on the null and
every LEO dot, its legend swatch, and any line bound to it all follow.

Turn this off with **Bind layers to MASTER_CONTROLS** in the Style tab if you
want a lighter comp with baked values and only Progress driving the reveal.

---

## Fonts

The Style tab has a font picker plus an optional exact PostScript name.

After Effects matches fonts by PostScript name, not by the family name the OS
shows you, and the two often differ. Picking a family sends it through and the
generated `setFont()` tries the usual bold spellings before falling back to
Arial:

```
Futura -> Futura-Bold -> Futura-BoldMT -> "Futura,Bold" -> Arial-BoldMT -> ...
```

If a font still refuses to apply, put its exact PostScript name in the second
field and it goes to the front of that list. In After Effects you can read the
correct name from the Character panel tooltip, or from
`app.fonts.allFonts[i].postScriptName` in the ExtendScript console.

The preview uses the same setting, trimming the weight suffix because Qt
matches on family name where After Effects matches on PostScript name.

---

## Reveal timing

**Start from an empty frame** (Comp & Animation tab, on by default) divides the
timeline into N slots for N points. Point `i` reveals across
`[i/N, (i+1)/N]` of Progress, so Progress 0 is a genuinely empty frame and even
the first point animates in. The last point finishes exactly at Progress 100.

Turn it off to match the original hand-written scripts, where point `i` sits on
`i/(N-1)` and the first point is already fully drawn at Progress 0.

**Reveal lead** and **lag** widen that window on either side and are additive,
so leaving both at 0 still gives a clean fade-in rather than a pop. Lead is
clamped so it can never pull the first point back before Progress 0.

Bars work the same way: bar `i` finishes growing at `(i+1)/N` and starts one
slot earlier.

---

## Geometry

The path is a uniform Catmull-Rom spline expressed as After Effects
vertex-relative Bézier offsets:

```
out_tangent[i] = (P[i+1] - P[i-1]) / 6
in_tangent[i]  = -out_tangent[i]
endpoints      = [0, 0]
```

This was reverse-engineered from the reference scripts and reproduces their
`IN_TANGENTS` and `OUT_TANGENTS` arrays exactly, to zero error.

The `ARC` array is the cumulative **chord** length fraction at each vertex.
That is what the reference scripts use, and matching it is what makes the Trim
Paths reveal stay in step with the dots. A **Trim Paths arc mode** option in
the Comp & Animation tab switches to true Bézier arc length instead, which is
marginally more accurate on strongly curved paths since that is what After
Effects actually measures. Chord is the default because it reproduces existing
output.

Pixel mapping follows the reference convention:

```
x_pix = PLOT_L + t * (PLOT_R - PLOT_L)
y_pix = PLOT_B + t * (PLOT_T - PLOT_B)
```

Dates become decimal years as `year + (day_of_year - 1) / days_in_year`, so
2001-01-10 is 2001.0247, matching the reference `YEARS` arrays.

---

## Reproducing the reference charts

**Source3, cumulative capacity by launch year**

- Type `line`, X `Launch_Date`, Y `Bandwidth_Mbps` with transform
  `cumulative_sum`, sort `Launch_Date`
- Category `Orbit_Type` for the dot colours
- Y axis 0 to 250000

**Source5, connected scatter with size and colour encodings**

- Type `connected_scatter`, X `Latency_ms`, Y `Bandwidth_Mbps`, sort
  `Launch_Date`
- Category `Orbit_Type`, size `Altitude_km`
- Readout `Launch_Date` with prefix `LAUNCH YEAR  ` and 0 decimals

**Source4 and Source6, dual-axis rolling averages**

- Type `line`, X `Launch_Date`, sort `Launch_Date`
- Series 1 `Latency_ms`, transform `rolling_mean`, left axis
- Series 2 `Bandwidth_Mbps`, transform `rolling_mean`, right axis
- Category `Orbit_Type` for dots (this is the difference between 4 and 6)

**Two of the new types, from the CLI**

```bash
# share of capacity by orbit class, as a donut
python forge_cli.py build data.csv -o SAT_Capacity_Share.jsx \
    --type donut --group-by Orbit_Type --y Bandwidth_Mbps \
    --title "CAPACITY BY ORBIT CLASS"

# share of the fleet by count, as a solid pie with a gap between slices
python forge_cli.py build data.csv -o SAT_Fleet_Share.jsx \
    --type donut --group-by Orbit_Type --agg count --y Altitude_km \
    --inner-radius 0 --slice-gap 2 --title "SHARE OF FLEET"

# mean altitude per class, as a lollipop
python forge_cli.py build data.csv -o SAT_Altitude_Ranking.jsx \
    --type lollipop --group-by Orbit_Type --agg mean --y Altitude_km
```

`--group-by` is what makes these readable. Without it the slices fall back to
the X column, and an X like `Launch_Date` gives one wedge per row.

Or straight from the CLI:

```bash
python forge_cli.py build data.csv -o SAT_Altitude_Age_Effects.jsx \
    --type connected_scatter --x Latency_ms --y Bandwidth_Mbps \
    --sort Launch_Date --color-by Orbit_Type --size-by Altitude_km \
    --readout Launch_Date --readout-prefix "LAUNCH YEAR  " \
    --title "ORBITAL ALTITUDE & SATELLITE AGE" --comp SAT_Altitude_Age_Effects
```

---

## Command line

```bash
# show detected column types
python forge_cli.py inspect data.csv

# build from a preset saved in the app
python forge_cli.py build data.csv --preset chart.json -o chart.jsx

# build from flags, and save the resolved spec as a preset
python forge_cli.py build data.csv -o chart.jsx \
    --type line --x Launch_Date --y "Bandwidth_Mbps:cumulative_sum" \
    --sort Launch_Date --color-by Orbit_Type --save-preset chart.json
```

`--y` accepts `COLUMN:transform`, and `--right COLUMN` sends a series to the
right-hand axis.

---

## Layout

```
run.py                      launcher
forge_cli.py                headless generation
build.bat / build.sh        standalone app builds
.github/workflows/build.yml CI: test, build all three platforms, release
tools/ae_mock_check.js      mock AE host, validates expressions
aegraphforge/
  app.py                    entry point, dark theme
  core/
    dataset.py              CSV loader and type inference
    spec.py                 ChartSpec, the single source of truth
    scales.py               linear/log/sqrt mapping, tick generation
    geometry.py             Catmull-Rom tangents, arc length
    transform.py            series transforms, bar aggregation
    layout.py               text metrics, legend packing
    build.py                Dataset + ChartSpec -> RenderModel
    jsxgen.py               RenderModel -> ExtendScript
  ui/
    widgets.py              colour buttons, auto-range fields
    preview.py              WYSIWYG canvas
    mainwindow.py           the five configuration tabs
```

### Why the preview cannot drift

`build_model()` produces a `RenderModel` holding every number in composition
pixel space: vertices, tangents, arc fractions, tick positions, dot diameters,
legend coordinates. The preview and the JSX generator both consume that model
and neither does any geometry of its own. If the preview is right, the export
is right, because they are reading the same array.

This is also why legend placement lives in `core/layout.py` rather than in the
painter. The JSX side cannot measure a font at build time, so both sides use
the same Arial advance-width table and the same packing routine.

---

## Shape layer construction

Two details in the generated code are deliberate and worth knowing about if you
edit the output by hand.

**No cached shape-property references.** After Effects invalidates a stored
shape-property reference as soon as another item is added to the same vector
group, so a handle grabbed mid-build goes stale even though the layer is fine.
Every vector property is therefore given a name at creation time and looked
back up when it is used:

```js
vprop(line0, "LineGroup", "LineStroke").property("Stroke Width").expression = ...
```

`vgroup()` and `vprop()` walk `Contents` by index and match on name. Keep that
pattern if you add properties to a generated script.

**Identity transforms on path layers.** Vertices are precomputed in composition
pixel space, so a line or area layer sets Anchor Point and Position to the same
point (comp centre) on both the layer and its vector group. Equal anchor and
position means the transform contributes nothing and the path lands exactly
where it was computed, while the pivot stays at comp centre so scaling or
rotating the finished graph behaves sensibly. Dots and bars are excluded on
purpose: they are placed by Position, and their anchors stay put so Scale
pivots on the dot centre and the bar baseline respectively.

`tools/ae_mock_check.js` asserts both of these, along with the reveal invariant
that nothing is drawn at Progress 0.

---

## Building a standalone app

`build.bat` (Windows) and `build.sh` (macOS, Linux) wrap PyInstaller. Both take
an optional `onefile` argument, and `clean` to remove artefacts.

### Windows

```bat
build.bat
```

Output is `dist\AEGraphForge\AEGraphForge.exe`. For a single file:

```bat
build.bat onefile
```

Unsigned executables get a SmartScreen warning on first run. Sign with
`signtool` if you are distributing it.

### macOS

```bash
chmod +x build.sh
./build.sh
```

Output is `dist/AEGraphForge.app`. Gatekeeper blocks unsigned apps downloaded
from the internet, so either right-click and Open the first time, or clear the
quarantine flag:

```bash
xattr -cr dist/AEGraphForge.app
```

To sign and notarise properly:

```bash
codesign --deep --force --options runtime \
    --sign "Developer ID Application: YOUR NAME (TEAMID)" dist/AEGraphForge.app
ditto -c -k --keepParent dist/AEGraphForge.app AEGraphForge.zip
xcrun notarytool submit AEGraphForge.zip \
    --apple-id you@example.com --team-id TEAMID --wait
xcrun stapler staple dist/AEGraphForge.app
```

A build made on Apple Silicon runs on Apple Silicon only. For a universal
binary you need universal2 PySide6 wheels, which are not always published;
building on both architectures is the reliable route.

### Linux

```bash
chmod +x build.sh
./build.sh
```

Output is `dist/AEGraphForge/AEGraphForge`. Qt needs a few system libraries
that are not bundled:

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon-x11-0 libxcb-icccm4 \
    libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
    libxcb-shape0 libxcb-xinerama0 libxcb-cursor0
```

Build on the oldest distribution you intend to support, since glibc is forward
compatible but not backward.

---

## Continuous builds

`.github/workflows/build.yml` runs on push, on pull request, and on demand.

1. **test** byte-compiles the package, generates all six chart types, checks
   each script with `node --check`, then runs the mock After Effects host.
2. **build** produces Windows, macOS, and Linux apps in parallel and uploads
   each as a workflow artifact, with `presets/`, `examples/`, and the README
   alongside.
3. **release** fires only on a `v*` tag, zips the three builds and attaches
   them to a GitHub Release.

So pushing the repo gets you tested builds for all three platforms, and:

```bash
git tag v1.0.0 && git push --tags
```

gets you a release with downloadable zips. The workflow needs no secrets;
`GITHUB_TOKEN` is provided automatically and `permissions: contents: write` is
already declared.

---

## Notes and limits

- Generated code is ES3-safe, no arrow functions, `let`, `const`, or template
  literals, because the ExtendScript engine predates all of them.
- **Max dot layers** defaults to 400. Above that, points are strided and a
  comment in the script records the stride. Raise it if you want every point,
  but a 10,000-layer comp will be slow to open.
- Long value arrays are inlined into expression text. That is unavoidable:
  an AE expression evaluates in its own scope and cannot see variables the
  build script declared.
- The legend wraps to a second row when it runs past the plot rectangle. If it
  still crowds, widen the plot rect or shorten the labels.
- Small multiples and error bars are not implemented.
- Every control carries a tooltip explaining what it does and, where it
  matters, which choice is the honest one.
- Bar and donut charts do not draw a path, so the playhead and tip dot are
  skipped. A donut also has no cartesian axes, so gridlines and tick labels
  are skipped for it.

## Verification status

Reproduced against the reference scripts to zero error on tangents and arc
fractions. All chart types generate scripts that parse as JavaScript and
pass the mock AE host, which checks three things: every expression evaluates
cleanly across the Progress sweep, nothing is drawn at Progress 0, and every
path layer has matching anchor and position on both the layer and its vector
group.

Three checkers live in `tools/`, and all of them pass:

```bash
python tools/check_donut.py           # donut geometry, labels, ordering, presets
python tools/check_ui.py              # drag and drop and the mapping panels
node   tools/ae_mock_check.js *.jsx   # generated scripts against a mock AE host
```

`check_ui.py` builds a real main window under Qt's offscreen platform plugin
and drives it with synthetic drag and drop events, so the widget wiring is
exercised rather than just the model beneath it.

The generated scripts have **not** been executed inside a real After Effects
install, so give the first export a look before committing to a batch.


## Animation controls (updated)

Comp & Animation now separates **overall easing** (the Progress timeline) from
**per-item easing** (each line segment, bar, dot movement or pie slice).
Start and end strengths are independent. Choose Linear, Bezier/keyframe influence,
Smoothstep, Sine, Quad, Cubic, Quart, Quint or Expo. For named curves, 0% blends
back to Linear and 100% uses the full curve. Older presets continue to use their
saved `ease_influence` for both ends and the original per-chart easing.

Animation style:

- **Original / by data point** keeps the original reveal order and Trim Paths
  timing. The arc measure still controls the original chord/Bezier mapping.
- **Draw on / uniform across screen** moves the line's leading edge across the
  plot at a uniform X rate. Pie/donut charts use a continuous angular sweep,
  giving larger slices proportionally more time. Bars grow linearly in order.
- **Draw on / uniform path speed** draws a line at constant distance per unit of
  Progress. Pie/donut charts again use angular distance. Single-series bars
  allocate time by bar length; grouped/stacked bars stay synchronized per group.
- **Rise / stagger items** moves line/scatter points from their baseline, grows
  bars/candles and animates pie slices in overlapping windows. Delay 0 starts
  them all together. Reverse changes the stagger order. Delay is measured in
  seconds of the uneased Progress interval; overall easing also shapes these
  delays. If the requested delay cannot fit, the model shortens it and warns.

For constant speed in real time, choose **Linear overall easing**. Uniform modes
bypass per-item easing on drawn paths, bars and slices so they do not pause at
individual data items. A path that doubles back in X (including smoothing
overshoot) cannot follow a one-direction horizontal sweep; that series falls
back to constant path distance and the app shows a warning. Curve distance is
sampled numerically, so small subpixel differences from AE are possible.

Candlesticks are configured on Mapping: choose Candlestick, select X, then map
Open/High/Low/Close. Each valid row becomes one candle. Equal Open and Close
values produce a visible doji body. Low must be <= Open/Close <= High. The Y
range includes wick extremes. Log Y requires positive OHLC values.

CLI flags are available too, for example:

```bash
python forge_cli.py build prices.csv --type candlestick --x Date \
  --open Open --high High --low Low --close Close \
  --animation-mode rise --stagger-seconds 0.06 --ease-family sine \
  --ease-start 100 --ease-end 70 -o prices.jsx
```

### Review fixes and verification

- Preview playback now respects easing strength and curve selection.
- Preview trimming uses arc length instead of Qt's Bezier parameter; tip dots
  follow the actual curve and stay with the line's leading edge.
- Missing-value dot timing is exported from the resolved model instead of
  recomputing a compressed index in the script.
- Stacked area fills are exported; area wipes account for composition width.
- Negative bars grow in the correct direction, stacked segments use their own
  baselines, and grouped/stacked ranges include individual positive/negative
  values. Value labels and lollipop heads follow the growing bar ends.
- Invalid Progress times and inverted plot bounds produce readable errors.
- A zero easing value exports safely instead of constructing an invalid
  zero-influence KeyframeEase.

Run `python tools/check_animation.py` for curve parity, geometry, validation,
preset compatibility and 104 JSX export combinations evaluated in the mock AE
host. `python tools/check_donut.py` covers the existing chart/preset regressions.
These checks do not replace opening a generated JSX in After Effects.


## Histograms, box plots and heatmaps

All three appear in Mapping > Chart type and use a dedicated **Value column**.
Their options, colours, mappings and animation settings are saved in chart
presets. They export editable AE shape layers and expressions just like the
existing graphs.

**Histogram**: choose a numeric Value column and a bin count. Zero chooses the
square-root rule (capped at 100); explicit counts support 1 to 200 bins. Bins
have equal data width, and the last bin includes the maximum observation.
Count gives raw frequencies, Probability sums the bin heights to 1, and Density
makes the total bar area equal 1. Constant values receive a nonzero bin range.
Histogram axes must be linear. Set axis titles in Axes to match the chosen
value and normalization. Missing values are skipped with a warning.

**Box plot**: choose a numeric Value column and optional Group by column. Without
a group column there is one box. The box spans Q1 to Q3 and its line is the
median. Quartiles use linear interpolation at `(n - 1) * p`; whiskers reach the
most extreme observations within 1.5 times the interquartile range. Values beyond
that range are optional outlier dots. Max dot layers limits the outlier dots,
while statistics always include every observation. Group ordering uses the
median for value sorts; 0 Max groups includes all groups. Single-observation
and constant groups remain visible. Log Y requires positive plotted values.

**Heatmap**: map Columns and Rows to category columns (numeric/date columns may
also serve as category labels). Map the Value column and select Sum, Mean,
Median, Count, Min or Max. Count works without a numeric Value mapping. Repeated
pairs are aggregated; missing combinations remain blank, and genuine zero
values get a colour. Categories retain their first-seen CSV order. The colour
legend covers the observed aggregate minimum/maximum; equal-valued cells use
the gradient midpoint. Cell values can be hidden, and text is fitted to each
cell and omitted when it would be smaller than 8 px. Grids larger than 1600
cells are rejected with a readable message. Axis numeric ranges/scales do not
change category placement; use axis titles and label sizes for presentation.

Animation: histograms use the existing bar growth controls. Box-plot parts stay
synchronized by group; Rise animates them from the plot bottom. Heatmaps reveal
cells in row order, sweep columns together in uniform horizontal mode, or rise
with the configured delay. Delay 0 starts every group/cell together. Uniform
modes use linear item timing; overall easing still shapes the whole timeline.

CLI examples:

```bash
python forge_cli.py build data.csv --type histogram --value-column Amount --histogram-bins 12 -o histogram.jsx
python forge_cli.py build data.csv --type box_plot --value-column Amount --group-by Region -o boxes.jsx
python forge_cli.py build data.csv --type heatmap --value-column Amount --heatmap-x Month --heatmap-y Region --agg mean -o heatmap.jsx
```

Run `python tools/check_distributions.py` for statistics, edge cases, preset
round trips and UI mapping checks. The expanded `tools/check_animation.py` now
checks 128 graph/mode/control-binding export combinations through the mock AE
host, including all three new chart types.

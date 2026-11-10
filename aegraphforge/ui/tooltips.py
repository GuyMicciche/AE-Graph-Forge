"""Tooltip text for every control in the main window.

Kept in one table rather than scattered through the widget construction, so
the wording stays consistent and a missing tooltip is easy to spot. Anything
listed here is matched to the attribute of the same name on MainWindow.
"""

from __future__ import annotations

from typing import Dict

# ---------------------------------------------------------------------------
# The three axis blocks are built from one factory, so their tooltips are
# keyed by the suffix and formatted with the axis name.
# ---------------------------------------------------------------------------
AXIS_TIPS: Dict[str, str] = {
    "title": "Axis title, drawn beside the {axis} axis.\n"
             "Leave blank to omit it entirely.",
    "tsize": "Point size of the {axis} axis title.",
    "unit": "Short unit label such as ms, Mbps or km.\n"
            "Drawn near the end of the {axis} axis, separate from the title.",
    "usize": "Point size of the {axis} axis unit label.",
    "scale": "Linear spreads values evenly.\n"
             "Log10 suits data spanning orders of magnitude and cannot show "
             "zero or negatives.\n"
             "Square root compresses large values more gently than log.",
    "range": "Lowest and highest value the {axis} axis covers.\n"
             "Auto reads the data and pre-fills the boxes, so you can nudge "
             "one end without typing the other.",
    "ticks": "Roughly how many labelled gridlines to aim for.\n"
             "With Nice round ticks on, the real count may differ slightly to "
             "land on tidy numbers.",
    "dec": "Decimal places on tick labels.\n"
           "-1 chooses automatically from the tick spacing.",
    "size": "Point size of the {axis} axis tick labels.",
    "lscale": "Divide tick LABELS by a power of ten to keep them short, so "
              "4,500,000 reads as 4.5M.\n"
              "Cosmetic only: plotted values, ranges and the readout are "
              "untouched.\n"
              "Auto picks the magnitude from the data.",
    "lsuffix": "Append K, M or B to shortened labels.\n"
               "Turn off if the unit field already says thousands or millions.",
    "nice": "Snap the range and tick spacing to round numbers such as 0, 50, "
            "100 rather than the raw data extremes.",
    "sep": "Group thousands with commas, so 40000 prints as 40,000.",
    "grid": "Draw gridlines across the plot for this axis.",
}

AXIS_NAMES = {"ax": "X", "ay": "Y", "ay2": "second Y"}

# ---------------------------------------------------------------------------
TIPS: Dict[str, str] = {
    # -- data ---------------------------------------------------------------
    "btn_open": "Open a CSV or TSV file.\n"
                "The delimiter and each column's type are detected on load.",
    "lbl_path": "The file currently loaded.",
    "col_list": "Every column found, with its detected type and a summary.\n"
                "Check these look right before mapping columns to the chart.",
    "table": "The first rows of the file, exactly as parsed.\n"
             "Useful for spotting a stray header row or a misread date.",
    "btn_auto": "Pick a chart type and column mapping that suit the data.\n"
                "A good starting point you can then adjust.",

    # -- mapping ------------------------------------------------------------
    "cb_type": "How the data is drawn.\n"
               "Line, step and area types plot a value against a continuous X.\n"
               "Bar, lollipop and donut aggregate rows into groups first.",
    "cb_x": "Column that positions points along the horizontal axis.\n"
            "Dates become decimal years automatically.",
    "cb_sort": "Column that decides the order points are revealed in.\n"
               "Usually a date. Often the same as X, but a connected "
               "scatterplot normally sorts by time while plotting two other "
               "measures.",
    "chk_sort_asc": "Reveal from lowest to highest.\n"
                    "Turn off to run the animation backwards through the data.",
    "cb_group": "Column whose values become the bars or slices.\n"
                "Rows sharing a value are combined using the aggregation "
                "below, so a category column like Orbit_Type gives one slice "
                "per orbit rather than one per row.",
    "cb_agg": "How rows in the same group are combined into one number.\n"
              "Count ignores the value column and just counts rows in the "
              "group, which is what a share-of-fleet chart wants.",
    "cb_slice_sort": "Order the groups are drawn in.\n"
                     "The Max setting always keeps the largest groups, "
                     "whichever order you display them in.",
    "sp_maxbars": "Cap on how many groups to draw.\n"
                  "The largest are kept; on a donut the rest merge into an "
                  "Other slice. Set to 0 for no cap.",
    "grp_bar": "How rows are collapsed into groups. Applies to every bar "
               "type, the lollipop and the donut.",
    "grp_slice_colors": "A colour per group in the current chart.\n"
                        "The list follows what is actually drawn, including "
                        "the merged Other slice.",
    "grp_lolli": "Settings for lollipop charts.",
    "grp_donut": "Settings for donut and pie charts.",
    "sp_stem": "Thickness of the lollipop stem in pixels.\n"
               "Thin stems read best, since the head carries the value.",
    "sp_head": "Diameter of the lollipop head in pixels.",
    "sp_ring_r": "Outer edge of the ring, as a percentage of half the shorter "
                 "plot dimension.",
    "sp_ring_i": "Inner edge of the ring, as a percentage of the outer "
                 "radius.\n"
                 "0% closes the hole completely and gives a solid pie; "
                 "around 55% is a conventional donut.",
    "sp_ring_gap": "Gap cut between neighbouring slices, in degrees.\n"
                   "A degree or two separates slices of similar colour "
                   "without distorting the shares.",
    "chk_dlabels": "Draw a label beside each slice.",
    "cb_dlabel": "What each slice label says.",
    "cb_dplace": "Outside sits the label beyond the ring and reads outward.\n"
                 "Inside centres it on the band, which suits a thick ring or "
                 "a pie with few slices.",
    "sp_dminpct": "Drop the label on any slice smaller than this share.\n"
                  "Keeps a long tail of thin slices from crowding the ring.",

    # -- series -------------------------------------------------------------
    "series_list": "Every plotted series. Select one to edit it below.",
    "btn_add_series": "Plot another column on the same chart.",
    "btn_del_series": "Remove the selected series.",
    "se_col": "Column supplying this series' values.",
    "se_label": "Name shown in the legend and used for its colour control.\n"
                "Defaults to the column name.",
    "se_color": "Series colour. With MASTER_CONTROLS binding on, this becomes "
                "the starting value of a colour control you can change later "
                "in After Effects.",
    "se_axis": "Put this series on the left or the right axis.\n"
               "Use the right axis when two series have very different units.",
    "se_transform": "Maths applied before plotting.\n"
                    "Cumulative sum builds a running total, rolling mean "
                    "smooths noise, index to 100 rebases everything to a "
                    "common start.",
    "se_window": "How many points the rolling transforms average over.\n"
                 "Larger is smoother and slower to react.",
    "se_stroke": "Line thickness in pixels.",
    "se_smooth": "Curve the line through the points with Catmull-Rom tangents.\n"
                 "Off draws straight segments, which is more honest for sparse "
                 "or irregular data.",
    "se_dots": "Draw a dot at every data point on this series.",
    "se_dotsize": "Dot diameter in pixels, when no size column is driving it.",
    "se_fill": "Opacity of a fill under the line, 0 for none.\n"
               "Any value above zero turns a line chart into an area chart for "
               "this series.",

    # -- encodings ----------------------------------------------------------
    "chk_cat": "Colour points by a category column rather than by series.",
    "cb_cat": "Column holding the category of each row, such as LEO, MEO, GEO.\n"
              "Each distinct value gets its own colour and legend entry.",
    "cat_holder": "One colour per category. Each also becomes a MASTER_CONTROLS "
                  "colour control you can change after the build.",
    "chk_size": "Scale dot size by a numeric column.",
    "cb_size": "Column driving dot size.",
    "sp_dmin": "Diameter of the smallest dot, in pixels.",
    "sp_dmax": "Diameter of the largest dot, in pixels.",
    "chk_sqrt": "Map the value to dot AREA rather than diameter.\n"
                "Recommended: the eye compares areas, so this is the honest "
                "encoding.",

    # -- readout ------------------------------------------------------------
    "chk_readout": "Show a large number that counts along as Progress sweeps, "
                   "like the launch-year counter in your reference scripts.",
    "cb_readout": "Column the readout interpolates.",
    "ed_rpre": "Text before the number, such as 'LAUNCH YEAR  '.",
    "ed_rsuf": "Text after the number, such as ' Mbps'.",
    "sp_rdec": "Decimal places in the readout.\n"
               "0 floors the value, which is what a year counter wants.",
    "sp_rsize": "Point size of the readout text.",
    "cb_rcorner": "Which corner of the composition the readout sits in.",

    # -- style: text --------------------------------------------------------
    "ed_title": "Main title, drawn top left.",
    "ed_sub": "Smaller line under the title.",
    "ed_cap": "Third, smallest line. Good for explaining the encodings.",
    "sp_tsize": "Point size of the title.",
    "sp_ssize": "Point size of the subtitle.",
    "sp_csize": "Point size of the caption.",
    "fc_font": "Typeface for every text layer.\n"
               "After Effects matches fonts by PostScript name, so the script "
               "tries the usual bold spellings of this family before falling "
               "back to Arial.",
    "ed_psname": "Exact PostScript name, tried before anything else.\n"
                 "Use this if a font refuses to apply. In After Effects the "
                 "Character panel tooltip shows the correct name.",

    # -- style: colour ------------------------------------------------------
    "c_bg": "Composition background colour.",
    "c_grid": "Gridline colour.",
    "c_axis": "Colour of tick labels, axis titles and value labels.",
    "c_title": "Title colour.",
    "c_sub": "Subtitle colour.",
    "c_cap": "Caption colour.",
    "sp_gridop": "Gridline opacity, 0 to 100.",
    "sp_gridw": "Gridline thickness in pixels.",

    # -- style: chrome ------------------------------------------------------
    "chk_legend": "Draw the legend along the bottom.\n"
                  "It wraps to a second row if it runs past the plot.",
    "sp_lsize": "Point size of legend labels.",
    "chk_playhead": "Draw a vertical line that tracks the leading edge.",
    "sp_phop": "Playhead opacity.",
    "chk_tip": "Draw a dot riding the front of the line.",
    "sp_tipsize": "Diameter of the tip dot in pixels.",
    "sp_dotop": "Opacity dots reach once revealed.",
    "ck_fromzero": "Each point owns a slice of the timeline, so Progress 0 is "
                   "an empty frame and even the first point animates in.\n"
                   "Turn off to match the original scripts, where the first "
                   "point is already drawn at Progress 0.",
    "sp_lead": "Extra Progress units of fade-in before a point's own slot.\n"
               "Clamped so nothing can appear before Progress 0.",
    "sp_lag": "Extra Progress units of fade-in after a point's slot.",
    "sp_maxdots": "Ceiling on how many dot layers to create.\n"
                  "Beyond this, points are strided so the comp stays openable. "
                  "The script records the stride in a comment.",
    "chk_bind": "Wire every look property to controls on a MASTER_CONTROLS "
                "null, so colours, weights and opacities stay adjustable in "
                "After Effects without regenerating.\n"
                "Off bakes the values and leaves only Progress driving the "
                "reveal.",

    # -- comp ---------------------------------------------------------------
    "ed_comp": "Name of the composition the script creates.",
    "sp_w": "Composition width in pixels.",
    "sp_h": "Composition height in pixels.",
    "sp_fps": "Frame rate. Also the rate the preview plays back at.",
    "sp_dur": "Composition length in seconds.",
    "sp_pstart": "Time the Progress slider leaves 0.\n"
                 "The gap before it is breathing room at the head of the shot.",
    "sp_pend": "Time Progress reaches 100.\n"
               "The gap after it lets the finished graph hold on screen.",
    "sp_ease": "Overall start ease. For Bezier this is outgoing keyframe influence; for named curves it blends Linear (0%) to the full curve (100%).",
    "sp_ease_end": "Overall end ease, independent of the start. Bezier uses incoming keyframe influence.",
    "cb_ease_family": "Curve for the entire Progress animation. Linear gives constant clock speed; start/end strengths independently shape other curves.",
    "cb_item_family": "Curve inside each point/bar/slice interval. Original preserves each chart's previous behavior. Uniform draw-on bypasses item easing to preserve speed.",
    "sp_item_in": "Per-item ease-in strength (0% linear, 100% full curve).",
    "sp_item_out": "Per-item ease-out strength, independent of ease-in.",
    "cb_animation": "Original follows data order. Uniform across screen sweeps X at a steady rate; uniform path follows distance. Rise animates all items with overlapping delays.",
    "sp_stagger": "Delay per item in seconds of the uneased Progress interval. 0 animates all items together. Excessive delay is shortened to fit, with a warning.",
    "ck_reverse": "Reverse the order in which items start rising.",
    "sp_pl": "Left edge of the plotting area, in composition pixels.",
    "sp_pr": "Right edge of the plotting area.",
    "sp_pt": "Top edge of the plotting area.",
    "sp_pb": "Bottom edge of the plotting area.",
    "btn_fit": "Reset the plot rectangle to sensible margins for the current "
               "composition size.",
    "cb_arc": "How Trim Paths distance is measured along the curve.\n"
              "Chord matches your original scripts. Bezier uses true arc "
              "length, which After Effects actually measures, and syncs "
              "slightly better on strongly curved paths.",

    # -- output -------------------------------------------------------------
    "btn_save": "Write the ExtendScript to a .jsx file.",
    "btn_copy": "Copy the whole script to the clipboard.",
    "chk_open": "Add a line that opens the finished comp in the viewer.",
    "script": "The generated ExtendScript, refreshed as you change settings.\n"
              "Run it with File > Scripts > Run Script File in After Effects.",
    "preview": "Live preview at the composition's real proportions.\n"
               "It reads the same numbers the script will, so nothing can "
               "drift between this and the render.",
    "tabs": "Configuration, grouped by what it affects.",
    "ay2_box": "Enable a second value axis on the right.\n"
               "Its ticks are aligned to the left axis so both share the same "
               "gridlines. Send a series to it from the Mapping tab.",
}

# tooltips for the preview transport, which lives on the PreviewPanel
PREVIEW_TIPS: Dict[str, str] = {
    "btn_play": "Play the reveal at the composition frame rate, using the "
                "Progress keyframe times from the Comp & Animation tab.",
    "btn_loop": "Restart automatically at the end.",
    "slider": "Scrub Progress by hand. Starting a drag stops playback.",
    "guides": "Outline the plotting rectangle, to help place titles and "
              "legends.",
    "value_label": "Composition time and the Progress value at that time.",
    "canvas": "Live preview at the composition's real proportions.\n"
              "It reads the same numbers the script will, so nothing can drift "
              "between this and the render.",
}


def apply_tooltips(win) -> int:
    """Attach every tooltip. Returns how many controls were covered."""
    n = 0
    for attr, text in TIPS.items():
        wdg = getattr(win, attr, None)
        if wdg is not None:
            wdg.setToolTip(text)
            n += 1

    for prefix, axis_name in AXIS_NAMES.items():
        for suffix, text in AXIS_TIPS.items():
            wdg = getattr(win, f"{prefix}_{suffix}", None)
            if wdg is not None:
                wdg.setToolTip(text.format(axis=axis_name))
                n += 1

    panel = getattr(win, "preview", None)
    if panel is not None:
        for attr, text in PREVIEW_TIPS.items():
            wdg = getattr(panel, attr, None)
            if wdg is not None:
                wdg.setToolTip(text)
                n += 1
    return n

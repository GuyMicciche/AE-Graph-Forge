"""
mainwindow.py -- AE Graph Forge main window.

Left side: five panels of configuration. Right side: the live preview and the
generated script. Every edit runs the same pipeline the exporter uses
(build_model -> RenderModel), so the preview is never an approximation.
"""

from __future__ import annotations

import os
import traceback
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QFontComboBox,
                               QFileDialog, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QSplitter, QStatusBar, QTabWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..core.build import build_model
from ..core.dataset import CATEGORY, DATE, Dataset, NUMERIC
from ..core.jsxgen import generate_jsx
from ..core.spec import (LABEL_SCALES, SCALE_NONE, AGGREGATIONS, AREA, BAR, BAR_LIKE,
                         CHART_TYPES, CONNECTED_SCATTER, CategorySpec, ChartSpec,
                         DONUT, DONUT_LABEL_MODES, DONUT_LABEL_PLACES,
                         HBAR, LINE, LOLLIPOP, SCALES, SCATTER, SLICE_SORTS,
                         SeriesSpec, TRANSFORMS, palette_color)
from .preview import PreviewPanel
from .tooltips import apply_tooltips
from .widgets import (WideComboBox, AutoRange, ColorButton, combo, fill_columns, form,
                      group, hint, hline, scroller, spin)

APP_NAME = "AE Graph Forge"

# Chart types whose rows are aggregated into groups before anything is drawn.
# All of them read Group by / Aggregate / Order, not just the plain bars.
GROUPED_TYPES = tuple(BAR_LIKE) + (DONUT,)
# ... and of those, the ones that colour each group individually. Grouped and
# stacked bars take their colours from the series instead.
PER_GROUP_COLOR = (BAR, HBAR, LOLLIPOP, DONUT)

# What a dropped file is taken to be. The delimiter inside a .txt is sniffed
# on load, so it is offered here on the same footing as .csv and .tsv.
DATA_SUFFIXES = (".csv", ".tsv", ".txt")
PRESET_SUFFIXES = (".json",)

DROP_HINT_CSS = """
    background: rgba(20, 21, 25, 190);
    color: #e8eaf0;
    font-size: 20px;
    font-weight: 600;
    border: 3px dashed #6f9ad8;
    border-radius: 10px;
"""


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 940)

        self.ds: Optional[Dataset] = None
        self.spec = ChartSpec()
        self.model = None
        self._loading = False
        self._script_dirty = True
        self._cat_buttons: Dict[str, ColorButton] = {}
        self._slice_buttons: Dict[str, ColorButton] = {}
        self._slice_levels: List[str] = []

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(140)
        self._timer.timeout.connect(self._refresh)

        self._build_ui()
        self._build_menu()
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Open a CSV to begin.")

    # =====================================================================
    # layout
    # =====================================================================
    def _build_ui(self) -> None:
        split = QSplitter(Qt.Horizontal)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_data(), "Data")
        self.tabs.addTab(self._tab_mapping(), "Mapping")
        self.tabs.addTab(self._tab_axes(), "Axes")
        self.tabs.addTab(self._tab_style(), "Style")
        self.tabs.addTab(self._tab_anim(), "Comp && Animation")
        self.tabs.setMinimumWidth(430)
        split.addWidget(self.tabs)

        right = QTabWidget()
        self.preview = PreviewPanel()
        right.addTab(self.preview, "Preview")

        self.script = QPlainTextEdit()
        self.script.setReadOnly(True)
        f = QFont("Menlo")
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(10)
        self.script.setFont(f)
        self.script.setLineWrapMode(QPlainTextEdit.NoWrap)
        right.addTab(self.script, "Script")

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        right.addTab(self.table, "Table")

        right.currentChanged.connect(self._tab_switched)
        self._right = right
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([450, 1050])
        self.setCentralWidget(split)

        # Files can be dropped anywhere on the window. The three large panes
        # on the right accept drops of their own by default, which would
        # swallow the event before it reached us, so they are opted out.
        self.setAcceptDrops(True)
        for pane in (self.script, self.table, self.col_list):
            pane.setAcceptDrops(False)
        self._drop_hint = QLabel("", self)
        self._drop_hint.setAlignment(Qt.AlignCenter)
        self._drop_hint.setStyleSheet(DROP_HINT_CSS)
        self._drop_hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._drop_hint.hide()

        apply_tooltips(self)

    def _build_menu(self) -> None:
        bar = self.menuBar()
        m = bar.addMenu("&File")
        for text, slot, key in (
            ("&Open CSV...", self.open_csv, QKeySequence.Open),
            ("&Save Script...", self.save_jsx, QKeySequence.Save),
            ("&Copy Script", self.copy_jsx, QKeySequence.Copy),
        ):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if key:
                a.setShortcut(key)
            m.addAction(a)
        m.addSeparator()
        for text, slot in (("Load Preset...", self.load_preset),
                           ("Save Preset...", self.save_preset)):
            a = QAction(text, self)
            a.triggered.connect(slot)
            m.addAction(a)
        m.addSeparator()
        a = QAction("Quit", self)
        a.triggered.connect(self.close)
        m.addAction(a)

    # =====================================================================
    # tab: data
    # =====================================================================
    def _tab_data(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        row = QHBoxLayout()
        self.btn_open = QPushButton("Open CSV...")
        self.btn_open.clicked.connect(self.open_csv)
        self.btn_auto = QPushButton("Auto-configure")
        self.btn_auto.clicked.connect(self.auto_configure)
        self.btn_auto.setEnabled(False)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_auto)
        row.addStretch(1)
        lay.addLayout(row)

        self.lbl_path = QLabel("No file loaded.")
        self.lbl_path.setWordWrap(True)
        lay.addWidget(self.lbl_path)
        lay.addWidget(hline())

        lay.addWidget(QLabel("Detected columns"))
        self.col_list = QListWidget()
        self.col_list.setAlternatingRowColors(True)
        lay.addWidget(self.col_list, 1)
        lay.addWidget(hint(
            "Types are inferred from the values: numeric, date (parsed to a "
            "decimal year so it scales linearly), category, or free text. "
            "Only numeric and date columns can drive an axis."))
        return w

    # =====================================================================
    # tab: mapping
    # =====================================================================
    def _tab_mapping(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        f = form()
        self.cb_type = combo(CHART_TYPES, LINE)
        self.cb_x = WideComboBox()
        self.cb_sort = WideComboBox()
        self.chk_sort_asc = QCheckBox("Ascending")
        self.chk_sort_asc.setChecked(True)
        f.addRow("Chart type", self.cb_type)
        f.addRow("X column", self.cb_x)
        srow = QHBoxLayout()
        srow.addWidget(self.cb_sort, 1)
        srow.addWidget(self.chk_sort_asc)
        f.addRow("Order by", srow)
        lay.addWidget(group("Chart", f))

        # -- grouping (bars, lollipop and donut all aggregate first) -------
        bf = form()
        self.cb_group = WideComboBox()
        self.cb_agg = combo(AGGREGATIONS, "sum")
        self.cb_slice_sort = combo(SLICE_SORTS, "value_desc")
        self.sp_maxbars = spin(0, 200, 20)
        bf.addRow("Group by", self.cb_group)
        bf.addRow("Aggregate", self.cb_agg)
        bf.addRow("Order", self.cb_slice_sort)
        self.lbl_maxbars = QLabel("Max groups")
        bf.addRow(self.lbl_maxbars, self.sp_maxbars)
        self.grp_bar = group("Grouping", bf)
        lay.addWidget(self.grp_bar)

        # -- per-group colours --------------------------------------------
        cf = form()
        self.slice_holder = QWidget()
        self.slice_layout = QGridLayout(self.slice_holder)
        self.slice_layout.setContentsMargins(0, 0, 0, 0)
        cf.addRow(self.slice_holder)
        cf.addRow(hint("One swatch per group in the current chart. Changing "
                       "'Group by' or the aggregation refreshes the list."))
        self.grp_slice_colors = group("Group colours", cf)
        lay.addWidget(self.grp_slice_colors)

        # -- lollipop ------------------------------------------------------
        lf = form()
        self.sp_stem = spin(1, 60, 6, 1, 1)
        self.sp_head = spin(4, 200, 26, 1, 1)
        lf.addRow("Stem width", self.sp_stem)
        lf.addRow("Head size", self.sp_head)
        self.grp_lolli = group("Lollipop", lf)
        lay.addWidget(self.grp_lolli)

        # -- donut / pie ---------------------------------------------------
        df = form()
        self.sp_ring_r = spin(10, 100, 78, 1, 0, suffix=" %")
        self.sp_ring_i = spin(0, 95, 55, 1, 0, suffix=" %")
        self.sp_ring_gap = spin(0, 20, 0, 1, 1, suffix=" deg")
        self.chk_dlabels = QCheckBox("Slice labels")
        self.chk_dlabels.setChecked(True)
        self.cb_dlabel = combo(DONUT_LABEL_MODES, "name_percent")
        self.cb_dplace = combo(DONUT_LABEL_PLACES, "outside")
        self.sp_dminpct = spin(0, 50, 0, 1, 1, suffix=" %")
        df.addRow("Outer radius", self.sp_ring_r)
        df.addRow("Inner radius", self.sp_ring_i)
        df.addRow("Slice gap", self.sp_ring_gap)
        df.addRow("", self.chk_dlabels)
        df.addRow("Label text", self.cb_dlabel)
        df.addRow("Label place", self.cb_dplace)
        df.addRow("Hide under", self.sp_dminpct)
        df.addRow(hint("Inner radius 0% gives a solid pie with no hole. "
                       "The outer radius is a share of half the shorter side "
                       "of the plot area."))
        self.grp_donut = group("Donut / Pie", df)
        lay.addWidget(self.grp_donut)

        # -- series -------------------------------------------------------
        sgroup = QGroupBox("Y series")
        sl = QVBoxLayout(sgroup)
        self.series_list = QListWidget()
        self.series_list.setMaximumHeight(96)
        self.series_list.currentRowChanged.connect(self._series_selected)
        sl.addWidget(self.series_list)
        brow = QHBoxLayout()
        self.btn_add_series = QPushButton("Add")
        self.btn_del_series = QPushButton("Remove")
        self.btn_add_series.clicked.connect(self._add_series)
        self.btn_del_series.clicked.connect(self._del_series)
        brow.addWidget(self.btn_add_series)
        brow.addWidget(self.btn_del_series)
        brow.addStretch(1)
        sl.addLayout(brow)

        sf = form()
        self.se_col = WideComboBox()
        self.se_label = QLineEdit()
        self.se_color = ColorButton((0.95, 0.95, 0.95))
        self.se_axis = combo([("left", "Left"), ("right", "Right")], "left")
        self.se_transform = combo(TRANSFORMS, "none")
        self.se_window = spin(1, 500, 8)
        self.se_stroke = spin(0, 60, 4, 0.5, 1)
        self.se_fill = spin(0, 100, 0, 1, 0, " %")
        self.se_dots = QCheckBox("Show dots")
        self.se_dotsize = spin(1, 200, 10, 1, 1)
        self.se_smooth = QCheckBox("Smooth (Catmull-Rom)")
        self.se_smooth.setChecked(True)
        sf.addRow("Column", self.se_col)
        sf.addRow("Label", self.se_label)
        sf.addRow("Colour", self.se_color)
        sf.addRow("Axis", self.se_axis)
        sf.addRow("Transform", self.se_transform)
        sf.addRow("Window", self.se_window)
        sf.addRow("Stroke", self.se_stroke)
        sf.addRow("Area fill", self.se_fill)
        drow = QHBoxLayout()
        drow.addWidget(self.se_dots)
        drow.addWidget(self.se_dotsize)
        drow.addStretch(1)
        sf.addRow("Dots", drow)
        sf.addRow("", self.se_smooth)
        sl.addLayout(sf)
        lay.addWidget(sgroup)

        # -- encodings ----------------------------------------------------
        ef = form()
        self.chk_cat = QCheckBox("Colour dots by category")
        self.cb_cat = WideComboBox()
        ef.addRow(self.chk_cat, self.cb_cat)
        self.cat_holder = QWidget()
        self.cat_layout = QGridLayout(self.cat_holder)
        self.cat_layout.setContentsMargins(0, 0, 0, 0)
        ef.addRow("", self.cat_holder)

        self.chk_size = QCheckBox("Size dots by value")
        self.cb_size = WideComboBox()
        ef.addRow(self.chk_size, self.cb_size)
        srow2 = QHBoxLayout()
        self.sp_dmin = spin(1, 500, 10, 1, 1)
        self.sp_dmax = spin(1, 500, 46, 1, 1)
        self.chk_sqrt = QCheckBox("sqrt")
        self.chk_sqrt.setChecked(True)
        self.chk_sqrt.setToolTip("Scale diameter by sqrt so dot AREA is "
                                 "proportional to the value, which is how a "
                                 "reader actually perceives it.")
        srow2.addWidget(self.sp_dmin)
        srow2.addWidget(self.sp_dmax)
        srow2.addWidget(self.chk_sqrt)
        ef.addRow("Diameter", srow2)
        lay.addWidget(group("Encodings", ef))

        # -- readout ------------------------------------------------------
        rf = form()
        self.chk_readout = QCheckBox("Live readout")
        self.cb_readout = WideComboBox()
        self.ed_rpre = QLineEdit()
        self.ed_rsuf = QLineEdit()
        self.sp_rdec = spin(0, 6, 0)
        self.sp_rsize = spin(8, 200, 30, 1, 1)
        self.cb_rcorner = combo([("top_right", "Top right"), ("top_left", "Top left"),
                                 ("bottom_right", "Bottom right"),
                                 ("bottom_left", "Bottom left")], "top_right")
        rf.addRow(self.chk_readout, self.cb_readout)
        rf.addRow("Prefix", self.ed_rpre)
        rf.addRow("Suffix", self.ed_rsuf)
        rf.addRow("Decimals", self.sp_rdec)
        rf.addRow("Text size", self.sp_rsize)
        rf.addRow("Corner", self.cb_rcorner)
        lay.addWidget(group("Readout", rf))

        lay.addStretch(1)

        self._wire_all(w)
        self.cb_type.currentIndexChanged.connect(self._type_changed)
        self.chk_cat.toggled.connect(self._rebuild_cat_colors)
        self.cb_cat.currentIndexChanged.connect(self._rebuild_cat_colors)
        return scroller(w)

    # =====================================================================
    # tab: axes
    # =====================================================================
    def _axis_block(self, title: str, prefix: str, with_enable: bool = False) -> QGroupBox:
        f = form()
        ed_title = QLineEdit()
        ed_unit = QLineEdit()
        cb_scale = combo(SCALES, "linear")
        sp_ticks = spin(2, 30, 6)
        chk_nice = QCheckBox("Nice round ticks")
        chk_nice.setChecked(True)
        chk_grid = QCheckBox("Gridlines")
        chk_grid.setChecked(True)
        sp_dec = spin(-1, 8, -1)
        sp_dec.setToolTip("-1 chooses the decimal count from the tick spacing.")
        chk_sep = QCheckBox("Thousands separator")
        chk_sep.setChecked(True)
        rng = AutoRange()
        sp_size = spin(6, 120, 22, 1, 1)
        sp_tsize = spin(6, 160, 22, 1, 1)
        sp_usize = spin(6, 120, 18, 1, 1)
        cb_lscale = combo(LABEL_SCALES, SCALE_NONE)
        chk_lsuffix = QCheckBox("Append K / M / B")
        chk_lsuffix.setChecked(True)

        f.addRow("Title", ed_title)
        f.addRow("Title size", sp_tsize)
        f.addRow("Unit", ed_unit)
        f.addRow("Unit size", sp_usize)
        f.addRow("Scale", cb_scale)
        f.addRow("Range", rng)
        f.addRow("Tick count", sp_ticks)
        f.addRow("Decimals", sp_dec)
        f.addRow("Label size", sp_size)
        f.addRow("Shorten labels", cb_lscale)
        f.addRow("", chk_lsuffix)
        f.addRow("", chk_nice)
        f.addRow("", chk_sep)
        f.addRow("", chk_grid)

        setattr(self, f"{prefix}_title", ed_title)
        setattr(self, f"{prefix}_unit", ed_unit)
        setattr(self, f"{prefix}_scale", cb_scale)
        setattr(self, f"{prefix}_ticks", sp_ticks)
        setattr(self, f"{prefix}_nice", chk_nice)
        setattr(self, f"{prefix}_grid", chk_grid)
        setattr(self, f"{prefix}_dec", sp_dec)
        setattr(self, f"{prefix}_sep", chk_sep)
        setattr(self, f"{prefix}_range", rng)
        setattr(self, f"{prefix}_size", sp_size)
        setattr(self, f"{prefix}_tsize", sp_tsize)
        setattr(self, f"{prefix}_usize", sp_usize)
        setattr(self, f"{prefix}_lscale", cb_lscale)
        setattr(self, f"{prefix}_lsuffix", chk_lsuffix)
        g = group(title, f)
        if with_enable:
            g.setCheckable(True)
            g.setChecked(False)
            setattr(self, f"{prefix}_box", g)
        return g

    def _tab_axes(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._axis_block("X axis", "ax"))
        lay.addWidget(self._axis_block("Y axis (left)", "ay"))
        lay.addWidget(self._axis_block("Y axis (right)", "ay2", with_enable=True))
        lay.addWidget(hint("Ranges auto-populate from the data. Untick Auto to "
                           "pin a bound; the box is already pre-filled with the "
                           "detected value so you can nudge from there."))
        lay.addStretch(1)
        self._wire_all(w)
        return scroller(w)

    # =====================================================================
    # tab: style
    # =====================================================================
    def _tab_style(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        tf = form()
        self.ed_title = QLineEdit()
        self.ed_sub = QLineEdit()
        self.ed_cap = QLineEdit()
        self.sp_tsize = spin(8, 200, 46, 1, 1)
        self.sp_ssize = spin(6, 120, 22, 1, 1)
        self.sp_csize = spin(6, 120, 20, 1, 1)
        tf.addRow("Title", self.ed_title)
        tf.addRow("Subtitle", self.ed_sub)
        tf.addRow("Caption", self.ed_cap)
        tf.addRow("Title size", self.sp_tsize)
        tf.addRow("Subtitle size", self.sp_ssize)
        tf.addRow("Caption size", self.sp_csize)

        self.fc_font = QFontComboBox()
        self.fc_font.setEditable(True)
        self.fc_font.setSizeAdjustPolicy(QFontComboBox.AdjustToContentsOnFirstShow)
        self.ed_psname = QLineEdit()
        self.ed_psname.setPlaceholderText("optional exact PostScript name, e.g. Futura-Bold")
        tf.addRow("Font", self.fc_font)
        tf.addRow("PostScript name", self.ed_psname)

        lay.addWidget(group("Text", tf))

        cf = form()
        self.c_bg = ColorButton((0, 0, 0))
        self.c_grid = ColorButton((0.25, 0.25, 0.27))
        self.c_axis = ColorButton((0.75, 0.78, 0.82))
        self.c_title = ColorButton((0.95, 0.95, 0.95))
        self.c_sub = ColorButton((0.65, 0.65, 0.68))
        self.c_cap = ColorButton((0.6, 0.63, 0.67))
        self.sp_gridop = spin(0, 100, 45, 1, 0, " %")
        self.sp_gridw = spin(1, 20, 2, 1, 0, " px")
        for label, wdg in (("Background", self.c_bg), ("Gridlines", self.c_grid),
                           ("Axis text", self.c_axis), ("Title", self.c_title),
                           ("Subtitle", self.c_sub), ("Caption", self.c_cap)):
            cf.addRow(label, wdg)
        cf.addRow("Grid opacity", self.sp_gridop)
        cf.addRow("Grid weight", self.sp_gridw)
        lay.addWidget(group("Colours", cf))

        lf = form()
        self.chk_legend = QCheckBox("Show legend")
        self.chk_legend.setChecked(True)
        self.sp_lsize = spin(6, 80, 20, 1, 1)
        self.chk_playhead = QCheckBox("Playhead sweep line")
        self.chk_playhead.setChecked(True)
        self.sp_phop = spin(0, 100, 35, 1, 0, " %")
        self.chk_tip = QCheckBox("Leading tip dot")
        self.chk_tip.setChecked(True)
        self.sp_tipsize = spin(1, 200, 16, 1, 1)
        self.sp_dotop = spin(0, 100, 100, 1, 0, " %")
        self.sp_lead = spin(0, 50, 0.0, 0.1, 2)
        self.sp_lag = spin(0, 50, 0.0, 0.1, 2)
        self.ck_fromzero = QCheckBox("Start from an empty frame")
        self.ck_fromzero.setChecked(True)
        lf.addRow("", self.chk_legend)
        lf.addRow("Legend size", self.sp_lsize)
        lf.addRow("", self.chk_playhead)
        lf.addRow("Playhead opacity", self.sp_phop)
        lf.addRow("", self.chk_tip)
        lf.addRow("Tip size", self.sp_tipsize)
        lf.addRow("Dot opacity", self.sp_dotop)
        lf.addRow("", self.ck_fromzero)
        lf.addRow("Reveal lead", self.sp_lead)
        lf.addRow("Reveal lag", self.sp_lag)

        lay.addWidget(group("Chrome", lf))
        lay.addStretch(1)
        self._wire_all(w)
        return scroller(w)

    # =====================================================================
    # tab: comp + animation
    # =====================================================================
    def _tab_anim(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        cf = form()
        self.ed_comp = QLineEdit("DATA_CHART")
        self.sp_w = spin(16, 16384, 1920)
        self.sp_h = spin(16, 16384, 1080)
        self.sp_fps = spin(1, 240, 30, 1, 3)
        self.sp_dur = spin(0.1, 3600, 14, 0.5, 2, " s")
        self.chk_open = QCheckBox("Open comp in viewer after build")
        self.chk_open.setChecked(True)
        cf.addRow("Comp name", self.ed_comp)
        cf.addRow("Width", self.sp_w)
        cf.addRow("Height", self.sp_h)
        cf.addRow("Frame rate", self.sp_fps)
        cf.addRow("Duration", self.sp_dur)
        cf.addRow("", self.chk_open)
        lay.addWidget(group("Composition", cf))

        pf = form()
        self.sp_pl = spin(0, 16384, 220)
        self.sp_pr = spin(0, 16384, 1800)
        self.sp_pt = spin(0, 16384, 170)
        self.sp_pb = spin(0, 16384, 860)
        self.btn_fit = QPushButton("Fit plot to comp with margins")
        self.btn_fit.clicked.connect(self._fit_plot)
        pf.addRow("Left", self.sp_pl)
        pf.addRow("Right", self.sp_pr)
        pf.addRow("Top", self.sp_pt)
        pf.addRow("Bottom", self.sp_pb)
        pf.addRow("", self.btn_fit)
        lay.addWidget(group("Plot area (pixels)", pf))

        af = form()
        self.sp_pstart = spin(0, 3600, 1.0, 0.1, 2, " s")
        self.sp_pend = spin(0, 3600, 12.0, 0.1, 2, " s")
        self.sp_ease = spin(0, 100, 33, 1, 0, " %")
        self.cb_arc = combo([("chord", "Chord length (matches your scripts)"),
                             ("bezier", "True bezier arc length")], "chord")
        self.cb_arc.setToolTip(
            "How the ARC array is measured. Chord reproduces your existing "
            "scripts exactly. Bezier is a closer match to how AE's Trim Paths "
            "actually measures the curve, so the dots land more precisely on "
            "the leading edge when the curve is very wiggly.")
        self.sp_maxdots = spin(0, 20000, 400)
        self.sp_maxdots.setToolTip("0 draws every point. A 5000-row CSV would "
                                   "otherwise create 5000 layers.")
        self.chk_bind = QCheckBox("Wire everything to MASTER_CONTROLS")
        self.chk_bind.setChecked(True)
        self.chk_bind.setToolTip(
            "Adds Line Weight, Dot Scale, Dot Opacity, Reveal Softness, Grid "
            "Opacity, Labels Opacity, Tip Size and one colour control per "
            "series and category, then binds every layer to them.")
        af.addRow("Progress start", self.sp_pstart)
        af.addRow("Progress end", self.sp_pend)
        af.addRow("Keyframe ease", self.sp_ease)
        af.addRow("Arc measure", self.cb_arc)
        af.addRow("Max dot layers", self.sp_maxdots)
        af.addRow("", self.chk_bind)
        lay.addWidget(group("Animation", af))

        row = QHBoxLayout()
        self.btn_save = QPushButton("Save Script...")
        self.btn_copy = QPushButton("Copy Script")
        self.btn_save.clicked.connect(self.save_jsx)
        self.btn_copy.clicked.connect(self.copy_jsx)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_copy)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(hint("In After Effects: File > Scripts > Run Script File..."))
        lay.addStretch(1)
        self._wire_all(w)
        return scroller(w)

    # =====================================================================
    # signal wiring
    # =====================================================================
    def _wire_all(self, root: QWidget) -> None:
        for wdg in root.findChildren(QWidget):
            self._wire(wdg)

    def _wire(self, wdg: QWidget) -> None:
        if isinstance(wdg, QComboBox):
            wdg.currentIndexChanged.connect(self._schedule)
        elif isinstance(wdg, QCheckBox):
            wdg.toggled.connect(self._schedule)
        elif isinstance(wdg, QLineEdit):
            wdg.textChanged.connect(self._schedule)
        elif isinstance(wdg, ColorButton):
            wdg.colorChanged.connect(self._schedule)
        elif isinstance(wdg, AutoRange):
            wdg.changed.connect(self._schedule)
        elif hasattr(wdg, "valueChanged") and hasattr(wdg, "value"):
            try:
                wdg.valueChanged.connect(self._schedule)
            except Exception:
                pass
        elif isinstance(wdg, QGroupBox) and wdg.isCheckable():
            wdg.toggled.connect(self._schedule)

    def _schedule(self, *_) -> None:
        if self._loading:
            return
        self._timer.start()

    def _tab_switched(self, idx: int) -> None:
        if self._right.tabText(idx) == "Script" and self._script_dirty:
            self._render_script()

    # =====================================================================
    # spec <-> widgets
    # =====================================================================
    def _collect(self) -> None:
        s = self.spec
        s.chart_type = self.cb_type.currentData() or LINE
        s.x_column = self.cb_x.currentData() or ""
        s.sort_column = self.cb_sort.currentData() or ""
        s.sort_ascending = self.chk_sort_asc.isChecked()
        s.group_column = self.cb_group.currentData() or ""
        s.aggregation = self.cb_agg.currentData() or "sum"
        s.slice_sort = self.cb_slice_sort.currentData() or "value_desc"
        s.max_bars = int(self.sp_maxbars.value())
        s.lollipop_stem = float(self.sp_stem.value())
        s.lollipop_dot = float(self.sp_head.value())
        s.donut_radius_frac = float(self.sp_ring_r.value()) / 100.0
        s.donut_inner_frac = float(self.sp_ring_i.value()) / 100.0
        s.donut_gap_deg = float(self.sp_ring_gap.value())
        s.donut_show_labels = self.chk_dlabels.isChecked()
        s.donut_label_mode = self.cb_dlabel.currentData() or "name_percent"
        s.donut_label_place = self.cb_dplace.currentData() or "outside"
        s.donut_label_min_pct = float(self.sp_dminpct.value())
        s.arc_mode = self.cb_arc.currentData() or "chord"

        # axes
        for prefix, axis in (("ax", s.x_axis), ("ay", s.y_axis), ("ay2", s.y2_axis)):
            axis.title = getattr(self, f"{prefix}_title").text()
            axis.unit = getattr(self, f"{prefix}_unit").text()
            axis.scale = getattr(self, f"{prefix}_scale").currentData()
            axis.tick_count = int(getattr(self, f"{prefix}_ticks").value())
            axis.nice_ticks = getattr(self, f"{prefix}_nice").isChecked()
            axis.show_grid = getattr(self, f"{prefix}_grid").isChecked()
            axis.decimals = int(getattr(self, f"{prefix}_dec").value())
            axis.thousands_sep = getattr(self, f"{prefix}_sep").isChecked()
            axis.label_size = float(getattr(self, f"{prefix}_size").value())
            axis.title_size = float(getattr(self, f"{prefix}_tsize").value())
            axis.unit_size = float(getattr(self, f"{prefix}_usize").value())
            axis.label_scale = getattr(self, f"{prefix}_lscale").currentData() or SCALE_NONE
            axis.label_scale_suffix = getattr(self, f"{prefix}_lsuffix").isChecked()
            r: AutoRange = getattr(self, f"{prefix}_range")
            axis.auto_min = r.auto_min.isChecked()
            axis.auto_max = r.auto_max.isChecked()
            axis.vmin = float(r.vmin.value())
            axis.vmax = float(r.vmax.value())
        s.y2_axis.enabled = self.ay2_box.isChecked()

        # Encodings. The colour map is the authority and the swatch editors
        # write straight through to it (see _set_level_color), so it is copied
        # as-is here. Rebuilding it from whichever editor happens to be on
        # screen would let a stale one overwrite the other's colours.
        colors = dict(s.category.colors)
        s.category = CategorySpec(
            column=self.cb_cat.currentData() or "",
            enabled=self.chk_cat.isChecked() and bool(self.cb_cat.currentData()),
            colors=colors,
            show_legend=True)
        s.size.column = self.cb_size.currentData() or ""
        s.size.enabled = self.chk_size.isChecked() and bool(s.size.column)
        s.size.min_diameter = float(self.sp_dmin.value())
        s.size.max_diameter = float(self.sp_dmax.value())
        s.size.sqrt_scale = self.chk_sqrt.isChecked()

        # readout
        s.readout.enabled = self.chk_readout.isChecked() and bool(self.cb_readout.currentData())
        s.readout.column = self.cb_readout.currentData() or ""
        s.readout.prefix = self.ed_rpre.text()
        s.readout.suffix = self.ed_rsuf.text()
        s.readout.decimals = int(self.sp_rdec.value())
        s.readout.size = float(self.sp_rsize.value())
        s.readout.corner = self.cb_rcorner.currentData() or "top_right"

        # style
        st = s.style
        st.title = self.ed_title.text()
        st.subtitle = self.ed_sub.text()
        st.caption = self.ed_cap.text()
        st.title_size = float(self.sp_tsize.value())
        st.subtitle_size = float(self.sp_ssize.value())
        st.caption_size = float(self.sp_csize.value())
        # An explicit PostScript name wins; otherwise use the picked family and
        # let the generated setFont() walk the bold spellings.
        st.font_family = (self.ed_psname.text().strip()
                          or self.fc_font.currentFont().family().strip())
        st.bg_color = self.c_bg.rgb()
        st.grid_color = self.c_grid.rgb()
        st.axis_text_color = self.c_axis.rgb()
        st.title_color = self.c_title.rgb()
        st.subtitle_color = self.c_sub.rgb()
        st.caption_color = self.c_cap.rgb()
        st.grid_opacity = float(self.sp_gridop.value())
        st.grid_width = float(self.sp_gridw.value())
        st.show_legend = self.chk_legend.isChecked()
        st.legend_size = float(self.sp_lsize.value())
        st.show_playhead = self.chk_playhead.isChecked()
        st.playhead_opacity = float(self.sp_phop.value())
        st.show_tip_dot = self.chk_tip.isChecked()
        st.tip_dot_size = float(self.sp_tipsize.value())
        st.dot_opacity = float(self.sp_dotop.value())
        st.reveal_from_zero = self.ck_fromzero.isChecked()
        st.dot_reveal_lead = float(self.sp_lead.value())
        st.dot_reveal_lag = float(self.sp_lag.value())
        st.max_dot_layers = int(self.sp_maxdots.value())
        st.bind_to_controls = self.chk_bind.isChecked()

        # comp
        c = s.comp
        c.name = self.ed_comp.text() or "DATA_CHART"
        c.width = int(self.sp_w.value())
        c.height = int(self.sp_h.value())
        c.fps = float(self.sp_fps.value())
        c.duration = float(self.sp_dur.value())
        c.plot_left = float(self.sp_pl.value())
        c.plot_right = float(self.sp_pr.value())
        c.plot_top = float(self.sp_pt.value())
        c.plot_bottom = float(self.sp_pb.value())
        c.progress_start = float(self.sp_pstart.value())
        c.progress_end = float(self.sp_pend.value())
        c.ease_influence = float(self.sp_ease.value())
        c.open_in_viewer = self.chk_open.isChecked()

        self._commit_series_editor()

    def _apply(self) -> None:
        """Push self.spec into the widgets (used by presets and auto-config)."""
        self._loading = True
        try:
            s = self.spec
            i = self.cb_type.findData(s.chart_type)
            self.cb_type.setCurrentIndex(max(0, i))
            self._select(self.cb_x, s.x_column)
            self._select(self.cb_sort, s.sort_column)
            self.chk_sort_asc.setChecked(s.sort_ascending)
            self._select(self.cb_group, s.group_column)
            self._select(self.cb_agg, s.aggregation)
            self._select(self.cb_slice_sort, s.slice_sort)
            self.sp_maxbars.setValue(s.max_bars)
            self.sp_stem.setValue(s.lollipop_stem)
            self.sp_head.setValue(s.lollipop_dot)
            # both are integer spin boxes, and a converted legacy preset can
            # land slightly over the top of their range
            self.sp_ring_r.setValue(int(round(min(100.0, max(10.0,
                                    s.donut_radius_frac * 100.0)))))
            self.sp_ring_i.setValue(int(round(min(95.0, max(0.0,
                                    s.donut_inner_frac * 100.0)))))
            self.sp_ring_gap.setValue(s.donut_gap_deg)
            self.chk_dlabels.setChecked(s.donut_show_labels)
            self._select(self.cb_dlabel, s.donut_label_mode)
            self._select(self.cb_dplace, s.donut_label_place)
            self.sp_dminpct.setValue(s.donut_label_min_pct)
            self._select(self.cb_arc, s.arc_mode)

            for prefix, axis in (("ax", s.x_axis), ("ay", s.y_axis), ("ay2", s.y2_axis)):
                getattr(self, f"{prefix}_title").setText(axis.title)
                getattr(self, f"{prefix}_unit").setText(axis.unit)
                self._select(getattr(self, f"{prefix}_scale"), axis.scale)
                getattr(self, f"{prefix}_ticks").setValue(axis.tick_count)
                getattr(self, f"{prefix}_nice").setChecked(axis.nice_ticks)
                getattr(self, f"{prefix}_grid").setChecked(axis.show_grid)
                getattr(self, f"{prefix}_dec").setValue(axis.decimals)
                getattr(self, f"{prefix}_sep").setChecked(axis.thousands_sep)
                getattr(self, f"{prefix}_size").setValue(axis.label_size)
                getattr(self, f"{prefix}_tsize").setValue(axis.title_size)
                getattr(self, f"{prefix}_usize").setValue(axis.unit_size)
                self._select(getattr(self, f"{prefix}_lscale"), axis.label_scale)
                getattr(self, f"{prefix}_lsuffix").setChecked(axis.label_scale_suffix)
                getattr(self, f"{prefix}_range").set_values(
                    axis.auto_min, axis.vmin, axis.auto_max, axis.vmax)
            self.ay2_box.setChecked(s.y2_axis.enabled)

            self.chk_cat.setChecked(s.category.enabled)
            self._select(self.cb_cat, s.category.column)
            self.chk_size.setChecked(s.size.enabled)
            self._select(self.cb_size, s.size.column)
            self.sp_dmin.setValue(s.size.min_diameter)
            self.sp_dmax.setValue(s.size.max_diameter)
            self.chk_sqrt.setChecked(s.size.sqrt_scale)

            self.chk_readout.setChecked(s.readout.enabled)
            self._select(self.cb_readout, s.readout.column)
            self.ed_rpre.setText(s.readout.prefix)
            self.ed_rsuf.setText(s.readout.suffix)
            self.sp_rdec.setValue(s.readout.decimals)
            self.sp_rsize.setValue(s.readout.size)
            self._select(self.cb_rcorner, s.readout.corner)

            st = s.style
            self.ed_title.setText(st.title)
            self.ed_sub.setText(st.subtitle)
            self.ed_cap.setText(st.caption)
            self.sp_tsize.setValue(st.title_size)
            self.sp_ssize.setValue(st.subtitle_size)
            self.sp_csize.setValue(st.caption_size)
            if st.font_family:
                f = QFont(st.font_family)
                self.fc_font.setCurrentFont(f)
                if st.font_family != f.family():
                    self.ed_psname.setText(st.font_family)
            for btn, val in ((self.c_bg, st.bg_color), (self.c_grid, st.grid_color),
                             (self.c_axis, st.axis_text_color), (self.c_title, st.title_color),
                             (self.c_sub, st.subtitle_color), (self.c_cap, st.caption_color)):
                btn.set_rgb(val)
            self.sp_gridop.setValue(st.grid_opacity)
            self.sp_gridw.setValue(st.grid_width)
            self.chk_legend.setChecked(st.show_legend)
            self.sp_lsize.setValue(st.legend_size)
            self.chk_playhead.setChecked(st.show_playhead)
            self.sp_phop.setValue(st.playhead_opacity)
            self.chk_tip.setChecked(st.show_tip_dot)
            self.sp_tipsize.setValue(st.tip_dot_size)
            self.sp_dotop.setValue(st.dot_opacity)
            self.ck_fromzero.setChecked(st.reveal_from_zero)
            self.sp_lead.setValue(st.dot_reveal_lead)
            self.sp_lag.setValue(st.dot_reveal_lag)
            self.sp_maxdots.setValue(st.max_dot_layers)
            self.chk_bind.setChecked(st.bind_to_controls)

            c = s.comp
            self.ed_comp.setText(c.name)
            self.sp_w.setValue(c.width)
            self.sp_h.setValue(c.height)
            self.sp_fps.setValue(c.fps)
            self.sp_dur.setValue(c.duration)
            self.sp_pl.setValue(c.plot_left)
            self.sp_pr.setValue(c.plot_right)
            self.sp_pt.setValue(c.plot_top)
            self.sp_pb.setValue(c.plot_bottom)
            self.sp_pstart.setValue(c.progress_start)
            self.sp_pend.setValue(c.progress_end)
            self.sp_ease.setValue(c.ease_influence)
            self.chk_open.setChecked(c.open_in_viewer)

            self._refresh_series_list()
            self._rebuild_cat_colors()
            self._type_changed()
        finally:
            self._loading = False

    @staticmethod
    def _select(cb: QComboBox, value: str) -> None:
        i = cb.findData(value)
        cb.setCurrentIndex(i if i >= 0 else 0)

    # =====================================================================
    # series editor
    # =====================================================================
    def _refresh_series_list(self) -> None:
        row = self.series_list.currentRow()
        self.series_list.blockSignals(True)
        self.series_list.clear()
        for s in self.spec.series:
            self.series_list.addItem(f"{s.display_label()}  [{s.axis}]")
        self.series_list.blockSignals(False)
        if self.spec.series:
            self.series_list.setCurrentRow(min(max(0, row), len(self.spec.series) - 1))
            self._load_series_editor()

    def _current_series(self) -> Optional[SeriesSpec]:
        i = self.series_list.currentRow()
        if 0 <= i < len(self.spec.series):
            return self.spec.series[i]
        return None

    def _load_series_editor(self) -> None:
        s = self._current_series()
        if s is None:
            return
        prev = self._loading
        self._loading = True
        try:
            self._select(self.se_col, s.column)
            self.se_label.setText(s.label)
            self.se_color.set_rgb(s.color)
            self._select(self.se_axis, s.axis)
            self._select(self.se_transform, s.transform)
            self.se_window.setValue(s.window)
            self.se_stroke.setValue(s.stroke_width)
            self.se_fill.setValue(int(s.fill_opacity))
            self.se_dots.setChecked(s.show_dots)
            self.se_dotsize.setValue(s.dot_size)
            self.se_smooth.setChecked(s.smooth)
        finally:
            self._loading = prev

    def _commit_series_editor(self) -> None:
        s = self._current_series()
        if s is None:
            return
        s.column = self.se_col.currentData() or ""
        s.label = self.se_label.text()
        s.color = self.se_color.rgb()
        s.axis = self.se_axis.currentData() or "left"
        s.transform = self.se_transform.currentData() or "none"
        s.window = int(self.se_window.value())
        s.stroke_width = float(self.se_stroke.value())
        s.fill_opacity = float(self.se_fill.value())
        s.show_dots = self.se_dots.isChecked()
        s.dot_size = float(self.se_dotsize.value())
        s.smooth = self.se_smooth.isChecked()

    def _series_selected(self, _row: int) -> None:
        if not self._loading:
            self._load_series_editor()

    def _add_series(self) -> None:
        if self.ds is None:
            return
        nums = self.ds.numeric_names()
        used = {s.column for s in self.spec.series}
        pick = next((n for n in nums if n not in used), nums[0] if nums else "")
        self.spec.series.append(SeriesSpec(column=pick, label=pick,
                                           color=palette_color(len(self.spec.series))))
        self._refresh_series_list()
        self.series_list.setCurrentRow(len(self.spec.series) - 1)
        self._schedule()

    def _del_series(self) -> None:
        i = self.series_list.currentRow()
        if 0 <= i < len(self.spec.series) and len(self.spec.series) > 1:
            self.spec.series.pop(i)
            self._refresh_series_list()
            self._schedule()

    # =====================================================================
    # category colours
    # =====================================================================
    def _rebuild_cat_colors(self, *_) -> None:
        while self.cat_layout.count():
            item = self.cat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cat_buttons.clear()

        name = self.cb_cat.currentData() or ""
        if not (self.chk_cat.isChecked() and name and self.ds):
            return
        col = self.ds.col(name)
        if col is None or col.kind != CATEGORY:
            return
        existing = self.spec.category.colors
        for i, lev in enumerate(col.categories[:24]):
            btn = ColorButton(existing.get(lev, palette_color(i + 1)))
            btn.colorChanged.connect(
                lambda rgb, name=lev: self._set_level_color(name, rgb))
            self._cat_buttons[lev] = btn
            self.cat_layout.addWidget(QLabel(lev), i // 2, (i % 2) * 2)
            self.cat_layout.addWidget(btn, i // 2, (i % 2) * 2 + 1)
        if not self._loading:
            self._schedule()

    def _type_changed(self, *_) -> None:
        """Show only the panels the current chart type actually reads.

        Everything in GROUPED_TYPES aggregates rows into groups before drawing,
        so they all want the Group by / Aggregate controls -- not just the two
        plain bar charts.
        """
        t = self.cb_type.currentData()
        grouped = t in GROUPED_TYPES
        self.grp_bar.setVisible(grouped)
        self.grp_slice_colors.setVisible(t in PER_GROUP_COLOR)
        self.grp_lolli.setVisible(t == LOLLIPOP)
        self.grp_donut.setVisible(t == DONUT)
        self.lbl_maxbars.setText("Max slices" if t == DONUT else "Max groups")
        # a donut has no axes to sort against; its order is the slice order
        self.cb_sort.setEnabled(not grouped)
        self.chk_sort_asc.setEnabled(not grouped)
        if self._loading:
            return
        # Switching to a grouped chart with nothing to group by would put one
        # slice on every row, so fall to the first category column instead.
        if grouped and not self.cb_group.currentData() and self.ds is not None:
            cats = self.ds.category_names()
            if cats:
                self.cb_group.blockSignals(True)
                self._select(self.cb_group, cats[0])
                self.cb_group.blockSignals(False)
        self._schedule()

    def _set_level_color(self, level: str, rgb) -> None:
        """Record a colour picked for one category level or group.

        Both swatch editors can be showing the same level at once, and either
        can be holding values from a chart type that is no longer on screen.
        So the pick goes straight into the spec, which is what the build reads,
        and the twin swatch is nudged to match rather than left to disagree.
        """
        rgb = tuple(rgb)
        self.spec.category.colors[level] = rgb
        for holder in (self._cat_buttons, self._slice_buttons):
            btn = holder.get(level)
            if btn is not None and btn.rgb() != rgb:
                btn.blockSignals(True)
                btn.set_rgb(rgb)
                btn.blockSignals(False)
        self._schedule()

    # -- per-group colour swatches ---------------------------------------
    def _sync_slice_colors(self) -> None:
        """Rebuild the group swatches from the model that was just built.

        Taking the labels from the model rather than from the raw column means
        the list matches what is on screen exactly, including the merged
        'Other' slice, and it picks up the aggregation and top-N cut for free.
        """
        t = self.cb_type.currentData()
        m = self.model
        labels: List[str] = []
        seed: Dict[str, tuple] = {}
        if t in PER_GROUP_COLOR and m is not None and m.ok:
            source = m.segments if t == DONUT else m.bars
            for item in source:
                if item.label not in seed:
                    labels.append(item.label)
                    seed[item.label] = tuple(item.color)
        if labels == self._slice_levels:
            return                                  # nothing moved, leave the widgets alone
        self._slice_levels = labels

        while self.slice_layout.count():
            item = self.slice_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._slice_buttons.clear()
        if not labels:
            return
        existing = self.spec.category.colors
        for i, lev in enumerate(labels[:40]):
            btn = ColorButton(existing.get(lev, seed[lev]))
            btn.colorChanged.connect(
                lambda rgb, name=lev: self._set_level_color(name, rgb))
            self._slice_buttons[lev] = btn
            self.slice_layout.addWidget(QLabel(lev), i // 2, (i % 2) * 2)
            self.slice_layout.addWidget(btn, i // 2, (i % 2) * 2 + 1)

    def _fit_plot(self) -> None:
        w, h = int(self.sp_w.value()), int(self.sp_h.value())
        self.sp_pl.setValue(int(w * 0.115))
        self.sp_pr.setValue(int(w * 0.9375))
        self.sp_pt.setValue(int(h * 0.157))
        self.sp_pb.setValue(int(h * 0.796))
        self._schedule()

    # =====================================================================
    # drag and drop
    # =====================================================================
    @staticmethod
    def _classify_drop(event) -> Tuple[Optional[str], Optional[str]]:
        """Split a drop into (data file, preset file), either may be None.

        Only local files count, and only the first of each kind: dropping a
        folder or a bundle of ten CSVs should not silently pick one at random
        beyond the obvious first-wins rule.
        """
        mime = event.mimeData()
        if not mime.hasUrls():
            return None, None
        data = preset = None
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext in DATA_SUFFIXES and data is None:
                data = path
            elif ext in PRESET_SUFFIXES and preset is None:
                preset = path
        return data, preset

    def dragEnterEvent(self, event) -> None:
        data, preset = self._classify_drop(event)
        if data is None and preset is None:
            event.ignore()
            return
        if data and preset:
            text = "Drop to load the data and apply the preset"
        elif data:
            text = f"Drop to load {os.path.basename(data)}"
        else:
            text = f"Drop to apply {os.path.basename(preset)}"
        self._show_drop_hint(text)
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        # Qt only keeps the drop target alive while move events are accepted.
        if self._drop_hint.isVisible():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._drop_hint.hide()
        event.accept()

    def dropEvent(self, event) -> None:
        self._drop_hint.hide()
        data, preset = self._classify_drop(event)
        if data is None and preset is None:
            event.ignore()
            return
        event.acceptProposedAction()
        # Data first: a preset dropped alongside it describes the new columns,
        # so applying it afterwards is the order that leaves both in effect.
        if data:
            # An explicit drop of a preset says what the mapping should be, so
            # do not spend effort auto-configuring one that is about to be
            # replaced.
            if not self.load_csv(data, keep_spec=True if preset else None):
                return
        if preset:
            self.load_preset_file(preset)

    def _show_drop_hint(self, text: str) -> None:
        self._drop_hint.setText(text)
        self._drop_hint.setGeometry(self.rect())
        self._drop_hint.raise_()
        self._drop_hint.show()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # __init__ resizes the window before _build_ui has made the overlay
        hint_widget = getattr(self, "_drop_hint", None)
        if hint_widget is not None and hint_widget.isVisible():
            hint_widget.setGeometry(self.rect())

    # =====================================================================
    # actions
    # =====================================================================
    def open_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open CSV", "", "Data files (*.csv *.tsv *.txt);;All files (*)")
        if path:
            self.load_csv(path)

    def load_csv(self, path: str, keep_spec: Optional[bool] = None) -> bool:
        """Load a data file and rebuild the interface around it.

        The Open button, the command line and a dropped file all come through
        here, so the three routes cannot drift apart.

        When the incoming file carries the same columns as the one it replaces
        the current mapping still describes it, so the chart is kept rather
        than thrown away -- which is what refreshing a dataset in place wants.
        Anything else auto-configures from scratch. Pass keep_spec to force
        either behaviour.
        """
        try:
            ds = Dataset.from_csv(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not read CSV", str(exc))
            return False
        if keep_spec is None:
            keep_spec = self.ds is not None and self.ds.names == ds.names
        self.ds = ds
        self.lbl_path.setText(f"{path}\n{ds.n_rows} rows, {len(ds.columns)} columns")
        self.btn_auto.setEnabled(True)
        self._populate_columns()
        self._fill_table()
        if keep_spec:
            self._apply()
            self._refresh()
            self.statusBar().showMessage(
                f"Reloaded {os.path.basename(path)}: {ds.n_rows} rows, "
                "same columns, chart kept.")
        else:
            self.auto_configure()
        self.tabs.setCurrentIndex(1)
        return True

    def _populate_columns(self) -> None:
        ds = self.ds
        self.col_list.clear()
        for c in ds.columns:
            it = QListWidgetItem(f"{c.name}\n    {c.kind}  ·  {c.summary()}")
            self.col_list.addItem(it)

        self._loading = True
        plott = ds.plottable_names()
        nums = ds.numeric_names()
        cats = ds.category_names()
        fill_columns(self.cb_x, plott or ds.names)
        fill_columns(self.cb_sort, plott, allow_blank=True, blank_text="(CSV row order)")
        fill_columns(self.cb_group, cats + ds.names, allow_blank=True)
        fill_columns(self.cb_cat, cats, allow_blank=True)
        fill_columns(self.cb_size, nums, allow_blank=True)
        fill_columns(self.cb_readout, plott, allow_blank=True)
        fill_columns(self.se_col, nums or ds.names)
        self._loading = False

    def _fill_table(self) -> None:
        ds = self.ds
        rows = min(ds.n_rows, 300)
        self.table.setColumnCount(len(ds.columns))
        self.table.setRowCount(rows)
        self.table.setHorizontalHeaderLabels(
            [f"{c.name}\n({c.kind})" for c in ds.columns])
        for r in range(rows):
            for ci, c in enumerate(ds.columns):
                self.table.setItem(r, ci, QTableWidgetItem(c.raw[r]))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

    def auto_configure(self) -> None:
        """Pick a sensible starting chart from the column types."""
        ds = self.ds
        if ds is None:
            return
        dates = [c.name for c in ds.columns if c.kind == DATE]
        nums = ds.numeric_names()
        cats = [c for c in ds.columns if c.kind == CATEGORY and 2 <= len(c.categories) <= 10]

        spec = ChartSpec()
        spec.x_column = dates[0] if dates else (nums[0] if nums else ds.names[0])
        spec.sort_column = spec.x_column
        ycands = [n for n in nums if n != spec.x_column]
        spec.series = [SeriesSpec(column=ycands[0] if ycands else (nums[0] if nums else ""),
                                  label=ycands[0] if ycands else "",
                                  color=palette_color(0))]
        spec.chart_type = LINE
        spec.x_axis.title = (dates[0] if dates else spec.x_column).replace("_", " ").upper()
        spec.y_axis.title = spec.series[0].display_label().replace("_", " ").upper()
        if cats:
            spec.category = CategorySpec(
                column=cats[0].name, enabled=True,
                colors={lev: palette_color(i + 1) for i, lev in enumerate(cats[0].categories)})
        spec.style.title = os.path.splitext(os.path.basename(ds.path or "DATA"))[0].upper()
        spec.style.subtitle = spec.y_axis.title
        spec.comp.name = "".join(ch if ch.isalnum() else "_"
                                 for ch in spec.style.title)[:28] or "DATA_CHART"
        self.spec = spec
        self._apply()
        self._refresh()
        self._suggest_ranges()
        self.statusBar().showMessage(
            f"Auto-configured: {spec.chart_type} of {spec.series[0].column} vs {spec.x_column}")

    def _suggest_ranges(self) -> None:
        """Pre-fill the manual min/max boxes with what auto resolved to."""
        m = self.model
        if m is None or not m.ok:
            return
        if m.x_scale:
            self.ax_range.suggest(m.x_scale.vmin, m.x_scale.vmax)
        if m.y_scale:
            self.ay_range.suggest(m.y_scale.vmin, m.y_scale.vmax)
        if m.y2_scale:
            self.ay2_range.suggest(m.y2_scale.vmin, m.y2_scale.vmax)

    # =====================================================================
    # refresh
    # =====================================================================
    def _refresh(self) -> None:
        if self.ds is None:
            return
        try:
            self._collect()
            self.model = build_model(self.ds, self.spec)
        except Exception:
            self.statusBar().showMessage("Build error, see console.")
            traceback.print_exc()
            return
        self.preview.set_model(self.model)
        self._refresh_series_list()
        self._sync_slice_colors()
        self._suggest_ranges()
        self._script_dirty = True
        if self._right.tabText(self._right.currentIndex()) == "Script":
            self._render_script()

        m = self.model
        if not m.ok:
            self.statusBar().showMessage(m.error)
        else:
            msg = f"{m.n_points} points · {len(m.series)} series"
            if m.bars:
                msg = f"{len(m.bars)} bars"
            if m.warnings:
                msg += "  ·  " + "; ".join(m.warnings[:2])
            self.statusBar().showMessage(msg)

    def _render_script(self) -> None:
        if self.model is None or not self.model.ok:
            self.script.setPlainText("// " + (self.model.error if self.model
                                              else "Nothing to build yet."))
            return
        try:
            self.script.setPlainText(generate_jsx(self.model))
            self._script_dirty = False
        except Exception as exc:
            self.script.setPlainText(f"// Generator error: {exc}")
            traceback.print_exc()

    def _jsx(self) -> Optional[str]:
        if self.model is None or not self.model.ok:
            QMessageBox.warning(self, APP_NAME,
                                self.model.error if self.model else "Load a CSV first.")
            return None
        try:
            return generate_jsx(self.model)
        except Exception as exc:
            QMessageBox.critical(self, "Generator error", str(exc))
            return None

    def save_jsx(self) -> None:
        js = self._jsx()
        if js is None:
            return
        default = (self.spec.comp.name or "chart") + ".jsx"
        path, _ = QFileDialog.getSaveFileName(self, "Save script", default,
                                              "ExtendScript (*.jsx)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js)
        self.statusBar().showMessage(f"Saved {path}")

    def copy_jsx(self) -> None:
        js = self._jsx()
        if js is None:
            return
        QGuiApplication.clipboard().setText(js)
        self.statusBar().showMessage("Script copied to clipboard.")

    def save_preset(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save preset",
                                              "chart_preset.json", "JSON (*.json)")
        if not path:
            return
        self._collect()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.spec.to_json())
        self.statusBar().showMessage(f"Preset saved to {path}")

    def load_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load preset", "", "JSON (*.json)")
        if path:
            self.load_preset_file(path)

    def load_preset_file(self, path: str) -> bool:
        """Apply a saved spec. Shared by the menu and by dropped .json files."""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                self.spec = ChartSpec.from_json(fh.read())
        except Exception as exc:
            QMessageBox.critical(self, "Could not load preset", str(exc))
            return False
        self._apply()
        self._refresh()
        msg = f"Loaded preset {os.path.basename(path)}"
        if self.ds is None:
            msg += ". Open a CSV to draw it."
        self.statusBar().showMessage(msg)
        return True

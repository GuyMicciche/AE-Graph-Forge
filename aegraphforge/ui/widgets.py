"""
widgets.py -- small reusable controls so the panels stay declarative.
"""

from __future__ import annotations

from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QStyle,
                               QDoubleSpinBox, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QVBoxLayout, QWidget)

RGB = Tuple[float, float, float]


def to_rgb(c: QColor) -> RGB:
    return (c.redF(), c.greenF(), c.blueF())


def to_qcolor(rgb: Sequence[float]) -> QColor:
    return QColor.fromRgbF(*(max(0.0, min(1.0, float(v))) for v in rgb[:3]))


class ColorButton(QPushButton):
    """A swatch button that opens the colour dialog."""

    colorChanged = Signal(tuple)

    def __init__(self, rgb: Sequence[float] = (1, 1, 1), parent=None):
        super().__init__(parent)
        self._rgb: RGB = tuple(rgb[:3])
        self.setFixedSize(54, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._refresh()

    def rgb(self) -> RGB:
        return self._rgb

    def set_rgb(self, rgb: Sequence[float]) -> None:
        self._rgb = tuple(float(v) for v in rgb[:3])
        self._refresh()

    def _refresh(self) -> None:
        pm = QPixmap(46, 16)
        pm.fill(to_qcolor(self._rgb))
        p = QPainter(pm)
        p.setPen(QColor(0, 0, 0, 110))
        p.drawRect(0, 0, 45, 15)
        p.end()
        self.setIcon(QIcon(pm))
        self.setToolTip("RGB " + ", ".join(f"{v:.2f}" for v in self._rgb))

    def _pick(self) -> None:
        c = QColorDialog.getColor(to_qcolor(self._rgb), self, "Pick colour")
        if c.isValid():
            self.set_rgb(to_rgb(c))
            self.colorChanged.emit(self._rgb)


class AutoRange(QWidget):
    """min/max pair with an Auto checkbox each, populated from the data."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.auto_min = QCheckBox("Auto")
        self.auto_max = QCheckBox("Auto")
        self.auto_min.setChecked(True)
        self.auto_max.setChecked(True)
        self.vmin = QDoubleSpinBox()
        self.vmax = QDoubleSpinBox()
        for sb in (self.vmin, self.vmax):
            sb.setRange(-1e12, 1e12)
            sb.setDecimals(4)
            sb.setSingleStep(1.0)
            sb.setEnabled(False)
            sb.setMinimumWidth(90)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(QLabel("min"))
        lay.addWidget(self.vmin, 1)
        lay.addWidget(self.auto_min)
        lay.addSpacing(8)
        lay.addWidget(QLabel("max"))
        lay.addWidget(self.vmax, 1)
        lay.addWidget(self.auto_max)

        self.auto_min.toggled.connect(lambda on: (self.vmin.setEnabled(not on), self.changed.emit()))
        self.auto_max.toggled.connect(lambda on: (self.vmax.setEnabled(not on), self.changed.emit()))
        self.vmin.valueChanged.connect(lambda _: self.changed.emit())
        self.vmax.valueChanged.connect(lambda _: self.changed.emit())

    def set_values(self, auto_min: bool, vmin: float, auto_max: bool, vmax: float) -> None:
        for w in (self.auto_min, self.auto_max, self.vmin, self.vmax):
            w.blockSignals(True)
        self.auto_min.setChecked(auto_min)
        self.auto_max.setChecked(auto_max)
        self.vmin.setValue(float(vmin))
        self.vmax.setValue(float(vmax))
        self.vmin.setEnabled(not auto_min)
        self.vmax.setEnabled(not auto_max)
        for w in (self.auto_min, self.auto_max, self.vmin, self.vmax):
            w.blockSignals(False)

    def suggest(self, lo: float, vhi: float) -> None:
        """Fill the boxes with data-derived values without switching off Auto,
        so the numbers are already sensible the moment Auto is unticked."""
        if self.auto_min:
            self.vmin.blockSignals(True)
            self.vmin.setValue(float(lo))
            self.vmin.blockSignals(False)
        if self.auto_max:
            self.vmax.blockSignals(True)
            self.vmax.setValue(float(vhi))
            self.vmax.blockSignals(False)


def spin(lo: float, hi: float, val: float, step: float = 1.0,
         decimals: int = 0, suffix: str = "") -> QWidget:
    if decimals <= 0:
        w = QSpinBox()
        w.setRange(int(lo), int(hi))
        w.setValue(int(val))
        w.setSingleStep(int(max(1, step)))
    else:
        w = QDoubleSpinBox()
        w.setRange(lo, hi)
        w.setValue(val)
        w.setDecimals(decimals)
        w.setSingleStep(step)
    if suffix:
        w.setSuffix(suffix)
    w.setMinimumWidth(80)
    return w


class WideComboBox(QComboBox):
    """A combo whose popup is sized to its longest entry.

    The default popup inherits the (often narrow) width of the closed control,
    so long column names get elided and you cannot tell two similar ones apart
    while choosing. This measures every item and widens the popup to fit,
    leaving the closed control free to stay compact in the form layout.
    """

    def showPopup(self) -> None:
        fm = self.fontMetrics()
        widest = 0
        for i in range(self.count()):
            widest = max(widest, fm.horizontalAdvance(self.itemText(i)))
        view = self.view()
        # room for the frame, the scrollbar, and a little breathing space
        extra = self.style().pixelMetric(QStyle.PM_ScrollBarExtent) + 24
        view.setMinimumWidth(max(self.width(), widest + extra))
        super().showPopup()


def combo(items: Iterable[Tuple[str, str]], current: str = "") -> QComboBox:
    c = WideComboBox()
    for key, label in items:
        c.addItem(label, key)
    if current:
        i = c.findData(current)
        if i >= 0:
            c.setCurrentIndex(i)
    return c


def fill_columns(c: QComboBox, names: Sequence[str], current: str = "",
                 allow_blank: bool = False, blank_text: str = "(none)") -> None:
    c.blockSignals(True)
    c.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
    prev = current or c.currentData()
    c.clear()
    if allow_blank:
        c.addItem(blank_text, "")
    for n in names:
        c.addItem(n, n)
    i = c.findData(prev)
    c.setCurrentIndex(i if i >= 0 else 0)
    # Keep the closed control readable too, without letting one very long
    # column name stretch the whole form.
    fm = c.fontMetrics()
    widest = max([fm.horizontalAdvance(c.itemText(j)) for j in range(c.count())] or [0])
    c.setMinimumWidth(min(360, max(150, widest + 44)))
    c.blockSignals(False)


def group(title: str, form: QFormLayout) -> QGroupBox:
    g = QGroupBox(title)
    g.setLayout(form)
    return g


def form() -> QFormLayout:
    f = QFormLayout()
    f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    f.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    f.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    f.setHorizontalSpacing(10)
    f.setVerticalSpacing(6)
    return f


def scroller(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidget(inner)
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    return sa


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


def hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet("color: #8b909b; font-size: 11px;")
    return lab

"""
preview.py -- WYSIWYG chart preview.

The canvas paints the *same* RenderModel the JSX generator serialises, in the
same composition pixel space, then applies a single uniform transform to fit
the widget. It reimplements the reveal maths from the generated expressions
(trim by arc fraction, dots by index-linear reveal) rather than approximating
it, so scrubbing the preview slider shows what AE will show.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PySide6.QtCore import QTimer, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QPainter,
                           QPainterPath, QPen, QTransform)
from PySide6.QtWidgets import (QCheckBox, QPushButton, QHBoxLayout, QLabel, QSlider,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..core.build import RenderModel
from ..core.geometry import PathGeometry
from ..core.spec import AREA, BAR, CONNECTED_SCATTER, HBAR, SCATTER


def qc(rgb, alpha: float = 1.0) -> QColor:
    c = QColor.fromRgbF(
        max(0.0, min(1.0, float(rgb[0]))),
        max(0.0, min(1.0, float(rgb[1]))),
        max(0.0, min(1.0, float(rgb[2]))),
    )
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _ease(u: float) -> float:
    """Smoothstep, standing in for the easy-ease keyframe interpolation."""
    u = min(max(u, 0.0), 1.0)
    return u * u * (3.0 - 2.0 * u)


def progress_at_time(t: float, comp) -> float:
    """Progress the generated slider holds at composition time `t`."""
    a, b = comp.progress_start, comp.progress_end
    if t <= a:
        return 0.0
    if t >= b or b <= a:
        return 100.0
    return _ease((t - a) / (b - a)) * 100.0


def time_at_progress(pct: float, comp) -> float:
    """Inverse of progress_at_time, for keeping the scrubber and clock aligned."""
    a, b = comp.progress_start, comp.progress_end
    if pct <= 0.0 or b <= a:
        return a
    if pct >= 100.0:
        return b
    lo, hi = 0.0, 1.0                       # smoothstep has no tidy inverse
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if _ease(mid) * 100.0 < pct:
            lo = mid
        else:
            hi = mid
    return a + (lo + hi) / 2.0 * (b - a)


class ChartCanvas(QWidget):
    """Paints a RenderModel at a given progress value."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model: Optional[RenderModel] = None
        self.progress: float = 100.0
        self.show_guides: bool = True
        self.setMinimumSize(480, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_model(self, model: Optional[RenderModel]) -> None:
        self.model = model
        self.update()

    def set_progress(self, value: float) -> None:
        self.progress = float(value)
        self.update()

    # -- painting --------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        m = self.model
        if m is None:
            self._placeholder(p, "Load a CSV and choose columns to see a preview.")
            return
        if not m.ok:
            self._placeholder(p, m.error or "Chart is not configured yet.", error=True)
            return

        comp = m.spec.comp
        cw, ch = float(comp.width), float(comp.height)
        avail_w, avail_h = self.width() - 16.0, self.height() - 16.0
        scale = min(avail_w / cw, avail_h / ch)
        ox = (self.width() - cw * scale) / 2.0
        oy = (self.height() - ch * scale) / 2.0

        p.save()
        p.translate(ox, oy)
        p.scale(scale, scale)
        p.setClipRect(QRectF(0, 0, cw, ch))

        st = m.spec.style
        p.fillRect(QRectF(0, 0, cw, ch), qc(st.bg_color))

        self._grid(p, m)
        if m.spec.is_bar:
            self._bars(p, m)
        else:
            self._series(p, m)
            self._playhead(p, m)
        self._labels(p, m)
        self._titles(p, m)
        self._legend(p, m)
        self._readout(p, m)
        if self.show_guides:
            self._guides(p, m)
        p.restore()

        self._badge(p, f"{self.progress:.0f}%")

    # -- pieces ----------------------------------------------------------
    def _placeholder(self, p: QPainter, text: str, error: bool = False) -> None:
        p.fillRect(self.rect(), QColor(22, 22, 26))
        p.setPen(QColor(220, 110, 110) if error else QColor(130, 135, 145))
        f = QFont()
        f.setPointSizeF(10.5)
        p.setFont(f)
        p.drawText(self.rect().adjusted(24, 24, -24, -24),
                   Qt.AlignCenter | Qt.TextWordWrap, text)

    def _badge(self, p: QPainter, text: str) -> None:
        f = QFont()
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetricsF(f)
        w = fm.horizontalAdvance(text) + 14
        r = QRectF(self.width() - w - 10, 10, w, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(r, 4, 4)
        p.setPen(QColor(225, 228, 235))
        p.drawText(r, Qt.AlignCenter, text)

    def _grid(self, p: QPainter, m: RenderModel) -> None:
        st = m.spec.style
        L, T, R, B = m.plot_rect
        pen = QPen(qc(st.grid_color, st.grid_opacity / 100.0))
        pen.setWidthF(max(1.0, st.grid_width))
        p.setPen(pen)
        if m.spec.y_axis.show_grid:
            for t in m.y_ticks:
                if m.spec.is_bar and m.spec.chart_type == HBAR:
                    continue
                p.drawLine(QPointF(L, t.pixel), QPointF(R, t.pixel))
        vertical_grid = m.spec.chart_type in (SCATTER, CONNECTED_SCATTER, HBAR)
        if m.spec.x_axis.show_grid and vertical_grid:
            for t in m.x_ticks:
                p.drawLine(QPointF(t.pixel, T), QPointF(t.pixel, B))

    def _qpath(self, g: PathGeometry) -> QPainterPath:
        path = QPainterPath()
        pts, ins, outs = g.points, g.in_tangents, g.out_tangents
        path.moveTo(*pts[0])
        for i in range(len(pts) - 1):
            c1 = (pts[i][0] + outs[i][0], pts[i][1] + outs[i][1])
            c2 = (pts[i + 1][0] + ins[i + 1][0], pts[i + 1][1] + ins[i + 1][1])
            path.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(*pts[i + 1]))
        return path

    def _trimmed(self, path: QPainterPath, frac: float) -> QPainterPath:
        """Mirror of AE's Trim Paths End, using Qt's own arc-length param."""
        frac = max(0.0, min(1.0, frac))
        if frac >= 0.999:
            return path
        if frac <= 0.0:
            return QPainterPath()
        out = QPainterPath()
        steps = 400
        out.moveTo(path.pointAtPercent(0.0))
        for i in range(1, steps + 1):
            out.lineTo(path.pointAtPercent(frac * i / steps))
        return out

    def _series(self, p: QPainter, m: RenderModel) -> None:
        st = m.spec.style
        prog = self.progress
        for sm in m.series:
            g = sm.path
            if g is not None and sm.spec.show_line and m.spec.chart_type != SCATTER:
                qp = self._qpath(g)
                frac = g.trim_at_progress(prog) / 100.0

                # area fill, wiped to the leading edge like the Linear Wipe does
                if m.spec.chart_type == AREA or sm.spec.fill_opacity > 0:
                    tip = g.point_at_progress(prog)
                    fill = QPainterPath(self._trimmed(qp, frac))
                    if fill.elementCount() > 1:
                        fill.lineTo(QPointF(tip[0], sm.baseline_pixel))
                        fill.lineTo(QPointF(g.points[0][0], sm.baseline_pixel))
                        fill.closeSubpath()
                        op = (sm.spec.fill_opacity or 28.0) / 100.0
                        p.setPen(Qt.NoPen)
                        p.setBrush(qc(sm.color, op))
                        p.drawPath(fill)

                pen = QPen(qc(sm.color))
                pen.setWidthF(sm.spec.stroke_width)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPath(self._trimmed(qp, frac))

            # dots
            p.setPen(Qt.NoPen)
            # Mirrors the dot Opacity expression in jsxgen._emit_dots.
            soft = st.dot_reveal_lead
            for d in sm.dots:
                lo = max(0.0, d.reveal_at - soft)
                hi = max(lo + 0.001, d.reveal_at + d.reveal_span + soft * 0.33)
                a = self._ramp(prog, lo, hi)
                if a <= 0.001:
                    continue
                p.setBrush(qc(d.color, a * st.dot_opacity / 100.0))
                r = d.diameter / 2.0
                p.drawEllipse(QPointF(d.x, d.y), r, r)

    @staticmethod
    def _ramp(v: float, lo: float, hi: float) -> float:
        if hi <= lo:
            return 1.0 if v >= hi else 0.0
        return max(0.0, min(1.0, (v - lo) / (hi - lo)))

    def _playhead(self, p: QPainter, m: RenderModel) -> None:
        st = m.spec.style
        paths = [sm for sm in m.series if sm.path is not None]
        if not paths or m.spec.chart_type == SCATTER:
            return
        lead = paths[0]
        L, T, R, B = m.plot_rect
        prog = self.progress
        fade = self._ramp(prog, 0, 2) * (1.0 if prog < 99.5 else self._ramp(100 - prog, 0, 0.5))
        if fade <= 0.001:
            return
        tip = lead.path.point_at_progress(prog)
        if st.show_playhead:
            pen = QPen(qc((0.95, 0.95, 0.95), fade * st.playhead_opacity / 100.0))
            pen.setWidthF(2)
            p.setPen(pen)
            p.drawLine(QPointF(tip[0], T), QPointF(tip[0], B))
        if st.show_tip_dot:
            p.setPen(Qt.NoPen)
            p.setBrush(qc(lead.color, fade))
            r = st.tip_dot_size / 2.0
            p.drawEllipse(QPointF(tip[0], tip[1]), r, r)

    def _bars(self, p: QPainter, m: RenderModel) -> None:
        horiz = m.spec.chart_type == HBAR
        prog = self.progress
        # Mirrors the bar Scale expression in jsxgen._bars.
        soft = m.spec.style.dot_reveal_lead
        p.setPen(Qt.NoPen)
        for b in m.bars:
            lo = max(0.0, b.reveal_at - b.reveal_span - soft)
            t = self._ramp(prog, lo, max(lo + 0.001, b.reveal_at))
            t = t * t * (3 - 2 * t)                      # ease(), roughly
            if t <= 0.001:
                continue
            if horiz:
                w = b.width * t
                x = b.base if b.x >= b.base else b.base - w
                rect = QRectF(min(x, b.base), b.y - b.height / 2, w, b.height)
            else:
                h = b.height * t
                y = b.base - h if b.y < b.base else b.base
                rect = QRectF(b.x - b.width / 2, y, b.width, h)
            p.setBrush(qc(b.color))
            p.drawRect(rect)

            llo = max(0.0, b.reveal_at - b.reveal_span)
            la = self._ramp(prog, llo, max(llo + 0.001, b.reveal_at))
            if la > 0.01:
                self._text(p, b.value_label or b.label, 20,
                           qc(m.spec.style.axis_text_color, la),
                           (rect.right() + 16, rect.center().y() + 7) if horiz
                           else (rect.center().x(), rect.top() - 16),
                           "left" if horiz else "center")

    def _text(self, p: QPainter, s: str, size: float, color: QColor,
              pos: Tuple[float, float], align: str = "left",
              bold: bool = True, rotation: float = 0.0) -> None:
        f = QFont(self._family())
        f.setPixelSize(max(1, int(round(size))))
        f.setBold(bold)
        p.setFont(f)
        p.setPen(color)
        fm = QFontMetricsF(f)
        w = fm.horizontalAdvance(s)
        p.save()
        p.translate(pos[0], pos[1])
        if rotation:
            p.rotate(rotation)
        dx = 0.0 if align == "left" else (-w if align == "right" else -w / 2.0)
        p.drawText(QPointF(dx, 0), s)
        p.restore()

    @staticmethod
    def _family() -> str:
        return "Arial"

    def _labels(self, p: QPainter, m: RenderModel) -> None:
        st = m.spec.style
        L, T, R, B = m.plot_rect
        col = qc(st.axis_text_color)
        for t in m.y_ticks:
            self._text(p, t.label, m.spec.y_axis.label_size, col, (L - 20, t.pixel + 8), "right")
        for t in m.y2_ticks:
            self._text(p, t.label, m.spec.y2_axis.label_size, col, (R + 20, t.pixel + 8), "left")
        rot = -38 if (m.spec.chart_type == BAR
                      and any(len(t.label) > 6 for t in m.x_ticks)) else 0
        for t in m.x_ticks:
            self._text(p, t.label, m.spec.x_axis.label_size, col,
                       (t.pixel, B + 45), "right" if rot else "center", rotation=rot)
        # On a horizontal bar chart the VALUE axis runs along the bottom, so the
        # y-axis title (which is what the user configures as the value axis)
        # belongs there rather than rotated up the left-hand side.
        bottom_title = (m.spec.y_axis.title if m.spec.chart_type == HBAR
                        else m.spec.x_axis.title)
        side_title = "" if m.spec.chart_type == HBAR else m.spec.y_axis.title
        if bottom_title:
            self._text(p, bottom_title, 22, col, ((L + R) / 2, B + 95), "center")
        if side_title:
            self._text(p, side_title, 22, col, (L - 95, (T + B) / 2), "center",
                       rotation=-90)
        if m.y2_ticks and m.spec.y2_axis.title:
            self._text(p, m.spec.y2_axis.title, 22, col, (R + 95, (T + B) / 2), "center",
                       rotation=90)
        if m.spec.y_axis.unit:
            self._text(p, m.spec.y_axis.unit, 18, qc(st.caption_color), (L - 20, T - 30), "right")
        if m.y2_ticks and m.spec.y2_axis.unit:
            self._text(p, m.spec.y2_axis.unit, 18, qc(st.caption_color), (R + 20, T - 30), "left")

    def _titles(self, p: QPainter, m: RenderModel) -> None:
        st = m.spec.style
        L = m.plot_rect[0]
        y = 80.0
        if st.title:
            self._text(p, st.title, st.title_size, qc(st.title_color), (L, y), "left")
            y += st.title_size * 0.85
        if st.subtitle:
            self._text(p, st.subtitle, st.subtitle_size, qc(st.subtitle_color), (L, y), "left")
            y += st.subtitle_size * 1.5
        if st.caption:
            self._text(p, st.caption, st.caption_size, qc(st.caption_color), (L, y), "left")

    def _legend(self, p: QPainter, m: RenderModel) -> None:
        st = m.spec.style
        lay = m.legend_layout
        if not lay.items:
            return
        if lay.title:
            self._text(p, lay.title, 18, qc(st.caption_color),
                       (lay.title_x, lay.title_y), "left")
        for it in lay.items:
            if it.kind == "swatch":
                p.setPen(Qt.NoPen)
                p.setBrush(qc(it.color))
                p.drawRect(QRectF(it.x - it.diameter / 2, it.y - it.diameter / 2,
                                  it.diameter, it.diameter))
                col = qc((0.85, 0.85, 0.85))
            else:
                pen = QPen(qc(st.axis_text_color))
                pen.setWidthF(1.5)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(it.x, it.y), it.diameter / 2, it.diameter / 2)
                col = qc(st.axis_text_color)
            self._text(p, it.label, it.label_size, col,
                       (it.label_x, it.label_y), "left")

    def _readout(self, p: QPainter, m: RenderModel) -> None:
        if not m.readout_values:
            return
        r = m.spec.readout
        vals = m.readout_values
        n = len(vals)
        idx = (self.progress / 100.0) * (n - 1)
        i = int(math.floor(min(max(idx, 0), n - 2)))
        v = vals[i] + (vals[i + 1] - vals[i]) * (idx - i)
        text = r.prefix + (str(int(math.floor(v))) if r.decimals == 0
                           else f"{v:.{int(r.decimals)}f}") + r.suffix
        L, T, R, B = m.plot_rect
        pos = {"top_right": (R, 100.0), "top_left": (L, 100.0),
               "bottom_right": (R, B + 130), "bottom_left": (L, B + 130)}.get(
                   r.corner, (R, 100.0))
        self._text(p, text, r.size, qc(r.color), pos,
                   "right" if "right" in r.corner else "left")

    def _guides(self, p: QPainter, m: RenderModel) -> None:
        L, T, R, B = m.plot_rect
        pen = QPen(QColor(90, 150, 220, 90))
        pen.setWidthF(1.5)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(L, T, R - L, B - T))


class PreviewPanel(QWidget):
    """Canvas plus a scrub slider and a playback transport.

    Playback follows the Comp & Animation settings: the timer ticks at the
    comp frame rate, runs from 0 to the comp duration, and maps time to
    Progress using the same start/end keyframe times the generated script
    writes onto the MASTER_CONTROLS slider.
    """

    progressChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.canvas = ChartCanvas(self)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(1000)
        self.value_label = QLabel("Progress  100%")
        self.value_label.setMinimumWidth(150)
        self.guides = QCheckBox("Plot bounds")
        self.guides.setChecked(True)

        self.btn_play = QPushButton("Play")
        self.btn_play.setFixedWidth(64)
        self.btn_play.setCheckable(True)
        self.btn_loop = QCheckBox("Loop")
        self.btn_loop.setChecked(True)

        self._timer = QTimer(self)
        self._time = 0.0

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.btn_play)
        row.addWidget(self.btn_loop)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value_label)
        row.addWidget(self.guides)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.canvas, 1)
        lay.addLayout(row)

        self.slider.valueChanged.connect(self._on_slider)
        self.slider.sliderPressed.connect(self.stop)
        self.guides.toggled.connect(self._on_guides)
        self.btn_play.toggled.connect(self._on_play)
        self._timer.timeout.connect(self._tick)

    # -- transport --------------------------------------------------------
    def _comp(self):
        m = self.canvas.model
        return m.spec.comp if (m is not None and m.spec is not None) else None

    def _on_play(self, on: bool) -> None:
        c = self._comp()
        if on and c is None:
            self.btn_play.setChecked(False)
            return
        self.btn_play.setText("Stop" if on else "Play")
        if on:
            if self._time >= c.duration - 1e-6:
                self._time = 0.0
            fps = max(1.0, c.fps)
            self._timer.start(max(8, int(round(1000.0 / fps))))
        else:
            self._timer.stop()

    def stop(self) -> None:
        if self.btn_play.isChecked():
            self.btn_play.setChecked(False)

    def _tick(self) -> None:
        c = self._comp()
        if c is None:
            self.stop()
            return
        self._time += 1.0 / max(1.0, c.fps)
        if self._time >= c.duration:
            if self.btn_loop.isChecked():
                self._time = 0.0
            else:
                self._time = c.duration
                self.stop()
        pct = progress_at_time(self._time, c)
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(pct * 10)))
        self.slider.blockSignals(False)
        self.canvas.set_progress(pct)
        self.value_label.setText(f"{self._time:5.2f}s   {pct:5.1f}%")
        self.progressChanged.emit(pct)

    def _on_slider(self, v: int) -> None:
        pct = v / 10.0
        c = self._comp()
        if c is not None:
            self._time = time_at_progress(pct, c)
        self.canvas.set_progress(pct)
        self.value_label.setText(
            f"{self._time:5.2f}s   {pct:5.1f}%" if c else f"Progress  {pct:.1f}%")
        self.progressChanged.emit(pct)

    def _on_guides(self, on: bool) -> None:
        self.canvas.show_guides = on
        self.canvas.update()

    def set_model(self, model: Optional[RenderModel]) -> None:
        self.canvas.set_model(model)

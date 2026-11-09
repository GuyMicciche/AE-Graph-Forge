"""Headless checks for the main window: drag and drop, and the donut panel.

Builds a real MainWindow under the offscreen platform plugin and drives it
with synthetic events, so the widget wiring is exercised rather than just the
model underneath it. Run with: python tools/check_ui.py
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QMimeData, QUrl, QPoint, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QDragMoveEvent, QDragLeaveEvent
import aegraphforge.ui.mainwindow as mw
# The failure path pops a modal dialog, which would block a headless run,
# so record the calls instead of showing them.
ERRORS = []
mw.QMessageBox.critical = staticmethod(lambda *a, **k: ERRORS.append(a[1:3]))
from aegraphforge.ui.mainwindow import MainWindow
from aegraphforge.core.spec import DONUT

app = QApplication([])
fails = []
def check(name, cond, detail=""):
    print(("  ok    " if cond else "  FAIL  ") + name + ("  " + str(detail) if not cond else ""))
    if not cond: fails.append(name)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(HERE, "examples", "data.csv")
PRESET = os.path.join(HERE, "presets", "capacity_share_donut.json")

def mime(*paths):
    md = QMimeData(); md.setUrls([QUrl.fromLocalFile(p) for p in paths]); return md

def enter(win, md):
    e = QDragEnterEvent(QPoint(400, 300), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    win.dragEnterEvent(e); return e

def drop(win, md):
    e = QDropEvent(QPoint(400, 300), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    win.dropEvent(e); return e

win = MainWindow(); win.show()

print("drag feedback")
e = enter(win, mime(CSV))
check("csv drag accepted", e.isAccepted())
check("overlay appears", win._drop_hint.isVisible())
check("overlay names the file", "data.csv" in win._drop_hint.text(), win._drop_hint.text())
check("overlay covers the window", win._drop_hint.geometry() == win.rect())
e = QDragMoveEvent(QPoint(400,300), Qt.CopyAction, mime(CSV), Qt.LeftButton, Qt.NoModifier)
win.dragMoveEvent(e); check("drag move keeps the target alive", e.isAccepted())
win.dragLeaveEvent(QDragLeaveEvent()); check("overlay clears on leave", not win._drop_hint.isVisible())

e = enter(win, mime("/tmp/qtlibs/nope.deb"))
check("unsupported file rejected", not e.isAccepted())
check("no overlay for rejected drag", not win._drop_hint.isVisible())
e = enter(win, mime(PRESET))
check("preset drag accepted", e.isAccepted() and "capacity_share_donut" in win._drop_hint.text())
win.dragLeaveEvent(QDragLeaveEvent())
e = enter(win, mime(CSV, PRESET))
check("combined drag mentions both", "data and apply the preset" in win._drop_hint.text(),
      win._drop_hint.text())
win.dragLeaveEvent(QDragLeaveEvent())
e = enter(win, mime(os.path.join(HERE, "examples")))
check("directory rejected", not e.isAccepted())

print("\ndropping a csv")
check("nothing loaded yet", win.ds is None)
drop(win, mime(CSV))
check("dataset loaded", win.ds is not None and win.ds.n_rows == 107)
check("overlay hidden after drop", not win._drop_hint.isVisible())
check("auto-configured a chart", win.model is not None and win.model.ok)
check("jumped to Mapping tab", win.tabs.currentIndex() == 1)
check("column list populated", win.col_list.count() == 8)
first_spec = win.spec.to_json()

print("\nre-dropping the same columns keeps the chart")
win.spec.chart_type = DONUT
win.spec.group_column = "Orbit_Type"
win.spec.aggregation = "count"
win._apply(); win._refresh()
before = win.spec.to_json()
drop(win, mime(CSV))
check("mapping survives a same-columns reload", win.spec.to_json() == before)
check("status says so", "chart kept" in win.statusBar().currentMessage(),
      win.statusBar().currentMessage())

print("\ndropping a preset")
drop(win, mime(PRESET))
import json
want = json.load(open(PRESET))
check("preset chart type applied", win.spec.chart_type == want["chart_type"])
check("preset rebuilt cleanly", win.model is not None and win.model.ok,
      win.model.error if win.model else "")

print("\ncombined drop")
win2 = MainWindow(); win2.show()
drop(win2, mime(CSV, PRESET))
check("both applied from one drop",
      win2.ds is not None and win2.spec.chart_type == want["chart_type"])
check("model valid", win2.model is not None and win2.model.ok)

print("\nbad file")
open("/tmp/broken.csv","w").write("")
before_ds = win2.ds
drop(win2, mime("/tmp/broken.csv"))
check("unreadable csv reports an error", len(ERRORS) == 1, ERRORS)
check("unreadable csv leaves the old data alone", win2.ds is before_ds)
check("window survives", win2.isVisible())

print("\ndonut panel wiring")
w = MainWindow(); w.show(); w.load_csv(CSV)
w.cb_type.setCurrentIndex(w.cb_type.findData(DONUT))
app.processEvents(); w._refresh()
check("grouping panel visible on donut", w.grp_bar.isVisible())
check("donut panel visible", w.grp_donut.isVisible())
check("lollipop panel hidden", not w.grp_lolli.isVisible())
check("group column auto-picked", w.cb_group.currentData() == "Orbit_Type",
      w.cb_group.currentData())
check("three slices", len(w.model.segments) == 3,
      [g.label for g in w.model.segments])
check("max label reads 'Max slices'", w.lbl_maxbars.text() == "Max slices")
check("swatch per slice", sorted(w._slice_buttons) == ["GEO", "LEO", "MEO"],
      sorted(w._slice_buttons))
w.sp_ring_i.setValue(0); w._refresh()
check("inner radius 0 makes a pie", w.model.donut_r_inner == 0.0)
check("pie stroke reaches centre",
      abs(w.model.donut_radius * 2 - w.model.donut_thickness) < 1e-9)
w.sp_ring_i.setValue(55); w._refresh()
check("inner radius restores the hole", w.model.donut_r_inner > 0)
b = w._slice_buttons["LEO"]; b.set_rgb((1.0, 0.0, 0.0)); b.colorChanged.emit((1.0,0.0,0.0))
w._refresh()
leo = [g for g in w.model.segments if g.label == "LEO"][0]
check("slice recolour reaches the model", leo.color == (1.0, 0.0, 0.0), leo.color)
w.cb_type.setCurrentIndex(w.cb_type.findData("line")); app.processEvents(); w._refresh()
check("donut panel hides again", not w.grp_donut.isVisible())
check("line chart still builds", w.model.ok, w.model.error)
w.cb_type.setCurrentIndex(w.cb_type.findData(DONUT)); app.processEvents(); w._refresh()
check("LEO colour survived the round trip",
      w.spec.category.colors.get("LEO") == (1.0, 0.0, 0.0))

print()
print(f"{len(fails)} FAILED: {fails}" if fails else "all UI checks passed")
sys.exit(1 if fails else 0)

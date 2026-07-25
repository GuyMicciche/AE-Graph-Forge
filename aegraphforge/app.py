"""
app.py -- entry point.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from .ui.mainwindow import MainWindow


def _dark(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    bg, base, text = QColor(37, 38, 43), QColor(28, 29, 33), QColor(224, 226, 232)
    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, QColor(43, 44, 50))
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, QColor(52, 54, 61))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.ToolTipBase, QColor(52, 54, 61))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Highlight, QColor(72, 128, 200))
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 122, 130))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 122, 130))
    app.setPalette(p)
    app.setStyleSheet("""
        QGroupBox { font-weight: 600; border: 1px solid #45474f;
                    border-radius: 5px; margin-top: 12px; padding-top: 10px; }
        QGroupBox::title { subcontrol-origin: margin; left: 9px; padding: 0 4px; }
        QTabBar::tab { padding: 6px 12px; }
        QPlainTextEdit { background: #17181c; }
    """)


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName("AE Graph Forge")
    _dark(app)
    win = MainWindow()
    win.show()
    if len(argv) > 1:
        try:
            from .core.dataset import Dataset
            win.ds = Dataset.from_csv(argv[1])
            win.lbl_path.setText(f"{argv[1]}\n{win.ds.n_rows} rows, "
                                 f"{len(win.ds.columns)} columns")
            win.btn_auto.setEnabled(True)
            win._populate_columns()
            win._fill_table()
            win.auto_configure()
            win.tabs.setCurrentIndex(1)
        except Exception as exc:
            print(f"Could not open {argv[1]}: {exc}")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

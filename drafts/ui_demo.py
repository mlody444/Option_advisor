import sys
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QScrollArea,
    QGridLayout, QLabel, QVBoxLayout, QHBoxLayout, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import pyqtgraph as pg

# ── mock data ────────────────────────────────────────────────────────────────

STRIKES = [580, 585, 590, 595, 600, 605, 610, 615, 620, 625]

CALL_COLOR = "#89b4fa"   # blue
PUT_COLOR  = "#f38ba8"   # red
BG_COLOR   = "#1e1e2e"
PANEL_COLOR = "#181825"
LABEL_COLOR = "#313244"
TEXT_COLOR  = "#cdd6f4"
STRIKE_COLOR = "#a6e3a1"


def mock_theta_curve(strike, atm=600, seed=0):
    rng = np.random.default_rng(seed)
    dte = np.linspace(45, 0.5, 120)
    # theta accelerates near expiry; peaks slightly OTM
    moneyness = 1 - abs(strike - atm) / 60
    base = moneyness * 0.6 / np.sqrt(dte)
    noise = rng.normal(0, 0.015, len(dte))
    return dte, np.clip(base + noise, 0, None)


# ── widgets ───────────────────────────────────────────────────────────────────

def make_chart(strike, is_call, seed):
    dte, theta = mock_theta_curve(strike, seed=seed)

    pw = pg.PlotWidget()
    pw.setFixedHeight(110)
    pw.setBackground(PANEL_COLOR)
    pw.showGrid(x=True, y=True, alpha=0.15)
    pw.getAxis("bottom").setLabel("DTE", color=TEXT_COLOR)
    pw.getAxis("left").setLabel("θ", color=TEXT_COLOR)
    pw.getAxis("bottom").setPen(pg.mkPen(TEXT_COLOR, width=1))
    pw.getAxis("left").setPen(pg.mkPen(TEXT_COLOR, width=1))
    pw.getAxis("bottom").setTextPen(pg.mkPen(TEXT_COLOR))
    pw.getAxis("left").setTextPen(pg.mkPen(TEXT_COLOR))

    color = CALL_COLOR if is_call else PUT_COLOR
    pw.plot(dte, theta, pen=pg.mkPen(color=color, width=2))

    # shade area under curve
    fill = pg.FillBetweenItem(
        pw.plot(dte, theta, pen=None),
        pw.plot(dte, np.zeros_like(theta), pen=None),
        brush=pg.mkBrush(color + "33"),   # 20% opacity
    )
    pw.addItem(fill)

    pw.setMouseEnabled(x=False, y=False)
    pw.hideButtons()
    pw.setMenuEnabled(False)
    return pw


def make_strike_label(strike):
    lbl = QLabel(str(strike))
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    font = QFont("Segoe UI", 13, QFont.Weight.Bold)
    lbl.setFont(font)
    lbl.setFixedHeight(110)
    lbl.setStyleSheet(
        f"color: {STRIKE_COLOR};"
        f"background: {LABEL_COLOR};"
        "border-radius: 6px;"
        "border: 1px solid #45475a;"
    )
    return lbl


def make_header_label(text):
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    font = QFont("Segoe UI", 12, QFont.Weight.Bold)
    lbl.setFont(font)
    lbl.setStyleSheet(f"color: {TEXT_COLOR}; padding-bottom: 4px;")
    return lbl


# ── main window ───────────────────────────────────────────────────────────────

class OptionsUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Options Analyzer — Theta Decay")
        self.resize(1280, 750)
        self.setStyleSheet(f"background: {BG_COLOR};")
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # ── header row
        header = QWidget()
        hl = QGridLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setColumnStretch(0, 4)
        hl.setColumnStretch(1, 1)
        hl.setColumnStretch(2, 4)
        hl.addWidget(make_header_label("Call  θ  decay"), 0, 0)
        hl.addWidget(make_header_label("Strike"), 0, 1)
        hl.addWidget(make_header_label("Put  θ  decay"), 0, 2)
        layout.addWidget(header)

        # ── separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #45475a;")
        layout.addWidget(sep)

        # ── scrollable strike rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: {BG_COLOR}; }}
            QScrollBar:vertical {{
                background: {LABEL_COLOR}; width: 8px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: #585b70; border-radius: 4px; min-height: 20px;
            }}
        """)

        content = QWidget()
        content.setStyleSheet(f"background: {BG_COLOR};")
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 4)

        for row, strike in enumerate(STRIKES):
            grid.addWidget(make_chart(strike, is_call=True,  seed=row),        row, 0)
            grid.addWidget(make_strike_label(strike),                           row, 1)
            grid.addWidget(make_chart(strike, is_call=False, seed=row + 100),  row, 2)

        scroll.setWidget(content)
        layout.addWidget(scroll)


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    pg.setConfigOption("background", PANEL_COLOR)
    pg.setConfigOption("foreground", TEXT_COLOR)
    pg.setConfigOption("antialias", True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    win = OptionsUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

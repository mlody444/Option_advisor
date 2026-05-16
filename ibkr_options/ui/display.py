import sys
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import QTimer


class OptionsWindow(QMainWindow):
    """Main application window. Reads from DataManager, delegates rendering
    to helper functions. No ibapi imports here.
    """

    def __init__(self, data_manager):
        super().__init__()
        self._dm = data_manager
        self.setWindowTitle("Options Analyzer — Theta Decay")
        self._build_ui()
        self._start_refresh_timer()

    def _build_ui(self):
        pass  # TODO: port layout from ui_demo.py

    def _start_refresh_timer(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(500)  # refresh every 500 ms

    def _refresh(self):
        self._dm.process_pending()
        pass  # TODO: pull updated chain, replot charts


def run(data_manager):
    app = QApplication(sys.argv)
    win = OptionsWindow(data_manager)
    win.show()
    sys.exit(app.exec())

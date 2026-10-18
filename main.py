"""程序入口。"""
import sys

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.ui.font import apply_app_font


def main():
    app = QApplication(sys.argv)
    apply_app_font(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""程序入口。"""
import sys

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.paths import ensure_data_dirs
from app.ui.font import apply_app_font


def _set_windows_app_id():
    """让 Windows 任务栏把本程序识别为独立应用，使用自己的窗口图标。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "OneSheet.Onesheet")
    except (AttributeError, OSError):
        pass


def main():
    _set_windows_app_id()
    ensure_data_dirs()
    app = QApplication(sys.argv)
    apply_app_font(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

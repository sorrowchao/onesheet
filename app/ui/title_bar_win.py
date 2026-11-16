"""Windows 原生标题栏的深色支持。

Qt 无法直接改变系统标题栏配色；Windows 10 20H1+/Windows 11 支持
DwmSetWindowAttribute 的沉浸式深色模式（属性 20），更早的 Win10 1809–1909
使用属性 19。非 Windows 或系统不支持时静默返回 False，不影响其余功能。
"""
import ctypes
import sys

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_USE_IMMERSIVE_DARK_MODE_PRE_20H1 = 19

_WM_NCACTIVATE = 0x0086


def _refresh_title_bar(hwnd) -> None:
    """强制非客户区（标题栏）立即重绘。

    DwmSetWindowAttribute 只更新 DWM 内部状态，Windows 10 不会自动重画
    标题栏，要等下一次最大化/还原才刷新。向窗口发一对 WM_NCACTIVATE
    （先未激活、再激活）可立即触发非客户区重绘；RedrawWindow/SetWindowPos
    只作用于客户区，无效。
    """
    try:
        user32 = ctypes.windll.user32
        user32.SendMessageW(hwnd, _WM_NCACTIVATE, 0, 0)
        user32.SendMessageW(hwnd, _WM_NCACTIVATE, 1, 0)
    except (AttributeError, OSError):
        pass


def apply_dark_title_bar(widget, dark: bool) -> bool:
    """把 widget 所属顶层窗口的标题栏切换为深色/浅色；成功返回 True。"""
    if sys.platform != "win32":
        return False
    try:
        hwnd = ctypes.c_void_p(int(widget.window().winId()))
        value = ctypes.c_int(1 if dark else 0)
        dwmapi = ctypes.windll.dwmapi
    except (AttributeError, OSError, ValueError):
        return False
    for attribute in (_DWMWA_USE_IMMERSIVE_DARK_MODE,
                      _DWMWA_USE_IMMERSIVE_DARK_MODE_PRE_20H1):
        try:
            result = dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
        except (AttributeError, OSError):
            return False
        if result == 0:
            _refresh_title_bar(hwnd)
            return True
    return False

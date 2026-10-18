"""全局界面字体：优先中文 UI 字体，逐级回退。

`Microsoft YaHei UI` 是 Windows 10/11 上现代应用（VSCode 等）使用的中文
UI 字体：西文部分与 Segoe UI 同形，中文比默认宋体清晰，9.75pt 下小字号
也可读。若系统未安装则依次回退，全部缺失时交给 Qt 用系统默认字体。

纯 Qt 字体选择，不含业务逻辑；`apply_app_font()` 必须在创建任何窗口前
调用，才能让所有控件（含后续弹出的对话框）继承该字体。
"""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

# 按优先级排列；QFont.setFamilies 会按此顺序逐个回退缺失字形。
PREFERRED_FAMILIES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Segoe UI",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "PingFang SC",
    "Arial",
)

BASE_POINT_SIZE = 9.75  # ≈13px @96DPI，与 VSCode 默认 UI 字号一致


def available_families() -> list[str]:
    """当前系统可用字体族（Qt 全小写不敏感比较由调用方处理）。"""
    return list(QFontDatabase.families())


def resolve_families(preferred=PREFERRED_FAMILIES,
                     available=None) -> list[str]:
    """按优先级挑出已安装的字体族，保持顺序作为 QFont 回退链。

    `available` 用于测试注入，省略时读取系统字体库。
    """
    families = available_families() if available is None else available
    known = {name.casefold() for name in families}
    return [name for name in preferred if name.casefold() in known]


def ui_font(preferred=PREFERRED_FAMILIES, available=None,
            point_size: float = BASE_POINT_SIZE) -> QFont:
    """构造界面字体；即使一个首选字体都没有，也返回设置了字号的 QFont。"""
    font = QFont()
    resolved = resolve_families(preferred, available)
    if resolved:
        font.setFamilies(resolved)
    font.setPointSizeF(point_size)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def apply_app_font(app: QApplication | None = None) -> QFont:
    """把界面字体设为 QApplication 默认字体（在创建窗口前调用）。"""
    app = app if app is not None else QApplication.instance()
    font = ui_font()
    if app is not None:
        app.setFont(font)
    return font

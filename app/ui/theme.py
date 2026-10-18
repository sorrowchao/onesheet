"""VSCode 风格主题（深色 / 浅色）。

纯样式表（QSS），不含任何业务逻辑：由 `MainWindow` 在启动时应用到
`QApplication`，切换「视图 → 主题」时重新应用，从而影响所有控件（含对话框）。

配色取自 VSCode Dark+ / Light+ 的常用取值。
"""
from __future__ import annotations

from pathlib import Path
from string import Template

DARK = "dark"
LIGHT = "light"
DEFAULT = DARK
ALL = (DARK, LIGHT)


def normalize(name: str | None) -> str:
    """把未知/空主题名归一化到受支持值（默认深色）。"""
    return name if name in ALL else DEFAULT


def check_icon_path() -> Path:
    """勾选框「勾」图标路径（PyInstaller onefile 下同样位于 _MEIPASS/app/ui/assets）。"""
    return Path(__file__).resolve().parent / "assets" / "check.svg"


# --- 配色 ------------------------------------------------------------------
# 深浅两套只差这些色值，QSS 模板共用一份，避免维护两份样式表。

_DARK = {
    "bg": "#1e1e1e",          # 编辑区/主背景
    "bg_side": "#252526",     # 侧栏（文件/配置）
    "bg_alt": "#232323",      # 表格交替行
    "bg_titlebar": "#3c3c3c",  # 菜单栏
    "bg_input": "#3c3c3c",    # 输入框/下拉
    "bg_hover": "#2a2d2e",    # 悬停
    "card_bg": "#2b2b2c",     # 分组卡片背景（比侧栏略亮）
    "text": "#cccccc",
    "text_dim": "#969696",
    "border": "#3c3c3c",
    "input_border": "#3c3c3c",
    "focus_border": "#007fd4",
    "sel": "#094771",         # 选中背景
    "sel_text": "#ffffff",
    "accent": "#007acc",
    "btn_bg": "#0e639c",
    "btn_hover": "#1177bb",
    "btn_pressed": "#0a4d78",
    "btn_text": "#ffffff",
    "sb": "#797979",          # 滚动条滑块
    "sb_hover": "#a6a6a6",
    "status_text": "#ffffff",
    "check_bg": "#1e1e1e",    # 未勾选框底色
    "check_border": "#6b6b6b",  # 未勾选框边框（与底色区分，能看见）
}

_LIGHT = {
    "bg": "#ffffff",
    "bg_side": "#f3f3f3",
    "bg_alt": "#f7f7f7",
    "bg_titlebar": "#dddddd",
    "bg_input": "#ffffff",
    "bg_hover": "#e8e8e8",
    "card_bg": "#ffffff",
    "text": "#333333",
    "text_dim": "#6f6f6f",
    "border": "#e0e0e0",
    "input_border": "#cecece",
    "focus_border": "#007fd4",
    "sel": "#0060c0",
    "sel_text": "#ffffff",
    "accent": "#007acc",
    "btn_bg": "#007acc",
    "btn_hover": "#0062a3",
    "btn_pressed": "#005a94",
    "btn_text": "#ffffff",
    "sb": "#c1c1c1",
    "sb_hover": "#a8a8a8",
    "status_text": "#ffffff",
    "check_bg": "#ffffff",
    "check_border": "#8a8a8a",
}

_PALETTES = {DARK: _DARK, LIGHT: _LIGHT}


# --- QSS 模板（string.Template，避免与 CSS 的花括号冲突）----------------------
_TEMPLATE = Template("""
QMainWindow, QDialog { background-color: $bg; }

QWidget { color: $text; font-size: 13px; }

/* --- 菜单栏 / 菜单 --- */
QMenuBar {
    background-color: $bg_titlebar;
    color: $text;
    padding: 3px 6px;
    border-bottom: 1px solid $border;
}
QMenuBar::item {
    background: transparent;
    padding: 5px 12px;
    border-radius: 6px;
}
QMenuBar::item:selected { background-color: $bg_hover; }
QMenuBar::item:pressed { background-color: $sel; color: $sel_text; }

QMenu {
    background-color: $bg_side;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 5px;
}
QMenu::item {
    padding: 6px 26px 6px 22px;
    border-radius: 5px;
    margin: 1px 2px;
}
QMenu::item:selected { background-color: $sel; color: $sel_text; }
QMenu::item:disabled { color: $text_dim; }
QMenu::separator { height: 1px; background: $border; margin: 5px 10px; }

/* --- 分割条：加大可点区域，悬停高亮 --- */
QSplitter::handle { background-color: $border; }
QSplitter::handle:horizontal { width: 4px; }
QSplitter::handle:vertical { height: 4px; }
QSplitter::handle:hover { background-color: $accent; }

/* --- 分组框：圆角卡片 --- */
QGroupBox {
    background-color: $card_bg;
    border: 1px solid $border;
    border-radius: 10px;
    margin-top: 14px;
    padding: 10px 10px 8px 10px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: $text;
}

/* --- 面板分区标题：色带 + 分隔线 --- */
QLabel#sectionHeader {
    color: $text;
    font-weight: bold;
    letter-spacing: 1px;
    padding: 8px 10px;
    background-color: $bg_hover;
    border-bottom: 1px solid $border;
    border-radius: 6px;
}

/* --- 侧栏着色 --- */
QWidget#sidePanel { background-color: $bg_side; }
QScrollArea { border: none; background-color: $bg_side; }
QWidget#sideBody { background-color: $bg_side; }

/* --- 输入控件 --- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {
    background-color: $bg_input;
    color: $text;
    border: 1px solid $input_border;
    border-radius: 7px;
    padding: 4px 8px;
    selection-background-color: $sel;
    selection-color: $sel_text;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid $focus_border;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: $bg_side;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: $sel;
    selection-color: $sel_text;
    outline: 0;
}
QComboBox QAbstractItemView::item {
    padding: 5px 8px;
    border-radius: 5px;
    color: $text;
}
QComboBox QAbstractItemView::item:selected {
    background-color: $sel;
    color: $sel_text;
}
QComboBox QAbstractItemView::item:hover {
    background-color: $bg_hover;
    color: $text;
}

/* --- 按钮 --- */
QPushButton {
    background-color: $btn_bg;
    color: $btn_text;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 5px 14px;
}
QPushButton:hover { background-color: $btn_hover; }
QPushButton:pressed { background-color: $btn_pressed; }
QPushButton:disabled { background-color: $bg_hover; color: $text_dim; }

QToolButton {
    background-color: transparent;
    color: $text;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 5px 10px;
}
QToolButton:hover { background-color: $bg_hover; }
QToolButton:pressed { background-color: $sel; color: $sel_text; }

/* 页签栏右侧的紧凑按钮（与标签同高） */
QPushButton[compact="true"] { padding: 3px 10px; }
QToolButton[compact="true"] { padding: 3px 8px; }

/* --- 列表 / 表格 / 树：圆角边框，边界更清楚 --- */
QListWidget, QListView, QTableWidget, QTableView, QTreeWidget, QTreeView {
    background-color: $bg;
    alternate-background-color: $bg_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: 10px;
    gridline-color: $border;
    selection-background-color: $sel;
    selection-color: $sel_text;
    outline: 0;
}
QListWidget::item, QTreeWidget::item {
    padding: 4px 6px;
    border-radius: 5px;
    margin: 1px 3px;
}
QListWidget::item:hover, QListView::item:hover,
QTableWidget::item:hover, QTreeWidget::item:hover {
    background-color: $bg_hover;
}
QListWidget::item:selected, QTableWidget::item:selected,
QTreeWidget::item:selected {
    background-color: $sel;
    color: $sel_text;
}

QHeaderView { background-color: $bg_side; }
QHeaderView::section {
    background-color: $bg_side;
    color: $text_dim;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid $border;
    border-bottom: 1px solid $border;
}
QHeaderView::section:first { border-top-left-radius: 9px; }
QHeaderView::section:last { border-top-right-radius: 9px; }
QTableCornerButton::section {
    background-color: $bg_side;
    border: 1px solid $border;
}

/* --- 标签页（结果表 / 预览）--- */
QTabWidget { background-color: $bg; }
QTabWidget::pane {
    border: 1px solid $border;
    border-radius: 10px;
    background-color: $bg;
    top: -1px;
}
QTabBar { background-color: $bg; }
QTabBar::tab {
    background-color: $bg_side;
    color: $text_dim;
    padding: 6px 14px;
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin: 2px 2px 0 0;
}
QTabBar::tab:selected {
    background-color: $bg;
    color: $text;
    border: 1px solid $border;
    border-top: 2px solid $accent;
    border-bottom: 1px solid $bg;
}
QTabBar::tab:hover { background-color: $bg_hover; }

/* --- 滚动条 --- */
QScrollBar:vertical { background: transparent; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: $sb; min-height: 24px; border-radius: 6px; }
QScrollBar::handle:vertical:hover { background: $sb_hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QScrollBar:horizontal { background: transparent; height: 12px; margin: 0; }
QScrollBar::handle:horizontal { background: $sb; min-width: 24px; border-radius: 6px; }
QScrollBar::handle:horizontal:hover { background: $sb_hover; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

/* --- 勾选框（含列表/表格勾选项）--- */
QCheckBox { color: $text; spacing: 6px; }
QCheckBox::indicator, QListWidget::indicator, QTreeWidget::indicator,
QTableWidget::indicator, QTableView::indicator {
    width: 15px; height: 15px;
    border: 1px solid $check_border;
    border-radius: 4px;
    background-color: $check_bg;
}
QCheckBox::indicator:hover, QListWidget::indicator:hover,
QTreeWidget::indicator:hover, QTableWidget::indicator:hover,
QTableView::indicator:hover {
    border: 1px solid $accent;
}
QCheckBox::indicator:checked, QListWidget::indicator:checked,
QTreeWidget::indicator:checked, QTableWidget::indicator:checked,
QTableView::indicator:checked {
    background-color: $accent;
    border: 1px solid $accent;
    image: url("$check_icon");
}

/* 字段映射表首列（勾选框，列宽 44px）：把 17px 的勾选框居中。 */
QTableWidget#fieldsTable::indicator {
    margin-left: 13px;
}

/* --- 日志：等宽字体，时间/计数对齐更易扫读 --- */
QPlainTextEdit#logView {
    font-family: Consolas;
    font-size: 12px;
}

/* --- 进度条 / 状态栏 / 提示 --- */
QProgressBar {
    background-color: $bg_input;
    border: none;
    border-radius: 5px;
    color: $text;
    text-align: center;
    max-height: 10px;
}
QProgressBar::chunk {
    background-color: $accent;
    border-radius: 5px;
}

QStatusBar { background-color: $accent; color: $status_text; }
QStatusBar QLabel { color: $status_text; }
QStatusBar::item { border: none; }

QToolTip {
    background-color: $bg_side;
    color: $text;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 4px 8px;
}
""")


def stylesheet(name: str | None = DARK) -> str:
    """返回指定主题的完整 QSS（未知名称回退到默认主题）。"""
    return _TEMPLATE.substitute(
        check_icon=check_icon_path().as_posix(),
        **_PALETTES[normalize(name)],
    )

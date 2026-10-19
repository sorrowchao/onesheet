"""程序数据目录解析（data/ 所在根目录）。

源码运行：项目根目录（`app/paths.py` 的上两级）。
打包运行：exe 所在目录；若 exe 同级还没有模板、而上一级已有
（典型的 `dist/onesheet.exe` + 项目根 `data/templates/` 布局），
则沿用上一级，避免打包版“看不到”已有模板与设置。
"""
from __future__ import annotations

import sys
from pathlib import Path


def _source_base() -> Path:
    # app/paths.py -> app -> 项目根目录
    return Path(__file__).resolve().parent.parent


def _has_templates(templates: Path) -> bool:
    return templates.is_dir() and any(templates.glob("*.json"))


def frozen_base(exe_path: str | Path) -> Path:
    """根据 exe 路径推断数据根目录（可注入，便于测试）。"""
    exe_dir = Path(exe_path).resolve().parent
    if not _has_templates(exe_dir / "data" / "templates"):
        parent_templates = exe_dir.parent / "data" / "templates"
        if _has_templates(parent_templates):
            return exe_dir.parent
    return exe_dir


def base_dir() -> Path:
    """程序根目录，其下为 data/。"""
    if getattr(sys, "frozen", False):
        return frozen_base(sys.executable)
    return _source_base()


def data_dir() -> Path:
    return base_dir() / "data"


def resource_dir() -> Path:
    """只读资源根目录（`app/icons` 等随程序打包的资源所在处）。

    源码运行：项目根目录；打包运行：PyInstaller 的 onefile 解包目录
    （`sys._MEIPASS`），这样资源不必散落在 exe 旁边。
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return _source_base()

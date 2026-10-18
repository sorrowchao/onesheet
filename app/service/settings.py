"""本地设置存取（data/settings.json）。

保存 DeepSeek API Key 与界面主题名。单人本地工具，明文存盘可接受；
支持 `DEEPSEEK_API_KEY` 环境变量覆盖文件里的 key。
"""
import json
import os
from pathlib import Path

from app.paths import data_dir

# 打包后（onefile）由 app.paths 解析 exe 附近的数据根目录，避免设置丢失。
DEFAULT_SETTINGS_DIR = data_dir()

_API_KEY_FIELD = "deepseek_api_key"
_THEME_FIELD = "theme"
_ICON_FIELD = "icon"
_WINDOW_FIELD = "window_state"
_LAST_IMPORT_DIR_FIELD = "last_import_dir"

DEFAULT_ICON = "1"
_ICON_EXTS = {".png", ".ico", ".svg", ".jpg", ".jpeg", ".bmp"}

# 受支持的主题名（避免 settings 反向依赖 UI 层，这里只留一个白名单）。
_THEMES = ("dark", "light")
_DEFAULT_THEME = "dark"


def settings_path(dir_path: Path | None = None) -> Path:
    d = Path(dir_path) if dir_path is not None else DEFAULT_SETTINGS_DIR
    return d / "settings.json"


def load_settings(dir_path: Path | None = None) -> dict:
    """读取设置。缺文件/坏 JSON 都返回空 dict，不抛异常。"""
    path = settings_path(dir_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(d: dict, dir_path: Path | None = None) -> None:
    path = settings_path(dir_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def env_api_key() -> str:
    """环境变量 `DEEPSEEK_API_KEY` 的值（无则空串）。"""
    return (os.environ.get("DEEPSEEK_API_KEY") or "").strip()


def get_stored_api_key(dir_path: Path | None = None) -> str:
    """只读设置文件里的 key（忽略环境变量），供设置对话框展示/编辑。"""
    value = load_settings(dir_path).get(_API_KEY_FIELD)
    return value.strip() if isinstance(value, str) else ""


def get_api_key(dir_path: Path | None = None) -> str:
    """优先取环境变量 `DEEPSEEK_API_KEY`，否则读文件。无则返回空串。"""
    return env_api_key() or get_stored_api_key(dir_path)


def set_api_key(key: str, dir_path: Path | None = None) -> None:
    """写入 key，保留文件里其他键；key 为空则清除已保存的 key。"""
    data = load_settings(dir_path)
    key = (key or "").strip()
    if key:
        data[_API_KEY_FIELD] = key
    else:
        data.pop(_API_KEY_FIELD, None)
    save_settings(data, dir_path)


def get_theme(dir_path: Path | None = None) -> str:
    """返回保存的主题名（dark/light）；缺失或非法值回退默认（dark）。"""
    value = load_settings(dir_path).get(_THEME_FIELD)
    return value if value in _THEMES else _DEFAULT_THEME


def set_theme(name: str, dir_path: Path | None = None) -> None:
    """写入主题名（非受支持值忽略），保留文件里其他键。"""
    if name not in _THEMES:
        return
    data = load_settings(dir_path)
    data[_THEME_FIELD] = name
    save_settings(data, dir_path)


# --- 窗口状态 / 上次导入目录 ------------------------------------------------

def get_window_state(dir_path: Path | None = None) -> dict:
    """返回保存的窗口状态（宽高、最大化、分割条比例）；无则空 dict。"""
    value = load_settings(dir_path).get(_WINDOW_FIELD)
    return value if isinstance(value, dict) else {}


def set_window_state(state: dict, dir_path: Path | None = None) -> None:
    """保存窗口状态，保留文件里其他键。"""
    data = load_settings(dir_path)
    data[_WINDOW_FIELD] = state
    save_settings(data, dir_path)


def get_last_import_dir(dir_path: Path | None = None) -> str:
    """返回上次导入文件/文件夹的目录；无则空串。"""
    value = load_settings(dir_path).get(_LAST_IMPORT_DIR_FIELD)
    return value if isinstance(value, str) else ""


def set_last_import_dir(path: str, dir_path: Path | None = None) -> None:
    """记住导入目录；空串则清除。"""
    data = load_settings(dir_path)
    value = (path or "").strip()
    if value:
        data[_LAST_IMPORT_DIR_FIELD] = value
    else:
        data.pop(_LAST_IMPORT_DIR_FIELD, None)
    save_settings(data, dir_path)


# --- 应用图标（data/icons/ 下的文件，用户可选）-------------------------------

def icons_dir(dir_path: Path | None = None) -> Path:
    d = Path(dir_path) if dir_path is not None else DEFAULT_SETTINGS_DIR
    return d / "icons"


def _icon_sort_key(path: Path):
    stem = path.stem
    return (0, int(stem), "") if stem.isdigit() else (1, 0, stem.lower())


def available_icons(dir_path: Path | None = None) -> list[Path]:
    """列出 data/icons/ 下可用的图标文件（数字名按数值排序）。"""
    d = icons_dir(dir_path)
    if not d.exists():
        return []
    return sorted(
        (p for p in d.iterdir()
         if p.is_file() and p.suffix.lower() in _ICON_EXTS),
        key=_icon_sort_key,
    )


def resolve_icon_name(name: str | None = None,
                      dir_path: Path | None = None) -> str:
    """把图标名解析成实际存在的图标名：优先用传入值，其次默认 1，最后第一个。"""
    files = available_icons(dir_path)
    if not files:
        return ""
    stems = {p.stem for p in files}
    if name and name in stems:
        return name
    if DEFAULT_ICON in stems:
        return DEFAULT_ICON
    return files[0].stem


def icon_path(name: str | None = None,
              dir_path: Path | None = None) -> Path | None:
    """返回图标文件路径；data/icons/ 为空时返回 None。"""
    resolved = resolve_icon_name(name, dir_path)
    if not resolved:
        return None
    for p in available_icons(dir_path):
        if p.stem == resolved:
            return p
    return None


def get_icon(dir_path: Path | None = None) -> str:
    """返回当前图标名（保存在设置里；缺失/无效时回退默认 1 或第一个）。"""
    value = load_settings(dir_path).get(_ICON_FIELD)
    return resolve_icon_name(value if isinstance(value, str) else None, dir_path)


def set_icon(name: str, dir_path: Path | None = None) -> None:
    """保存图标名；不存在的图标名忽略。"""
    if name not in {p.stem for p in available_icons(dir_path)}:
        return
    data = load_settings(dir_path)
    data[_ICON_FIELD] = name
    save_settings(data, dir_path)

"""模板保存 / 读取 / 列表。"""
import json
from pathlib import Path

from app.core.models import ExtractTemplate
from app.paths import data_dir
from .schema import from_dict, to_dict, validate

# 打包后（onefile）由 app.paths 解析 exe 附近的数据根目录，避免模板丢失。
DEFAULT_TEMPLATE_DIR = data_dir() / "templates"

_INVALID_FILENAME_CHARS = set('<>:"/\\|?*')


def templates_dir() -> Path:
    return DEFAULT_TEMPLATE_DIR


def _safe_filename(name: str) -> str:
    cleaned = "".join("_" if ch in _INVALID_FILENAME_CHARS else ch for ch in name).strip()
    return cleaned or "未命名模板"


def save_path(template: ExtractTemplate, path: str | Path) -> str:
    """保存模板到指定文件路径（父目录自动创建），返回写入的文件路径。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(to_dict(template), ensure_ascii=False, indent=2)
    p.write_text(payload, encoding="utf-8")
    return str(p)


def save(template: ExtractTemplate, dir_path: Path | None = None) -> str:
    """按模板名保存到模板目录，返回写入的文件路径。"""
    d = dir_path or DEFAULT_TEMPLATE_DIR
    return save_path(template, d / (_safe_filename(template.name) + ".json"))


def template_filename(name: str) -> str:
    """模板名 → 安全文件名（含 .json）。"""
    return _safe_filename(name) + ".json"


def duplicate(path: str | Path, new_name: str) -> str:
    """复制模板为新名字，返回新文件路径；同名文件已存在时抛 FileExistsError。"""
    tpl = load(str(path))
    tpl.name = (new_name or "").strip() or "未命名模板"
    target = Path(path).parent / template_filename(tpl.name)
    if target.exists():
        raise FileExistsError(f"模板已存在：{target.name}")
    return save_path(tpl, target)


def rename(path: str | Path, new_name: str) -> str:
    """重命名模板（同时改模板名与文件名），返回新文件路径。

    目标文件已存在（且不是同一个文件）时抛 FileExistsError。
    """
    tpl = load(str(path))
    tpl.name = (new_name or "").strip() or "未命名模板"
    old = Path(path)
    target = old.parent / template_filename(tpl.name)
    if target.exists() and target.resolve() != old.resolve():
        raise FileExistsError(f"模板已存在：{target.name}")
    saved = save_path(tpl, target)
    if target.resolve() != old.resolve():
        old.unlink(missing_ok=True)
    return saved


def delete(path: str | Path) -> None:
    """删除模板文件（不存在时忽略）。"""
    Path(path).unlink(missing_ok=True)


def load(path: str) -> ExtractTemplate:
    """读取并校验模板 JSON，返回 ExtractTemplate。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate(data)
    if errors:
        raise ValueError("模板无效：" + "；".join(errors))
    return from_dict(data)


def list_templates(dir_path: Path | None = None) -> list[dict]:
    """列出模板目录下所有合法模板，返回 [{path, name, mtime}]（mtime 为时间戳）。"""
    d = dir_path or DEFAULT_TEMPLATE_DIR
    if not d.exists():
        return []
    result = []
    for p in sorted(d.glob("*.json")):
        try:
            tpl = load(str(p))
            result.append({"path": str(p), "name": tpl.name,
                           "mtime": p.stat().st_mtime})
        except (ValueError, json.JSONDecodeError, OSError):
            continue
    return result

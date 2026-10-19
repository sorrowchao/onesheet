"""文件夹扫描与筛选（纯逻辑，无 Qt）。

按「直接父文件夹」分组，对每组做筛选、排序、限量，供导入文件夹对话框
和 `collect_input_files` 共用。
"""
import os
import re
import stat
from pathlib import Path

EXCEL_EXTS = frozenset({".xlsx", ".xls", ".xlsm"})
DOCUMENT_EXTS = frozenset({".docx", ".pdf", ".csv"})
INPUT_EXTS = EXCEL_EXTS | DOCUMENT_EXTS

SORT_MTIME_NEWEST = "mtime_newest"
SORT_MTIME_OLDEST = "mtime_oldest"
SORT_NAME_ASC = "name_asc"
SORT_SIZE_LARGEST = "size_largest"
SORT_SIZE_SMALLEST = "size_smallest"
SORT_PATH = "path"  # 内部用：按相对路径全局排序，兼容旧导入顺序

SORT_CHOICES = (
    (SORT_MTIME_NEWEST, "最后修改：新 → 旧"),
    (SORT_MTIME_OLDEST, "最后修改：旧 → 新"),
    (SORT_NAME_ASC, "文件名：A → Z"),
    (SORT_SIZE_LARGEST, "文件大小：大 → 小"),
    (SORT_SIZE_SMALLEST, "文件大小：小 → 大"),
)
SORT_LABELS = dict(SORT_CHOICES)

DEFAULTS = {
    "recursive": True,
    "per_folder_limit": 0,
    "sort_by": SORT_MTIME_NEWEST,
    "min_size": 0,
    "max_size": 0,
    "name_pattern": "",
}


class FolderScanError(ValueError):
    """扫描参数错误（正则、大小范围、根目录、排序方式）。"""


def normalize_options(data: dict | None) -> dict:
    """把设置文件/调用方传来的 dict 规范成合法选项；非法值回退默认。"""
    opts = dict(DEFAULTS)
    if not isinstance(data, dict):
        return opts

    value = data.get("recursive")
    if isinstance(value, bool):
        opts["recursive"] = value

    value = data.get("per_folder_limit")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        opts["per_folder_limit"] = value

    value = data.get("sort_by")
    if value in SORT_LABELS:
        opts["sort_by"] = value

    for key in ("min_size", "max_size"):
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            opts[key] = value

    value = data.get("name_pattern")
    if isinstance(value, str):
        opts["name_pattern"] = value

    return opts


def _ignore_walk_error(_error: OSError) -> None:
    """无权限的子目录直接跳过，不中断整次扫描。"""


def _safe_stat(path: Path):
    """返回普通文件的 stat；失败/目录/失效链接返回 None。"""
    try:
        st = path.stat()
    except OSError:
        return None
    return st if stat.S_ISREG(st.st_mode) else None


def _rank_key(sort_by: str, path: Path, rel: str, size: int, mtime: float):
    """组内排序键；同一优先级下用相对路径保证结果确定。"""
    norm = rel.casefold()
    tie = (norm, rel)
    if sort_by == SORT_MTIME_NEWEST:
        return (-mtime,) + tie
    if sort_by == SORT_MTIME_OLDEST:
        return (mtime,) + tie
    if sort_by == SORT_NAME_ASC:
        return (path.name.casefold(),) + tie
    if sort_by == SORT_SIZE_LARGEST:
        return (-size,) + tie
    if sort_by == SORT_SIZE_SMALLEST:
        return (size,) + tie
    return tie


def _collect(path: Path, root: Path, pattern, min_size: int, max_size: int):
    """单个候选文件 → (path, 相对路径 Path, 大小, mtime)；不满足条件返回 None。"""
    if path.suffix.lower() not in INPUT_EXTS:
        return None
    st = _safe_stat(path)
    if st is None:
        return None
    size = st.st_size
    if min_size and size < min_size:
        return None
    if max_size and size > max_size:
        return None
    if pattern is not None and not pattern.search(path.name):
        return None
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = Path(path.name)
    return path, rel, size, st.st_mtime


def scan_folder(root, *, recursive: bool = True, per_folder_limit: int = 0,
                sort_by: str = SORT_MTIME_NEWEST, min_size: int = 0,
                max_size: int = 0, name_pattern: str = "") -> list[str]:
    """扫描 root 下受支持的输入文件，按直接父文件夹分组筛选/排序/限量。

    返回路径字符串（保留 root 传入时的相对/绝对形式）。
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise FolderScanError(f"不是有效的文件夹：{root}")
    if sort_by not in SORT_LABELS and sort_by != SORT_PATH:
        raise FolderScanError(f"未知的排序方式：{sort_by}")
    if min_size < 0 or max_size < 0:
        raise FolderScanError("文件大小不能为负数")
    if min_size and max_size and min_size > max_size:
        raise FolderScanError("最小大小不能大于最大大小")

    pattern = None
    if name_pattern:
        try:
            pattern = re.compile(name_pattern)
        except re.error as e:
            raise FolderScanError(f"正则表达式无效：{e}") from e

    limit = max(0, int(per_folder_limit))

    candidates = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(
                root_path, followlinks=False, onerror=_ignore_walk_error):
            dirnames.sort()
            base = Path(dirpath)
            for name in sorted(filenames):
                item = _collect(base / name, root_path, pattern, min_size, max_size)
                if item is not None:
                    candidates.append(item)
    else:
        try:
            entries = sorted(root_path.iterdir())
        except OSError:
            entries = []
        for path in entries:
            item = _collect(path, root_path, pattern, min_size, max_size)
            if item is not None:
                candidates.append(item)

    groups: dict[str, list] = {}
    for item in candidates:
        parent = item[1].parent.as_posix()
        groups.setdefault(parent, []).append(item)

    ordered: list = []
    for parent in sorted(groups, key=lambda p: (p != ".", p.casefold(), p)):
        items = sorted(
            groups[parent],
            key=lambda it: _rank_key(sort_by, it[0], it[1].as_posix(), it[2], it[3]),
        )
        ordered.extend(items[:limit] if limit else items)

    if sort_by == SORT_PATH:
        ordered.sort(key=lambda it: (it[1].as_posix().casefold(), it[1].as_posix()))

    return [str(item[0]) for item in ordered]

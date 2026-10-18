"""自动识别表头区与数据区（启发式规则）。

规则来自 M1 技术方案 5.2：
1. 表头行：从第 1 行往下，找第一行「非空文本占比 ≥ 0.6 且下方 2 行连续非空」。
2. 表头区右边界 = 表头行最后一个非空列。
3. 数据区：表头行下一行开始，向下直到连续 3 行空行为止；右边界 = 表头右边界。

识别结果只做「建议」，始终允许用户手动覆盖。
"""
from typing import Any

from .models import Region, SheetData

TEXT_RATIO_THRESHOLD = 0.6
EMPTY_RUN_LIMIT = 3
LABEL_TEXT_RATIO = 0.8


def _cell_value(cell) -> bool:
    """单元格是否非空（None 与空字符串都视为空）。"""
    return cell is not None and str(cell).strip() != ""


def _row_non_empty(row: list) -> list:
    return [c for c in row if _cell_value(c)]


def _row_non_empty_count(row: list) -> int:
    return len(_row_non_empty(row))


def _row_text_ratio(row: list) -> float:
    """非空单元格中文本占比。空行返回 0.0。"""
    cells = _row_non_empty(row)
    if not cells:
        return 0.0
    return sum(1 for c in cells if isinstance(c, str)) / len(cells)


def _find_header_row(grid: list[list]) -> int | None:
    nrows = len(grid)
    for r in range(nrows):
        if _row_text_ratio(grid[r]) < TEXT_RATIO_THRESHOLD:
            continue
        # 下方 2 行连续非空（最后一行允许只要求 1 行）
        if r + 1 >= nrows or _row_non_empty_count(grid[r + 1]) == 0:
            continue
        if r + 2 < nrows and _row_non_empty_count(grid[r + 2]) == 0:
            continue
        return r
    # 回退：取第一行非空行作为表头
    for r in range(nrows):
        if _row_non_empty_count(grid[r]) > 0:
            return r
    return None


def _header_right_boundary(row: list) -> int:
    """表头行最后一个非空列的 1-based 列号（无则返回 1）。"""
    right = 1
    for c in range(len(row) - 1, -1, -1):
        if _cell_value(row[c]):
            right = c + 1
            break
    return right


def _find_data_bottom(grid: list[list], start: int) -> int:
    """从 start（0-based，表头行下一行）向下扫描，返回数据区底部 1-based 行号；-1 表示到末尾。"""
    empty_run = 0
    for r in range(start, len(grid)):
        if _row_non_empty_count(grid[r]) == 0:
            empty_run += 1
            if empty_run >= EMPTY_RUN_LIMIT:
                return r - EMPTY_RUN_LIMIT + 1  # 1-based，最后一行数据
        else:
            empty_run = 0
    return -1


def detect(sheet: SheetData) -> tuple[Region, Region]:
    """识别表头区与数据区，返回 (header, data) 两个 Region（1-based，含边界）。"""
    grid = sheet.grid
    if not grid:
        return Region(1, 1, 1, 1), Region(2, 1, -1, 1)

    header_row = _find_header_row(grid)
    if header_row is None:
        return Region(1, 1, 1, 1), Region(2, 1, -1, 1)

    right = _header_right_boundary(grid[header_row])

    header = Region(header_row + 1, 1, header_row + 1, right)
    data_top = header_row + 2  # 1-based，表头行下一行
    data_bottom = _find_data_bottom(grid, header_row + 1)
    data = Region(data_top, 1, data_bottom, right)
    return header, data


# --------------------------------------------------------------------------
# 表单（标签:值 成对）识别
# --------------------------------------------------------------------------

def clean_label(s: str) -> str:
    """清理标签：去首尾空白、去末尾全角/半角冒号。"""
    return s.strip().rstrip("：:")


def _is_label_column(col_vals: list) -> bool:
    """判断一列是否为标签列：非空单元格中字符串占比高且非空数足够。"""
    non_empty = [v for v in col_vals if _cell_value(v)]
    if len(non_empty) < 2:
        return False
    text_count = sum(1 for v in non_empty if isinstance(v, str))
    return text_count / len(non_empty) >= LABEL_TEXT_RATIO


def detect_form_pairs_pos(sheet: SheetData) -> list[tuple[str, int, int, int, int]]:
    """扫描整张表，返回带位置的 (标签, 标签行, 标签列, 值行, 值列)，均为 1-based。

    规则同 detect_form_pairs：先识别「标签列」（该列文本占比高），
    再把每个标签文本单元格与其右邻值配对。适用于「标签:值」成对的表单。
    """
    grid = sheet.grid
    if not grid:
        return []
    max_col = max(len(row) for row in grid)
    label_cols = {
        c for c in range(max_col)
        if _is_label_column([row[c] if c < len(row) else None for row in grid])
    }
    pairs: list[tuple[str, int, int, int, int]] = []
    for r, row in enumerate(grid):
        for c in range(max_col):
            if c not in label_cols:
                continue
            cell = row[c] if c < len(row) else None
            if not isinstance(cell, str) or not _cell_value(cell):
                continue
            right = row[c + 1] if c + 1 < len(row) else None
            if _cell_value(right):
                pairs.append((clean_label(cell), r + 1, c + 1, r + 1, c + 2))
    return pairs


def detect_form_pairs(sheet: SheetData) -> list[tuple[str, Any]]:
    """扫描整张表，返回有序 (标签, 值) 列表，标签已清理。"""
    grid = sheet.grid
    out: list[tuple[str, Any]] = []
    for label, _lr, _lc, vr, vc in detect_form_pairs_pos(sheet):
        v = grid[vr - 1][vc - 1] if vr - 1 < len(grid) and vc - 1 < len(grid[vr - 1]) else None
        out.append((label, v))
    return out

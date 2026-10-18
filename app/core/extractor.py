"""按模板抽取单个文件 → 多张结果表。

流程：遍历 output_tables → 匹配 sheet → 按字段映射取值（表单：标签:值）。
"""
from typing import Any

from .models import ExtractTemplate, ResultTable, SheetData
from .detector import detect_form_pairs
from .reader import find_sheet


def _cell(grid: list[list], r: int, c: int):
    """取 grid[r][c]（0-based），越界返回 None。"""
    if 0 <= r < len(grid):
        row = grid[r]
        if 0 <= c < len(row):
            return row[c]
    return None


def _is_empty(v) -> bool:
    return v is None or str(v).strip() == ""


def _convert(value, value_type: str):
    """按字段类型做轻量转换。number 转 float（失败保留原值），其余原样。"""
    if value is None or value_type != "number":
        return value
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return value


# --------------------------------------------------------------------------
# 单文件抽取
# --------------------------------------------------------------------------

def extract_file(sheets: list[SheetData],
                 template: ExtractTemplate) -> dict[str, ResultTable]:
    """按模板抽取单个文件，返回 {表名: ResultTable}。"""
    result: dict[str, ResultTable] = {}
    for ot in template.output_tables:
        sheet = find_sheet(sheets, ot.sheet.sheet_keyword)
        result[ot.name] = _extract_form(sheet, ot)
    return result


def _extract_form(sheet: SheetData | None, ot) -> ResultTable:
    """表单模式：按「标签:值」配对取单行多列。

    - 手动配对的字段（含 value_row/value_col）：按值位置直接读单元格。
    - 扫描得到的字段（只有 key=标签文本）：按标签文本从自动识别结果里取值。
    - 没有配置字段时：输出全部自动识别到的标签:值。
    """
    if sheet is None:
        return ResultTable(name=ot.name, columns=[], rows=[])

    pairs = detect_form_pairs(sheet)
    label_to_val = dict(pairs)

    columns: list[str] = []
    values: list[Any] = []

    if not ot.fields:
        columns += [label for label, _ in pairs]
        values += [v for _, v in pairs]
        return ResultTable(name=ot.name, columns=columns, rows=[values])

    for f in ot.fields:
        columns.append(f.target)
        if f.value_row is not None and f.value_col is not None:
            values.append(_convert(_cell(sheet.grid, f.value_row - 1, f.value_col - 1),
                                   f.value_type))
        else:
            values.append(_convert(label_to_val.get(f.key), f.value_type))
    return ResultTable(name=ot.name, columns=columns, rows=[values])

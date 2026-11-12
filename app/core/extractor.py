"""按模板抽取单个文件 → 多张结果表。

流程：遍历 output_tables → 匹配 sheet → 按字段映射取值（表单：标签:值）。
`source="filename"` 的字段不读单元格，而是从文件名（没有汉字时回退到所在
文件夹名）里提取汉字作为「对象名」。
"""
import re
from pathlib import Path
from typing import Any

from .align import align_sheet
from .models import ExtractTemplate, ResultTable, SheetData
from .detector import detect_form_pairs
from .reader import find_sheet

_SOURCE_FILENAME = "filename"
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")


def _chinese_only(text: str) -> str:
    """只保留汉字（去掉英文、数字、标点、空白）。"""
    return "".join(_CJK_RUN.findall(text or ""))


def object_name_from_path(path: str | None) -> str:
    """从路径取「对象名」：优先文件名的汉字；文件名没有汉字时用所在文件夹名。

    例：`…/X企业2024.xlsx` → 「企业」；
        `…/采购部/2024.xlsx` → 「采购部」。
    """
    if not path:
        return ""
    p = Path(path)
    stem = p.stem if p.suffix else p.name
    name = _chinese_only(stem)
    if name:
        return name
    return _chinese_only(p.parent.name)


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

def extract_file(sheets: list[SheetData], template: ExtractTemplate,
                 path: str | None = None,
                 notes: list[str] | None = None) -> dict[str, ResultTable]:
    """按模板抽取单个文件，返回 {表名: ResultTable}。

    `path` 供 `source="filename"` 的字段取对象名；`notes` 非空时追加
    每张表的坐标对齐说明（供界面日志展示）。
    """
    result: dict[str, ResultTable] = {}
    for ot in template.output_tables:
        sheet = find_sheet(sheets, ot.sheet.sheet_keyword)
        result[ot.name] = _extract_form(sheet, ot, path, notes=notes)
    return result


def _same_type_groups(fields) -> list[list]:
    """把同一列、同一标签格的字段归为一组「同类数据行」。

    横向表格里，同一个表头（label_row/label_col）会对应多行数据
    （如 项目名称1/2/3），它们取值列相同、取值行递增。只有成组（≥2 个）
    才视为同类行，避免把普通标签（如单位名称）也向下扩展。
    """
    groups: dict[tuple, list] = {}
    for f in fields:
        if (f.value_row is None or f.value_col is None
                or f.label_row is None or f.label_col is None):
            continue
        key = (f.label_row, f.label_col, f.value_col)
        groups.setdefault(key, []).append(f)
    return [sorted(g, key=lambda x: x.value_row)
            for g in groups.values() if len(g) >= 2]


def _overflow_text(sheet: SheetData, group: list,
                   row_delta: int = 0, col_delta: int = 0) -> str:
    """从组内最后一个取值行继续向下读同列，把超出的内容编号后换行堆叠。

    终止条件：同列遇到空单元格。序号按数据行在表格中的位置连续编号
    （如模板已覆盖第 1~3 项，第 4 行起输出「4. …」）。
    坐标按 (row_delta, col_delta) 修正到当前文件的实际位置。
    """
    first_row = group[0].value_row + row_delta
    col = group[-1].value_col + col_delta
    lines: list[str] = []
    r = group[-1].value_row + row_delta + 1
    while r <= sheet.max_row:
        v = _cell(sheet.grid, r - 1, col - 1)
        if _is_empty(v):
            break
        lines.append(f"{r - first_row + 1}. {v}")
        r += 1
    return "\n".join(lines)


def _extract_form(sheet: SheetData | None, ot,
                  path: str | None = None,
                  notes: list[str] | None = None) -> ResultTable:
    """表单模式：按「标签:值」配对取单行多列。

    - 手动配对的字段（含 value_row/value_col）：按值位置直接读单元格。
    - 扫描得到的字段（只有 key=标签文本）：按标签文本从自动识别结果里取值。
    - 没有配置字段时：输出全部自动识别到的标签:值。
    - 同类行（横向表格同一列的多个字段）超出模板覆盖行仍有内容时，
      追加到该组最后一个字段的单元格里，换行堆叠并加序号。
    - 源文件删除了顶部行/列时，用模板里的标签锚点自动修正整表偏移。
    """
    if sheet is None:
        return ResultTable(name=ot.name, columns=[], rows=[])

    alignment = align_sheet(sheet, ot.fields)
    row_delta, col_delta = alignment.offset
    if notes is not None and ot.fields:
        if alignment.shifted and alignment.reliable:
            notes.append(
                f"「{ot.name}」按标签对齐：行 {row_delta:+d}，列 {col_delta:+d}"
                f"（{alignment.votes}/{alignment.anchor_count} 个标签命中）")
        elif alignment.anchor_count and not alignment.reliable:
            notes.append(
                f"「{ot.name}」疑似版式变化，未能可靠对齐"
                f"（{alignment.votes}/{alignment.anchor_count} 个标签命中），"
                "已按模板原位置读取")

    pairs = detect_form_pairs(sheet)
    label_to_val = dict(pairs)

    columns: list[str] = []
    values: list[Any] = []

    if not ot.fields:
        columns += [label for label, _ in pairs]
        values += [v for _, v in pairs]
        return ResultTable(name=ot.name, columns=columns, rows=[values])

    overflow = {id(g[-1]): _overflow_text(sheet, g, row_delta, col_delta)
                for g in _same_type_groups(ot.fields)}
    for f in ot.fields:
        columns.append(f.target)
        if f.source == _SOURCE_FILENAME:
            value = object_name_from_path(path)
        elif f.value_row is not None and f.value_col is not None:
            value = _convert(
                _cell(sheet.grid, f.value_row - 1 + row_delta,
                      f.value_col - 1 + col_delta),
                f.value_type)
        else:
            value = _convert(label_to_val.get(f.key), f.value_type)
        extra = overflow.get(id(f))
        if extra:
            value = f"{value}\n{extra}" if not _is_empty(value) else extra
        values.append(value)
    return ResultTable(name=ot.name, columns=columns, rows=[values])

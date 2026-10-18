"""多文件合并 + 清洗 + 排序。

同表名结果纵向拼接，列名取并集（以首个出现的顺序为准），
清洗 trim / 去空行，每张结果表独立排序（默认按第一列）。
"""
from typing import Any

from .models import SEQ_COLUMN, ResultTable


def _is_empty(v) -> bool:
    return v is None or str(v).strip() == ""


def _clean_value(v):
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _row_is_empty(row: list) -> bool:
    return all(_is_empty(v) for v in row)


def _safe_sort_key(v):
    """None 排最后；数字按数值，字符串按字典序。"""
    if v is None:
        return (2, "")
    if isinstance(v, (int, float)):
        return (0, v, "")
    return (1, 0, str(v))


def _union_columns(tables: list[ResultTable]) -> list[str]:
    seen: list[str] = []
    for t in tables:
        for c in t.columns:
            if c not in seen:
                seen.append(c)
    return seen


def _align_row(row: list, columns: list[str], table_columns: list[str]) -> list:
    """把某张表的行按并集列顺序对齐，缺失列补 None。"""
    mapping = {c: i for i, c in enumerate(table_columns)}
    return [row[mapping[c]] if c in mapping and mapping[c] < len(row) else None
            for c in columns]


def aggregate(files_results: list[dict[str, ResultTable]]) -> dict[str, ResultTable]:
    """合并多个文件的抽取结果，返回 {表名: ResultTable}。

    files_results：每个元素是一个文件的 {表名: ResultTable}（即 extract_file 的输出）。
    每张表按第一列排序，最后前置序号列。
    """
    table_names: list[str] = []
    for fr in files_results:
        for name in fr:
            if name not in table_names:
                table_names.append(name)

    merged: dict[str, ResultTable] = {}
    for name in table_names:
        tables = [fr[name] for fr in files_results if name in fr]
        columns = _union_columns(tables)

        rows: list[list[Any]] = []
        for t in tables:
            for row in t.rows:
                cleaned = [_clean_value(v) for v in _align_row(row, columns, t.columns)]
                if _row_is_empty(cleaned):
                    continue
                rows.append(cleaned)

        if columns:
            rows.sort(key=lambda r: _safe_sort_key(r[0]))

        # 第一列加序号（1 起），排在排序后的最终行序上。
        seq_rows = [[i + 1] + row for i, row in enumerate(rows)]
        merged[name] = ResultTable(
            name=name, columns=[SEQ_COLUMN] + columns, rows=seq_rows)
    return merged

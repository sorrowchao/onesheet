"""核心数据模型。

统一内部表示，屏蔽 xls/xlsx 差异。
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Region:
    """区域（1-based，含边界）。bottom/right 为 -1 表示到末尾。"""
    top: int
    left: int
    bottom: int
    right: int


@dataclass
class SheetData:
    """一个 sheet 的完整快照。grid[r][c]，r/c 从 0 开始。"""
    name: str
    grid: list[list[Any]]
    merged: list[Region]
    max_row: int
    max_col: int


@dataclass
class FieldMapping:
    """一条字段映射规则。

    标签 → 值（label_row/label_col + value_row/value_col）。
    """
    target: str = ""                 # 输出列名（= 标签文本）
    source: str = "kv"               # kv（标签:值字段）
    is_key: bool = False             # 主键：反向写入时「匹配字段」默认只勾它
    key: Optional[Any] = None        # 标签文本（扫描字段按此匹配）
    value_type: str = "text"         # text | number | date
    label_row: Optional[int] = None  # 标签位置（1-based，手动配对时记录）
    label_col: Optional[int] = None
    value_row: Optional[int] = None  # 值位置（1-based，按此读取）
    value_col: Optional[int] = None  # 值列


@dataclass
class SheetConfig:
    """结果表绑定的 sheet 配置（只需 sheet 匹配）。"""
    sheet_keyword: str = ""          # sheet 名匹配关键字（空=用第一个 sheet）


@dataclass
class OutputTable:
    """一张结果表。"""
    name: str = ""
    sheet: SheetConfig = field(default_factory=SheetConfig)
    fields: list[FieldMapping] = field(default_factory=list)


@dataclass
class ExtractTemplate:
    """抽取模板（多 sheet → 多结果表）。"""
    name: str = ""
    version: int = 2
    output_tables: list[OutputTable] = field(default_factory=list)


@dataclass
class ResultTable:
    """一张抽取/汇总后的结果表。"""
    name: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)


# 汇总结果第一列保留给序号列（反向写入时排除该列，不参与匹配/回填）。
SEQ_COLUMN = "序号"


def duplicate_value_positions(output_tables: list[OutputTable]) -> list[str]:
    """检查同一结果表内是否有多个字段指向同一个取值单元格。

    返回人类可读的警告列表（空列表表示没有重复）。
    """
    warnings: list[str] = []
    for ot in output_tables:
        by_pos: dict[tuple[int, int], list[str]] = {}
        for f in ot.fields:
            if f.value_row is None or f.value_col is None:
                continue
            pos = (f.value_row, f.value_col)
            name = f.target or str(f.key or "") or "（未命名）"
            by_pos.setdefault(pos, []).append(name)
        for (row, col), names in by_pos.items():
            if len(names) > 1:
                warnings.append(
                    f"结果表「{ot.name}」：字段 {'、'.join(names)} "
                    f"都指向第 {row} 行第 {col} 列")
    return warnings


def dedupe_targets(fields: list[FieldMapping]) -> None:
    """标签重名自动加数字后缀（只改 target 输出列名，不改 key 匹配标签）。

    首个出现的标签保留原样，后续同名依次追加 2、3、4……
    例如 [「金额」「金额」「金额」] → [「金额」「金额2」「金额3」]。
    """
    used: set[str] = set()
    for f in fields:
        base = (f.target or "").strip()
        if not base:
            continue
        candidate = base
        n = 2
        while candidate in used:
            candidate = f"{base}{n}"
            n += 1
        f.target = candidate
        used.add(candidate)

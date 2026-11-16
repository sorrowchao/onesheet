"""核心数据模型。

统一内部表示，屏蔽 xls/xlsx 差异。
"""
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# 校验规则类型：必填 / 数值范围 / 唯一性 / 合计等式。
VALID_RULE_TYPES = ("required", "number", "unique", "sum")

# 分析准备（派生列 / 清洗去重 / 分组汇总 / 描述统计）。
AGG_FUNCS = ("sum", "count", "avg", "min", "max")
STAT_METRICS = ("count", "sum", "avg", "median", "min", "max", "std")
FILTER_OPS = ("not_empty", "empty", "eq", "ne", "gt", "ge", "lt", "le",
              "contains", "not_contains")


def is_empty(v) -> bool:
    """单元格是否为空（None 或纯空白字符串）。"""
    return v is None or (isinstance(v, str) and v.strip() == "")


def to_number(v):
    """把单元格值转成 float；无法转换返回 None。bool 不当作数字。

    带千分位逗号（半角/全角）的数值字符串会被识别；空串返回 None。
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace("，", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


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
    source: str = "kv"               # kv（标签:值字段）| filename（从文件名/文件夹名取汉字）
    is_key: bool = False             # 主键：反向写入时「匹配字段」默认只勾它
    key: Optional[Any] = None        # 标签文本（扫描字段按此匹配）
    value_type: str = "text"         # text | number | date
    label_row: Optional[int] = None  # 标签位置（1-based，手动配对时记录）
    label_col: Optional[int] = None
    value_row: Optional[int] = None  # 值位置（1-based，按此读取）
    value_col: Optional[int] = None  # 值列


@dataclass
class ValidationRule:
    """一条数据校验规则（作用于结果表的列）。

    type:
      - required：列不可为空；
      - number：列必须是数字，可选 min/max 范围；
      - unique：列组合的取值必须唯一（非空键）；
      - sum：target 列应等于 columns 各列之和（允许 tolerance 误差）。
    """
    type: str = "required"
    columns: list[str] = field(default_factory=list)
    target: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    tolerance: float = 0.0


@dataclass
class SheetConfig:
    """结果表绑定的 sheet 配置（只需 sheet 匹配）。"""
    sheet_keyword: str = ""          # sheet 名匹配关键字（空=用第一个 sheet）


@dataclass
class DerivedColumn:
    """派生列：由公式计算出的新列。"""
    target: str = ""          # 新列名
    formula: str = ""         # "[基本工资] + [绩效]"


@dataclass
class RowFilter:
    """清洗阶段的一条行筛选条件。"""
    column: str = ""
    op: str = "not_empty"     # FILTER_OPS
    value: str = ""


@dataclass
class CleanupSpec:
    """清洗 / 去重配置。"""
    trim: bool = False
    dedupe: bool = False
    dedupe_columns: list[str] = field(default_factory=list)  # 空=全部列（不含序号）
    filters: list[RowFilter] = field(default_factory=list)


@dataclass
class AggregateSpec:
    """分组汇总中的一条聚合。"""
    column: str = ""
    func: str = "sum"         # AGG_FUNCS
    target: str = ""          # 输出列名，空=自动命名 func(column)


@dataclass
class GroupBySpec:
    """分组汇总配置。"""
    enabled: bool = False
    group_columns: list[str] = field(default_factory=list)
    aggregations: list[AggregateSpec] = field(default_factory=list)


@dataclass
class StatsSpec:
    """描述统计配置。"""
    enabled: bool = False
    columns: list[str] = field(default_factory=list)   # 空=全部数值列
    metrics: list[str] = field(default_factory=list)   # 空=全部


@dataclass
class OutputTable:
    """一张结果表。"""
    name: str = ""
    sheet: SheetConfig = field(default_factory=SheetConfig)
    fields: list[FieldMapping] = field(default_factory=list)
    validations: list[ValidationRule] = field(default_factory=list)
    derived_columns: list[DerivedColumn] = field(default_factory=list)
    cleanup: CleanupSpec = field(default_factory=CleanupSpec)
    group_by: GroupBySpec = field(default_factory=GroupBySpec)
    stats: StatsSpec = field(default_factory=StatsSpec)


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


@dataclass
class ValidationIssue:
    """一条校验问题。row 为 ResultTable.rows 的 0 基下标，-1 表示表级问题。"""
    table: str = ""
    row: int = -1
    column: str = ""
    rule_type: str = ""
    message: str = ""


# 汇总结果第一列保留给序号列（反向写入时排除该列，不参与匹配/回填）。
SEQ_COLUMN = "序号"


def norm_key(v) -> str:
    """键值归一化，用于跨格式/类型比对，避免「同一值因存储/类型不同而匹配不上」。

    - None → ""
    - 数值：整型浮点去掉小数位（34.0 → 34）；NaN 等特殊值原样
    - 字符串：去首尾空白；带千分位逗号或小数的数值字符串归一为数值形式
      （"1,234" → "1234"、"34.0" → "34"）；纯数字文本（如 "007"）保留原样以保住前导零
    """
    if v is None:
        return ""
    if isinstance(v, float):
        if v != v:  # NaN
            return "nan"
        if v.is_integer():
            return str(int(v))
        return str(v)
    if isinstance(v, int):
        return str(v)
    s = str(v).strip()
    if s == "":
        return ""
    # 只有含千分位逗号或小数点时才尝试按数值归一，
    # 避免把 "007" 之类的文本 ID 误压成 7。
    if "," in s or "，" in s or "." in s:
        t = s.replace(",", "").replace("，", "")
        try:
            f = float(t)
            if f.is_integer():
                return str(int(f))
            return str(f)
        except ValueError:
            return s
    return s


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


_TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)$")
_FULLWIDTH_DIGITS = "０１２３４５６７８９"


def _split_numbered(name: str) -> tuple[str, Optional[int], str]:
    """把「项目名称2」拆成 ("项目名称", 2, "2")；整串都是数字时不拆（原名, None, ""）。

    第三个返回值是原始数字文本，用于保留编号风格（如 "02" 补零、"２" 全角）。
    """
    m = _TRAILING_NUMBER.match(name)
    if m and m.group(1):
        return m.group(1), int(m.group(2)), m.group(2)
    return name, None, ""


def _format_number(n: int, raw_suffix: str) -> str:
    """按家族已有的编号风格输出：补零位数、全角/半角。"""
    width = len(raw_suffix)
    digits = str(n).zfill(width)
    if any(ch in _FULLWIDTH_DIGITS for ch in raw_suffix):
        return "".join(chr(ord("０") + int(d)) for d in digits)
    return digits


def _next_numbered(stem: str, families: dict[str, tuple[int, str]],
                   used: set[str]) -> str:
    """在编号家族「stem1/stem2…」后取下一个未占用的名字。"""
    value, raw = families.get(stem, (1, ""))
    n = value + 1
    while True:
        candidate = f"{stem}{_format_number(n, raw)}"
        if candidate not in used:
            return candidate
        n += 1


def dedupe_targets(fields: list[FieldMapping]) -> None:
    """标签重名自动加数字后缀（只改 target 输出列名，不改 key 匹配标签）。

    任意「名称 + 尾部数字」都按同一家族处理，不限具体名称：
    首个出现的标签保留原样，后续同名依次追加 2、3、4……
    例如 [「金额」「金额」「金额」] → [「金额」「金额2」「金额3」]。

    已存在编号家族时接着家族编号，而不是从裸名重新开始：
    [「项目名称1」「项目名称2」「项目名称」] → [「项目名称1」「项目名称2」「项目名称3」]；
    [「项目名称1」「项目名称2」「项目名称1」] → [「项目名称1」「项目名称2」「项目名称3」]。
    家族原有编号风格会保留：[「股东01」「股东02」「股东」] → 「股东03」；
    [「费用１」「费用２」「费用」] → 「费用３」。
    """
    used: set[str] = set()
    families: dict[str, tuple[int, str]] = {}   # 家族名 -> (最大编号, 该编号原文)
    for f in fields:
        base = (f.target or "").strip()
        if not base:
            continue
        stem, num, raw = _split_numbered(base)
        if base in used or (num is None and stem in families):
            # 重名，或裸名遇到同名编号家族（如 项目名称1/2）——沿用家族继续编号；
            # 用户显式写的编号名（如 项目名称3）即使家族已存在也保留原样。
            candidate = _next_numbered(stem, families, used)
        else:
            candidate = base
        f.target = candidate
        used.add(candidate)
        cand_stem, cand_num, cand_raw = _split_numbered(candidate)
        if cand_num is None:
            families.setdefault(cand_stem, (1, ""))
        elif cand_num > families.get(cand_stem, (0, ""))[0]:
            families[cand_stem] = (cand_num, cand_raw)

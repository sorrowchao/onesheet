"""分析准备（纯逻辑，无 Qt）。

在抽取汇总之后对结果表做进一步加工：清洗去重、派生列、分组汇总、
描述统计。所有变换都返回新的 ``ResultTable``，不修改输入。
"""
import re
import statistics

from .formula import FormulaError, compile_formula, evaluate
from .models import (AGG_FUNCS, FILTER_OPS, SEQ_COLUMN, STAT_METRICS,
                     AggregateSpec, CleanupSpec, DerivedColumn, GroupBySpec,
                     ResultTable, RowFilter, StatsSpec, is_empty, norm_key,
                     to_number)

GROUP_SUFFIX = "（分组汇总）"
STATS_SUFFIX = "（描述统计）"

AGG_LABELS = {"sum": "合计", "count": "计数", "avg": "平均",
              "min": "最小值", "max": "最大值"}
STAT_LABELS = {"count": "计数", "sum": "合计", "avg": "平均",
               "median": "中位数", "min": "最小值", "max": "最大值",
               "std": "标准差"}

_FILTER_LABELS = {
    "not_empty": "非空", "empty": "为空", "eq": "等于", "ne": "不等于",
    "gt": "大于", "ge": "大于等于", "lt": "小于", "le": "小于等于",
    "contains": "包含", "not_contains": "不包含",
}
_NUMERIC_OPS = ("gt", "ge", "lt", "le")
_COMPARE = {
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
}


# --------------------------------------------------------------------------
# 克隆助手（配置面板 / 对话框共用）
# --------------------------------------------------------------------------
def clone_derived(d: DerivedColumn) -> DerivedColumn:
    return DerivedColumn(target=d.target, formula=d.formula)


def clone_filter(f: RowFilter) -> RowFilter:
    return RowFilter(column=f.column, op=f.op, value=f.value)


def clone_cleanup(c: CleanupSpec) -> CleanupSpec:
    return CleanupSpec(
        trim=c.trim, dedupe=c.dedupe,
        dedupe_columns=list(c.dedupe_columns),
        filters=[clone_filter(f) for f in c.filters])


def clone_aggregate(a: AggregateSpec) -> AggregateSpec:
    return AggregateSpec(column=a.column, func=a.func, target=a.target)


def clone_group_by(g: GroupBySpec) -> GroupBySpec:
    return GroupBySpec(
        enabled=g.enabled, group_columns=list(g.group_columns),
        aggregations=[clone_aggregate(a) for a in g.aggregations])


def clone_stats(s: StatsSpec) -> StatsSpec:
    return StatsSpec(enabled=s.enabled, columns=list(s.columns),
                     metrics=list(s.metrics))


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def _copy_table(t: ResultTable) -> ResultTable:
    return ResultTable(name=t.name, columns=list(t.columns),
                       rows=[list(r) for r in t.rows])


def _cell(row: list, col: int):
    return row[col] if 0 <= col < len(row) else None


def _ensure_len(row: list, n: int):
    if len(row) < n:
        row.extend([None] * (n - len(row)))


def _norm_num(value):
    if isinstance(value, float):
        if value != value:
            return None
        if value.is_integer():
            return int(value)
    return value


def _col_indexes(table: ResultTable) -> dict[str, int]:
    return {name: i for i, name in enumerate(table.columns)}


# --------------------------------------------------------------------------
# 清洗 / 去重
# --------------------------------------------------------------------------
def _passes_filter(value, row_filter: RowFilter) -> bool:
    op = row_filter.op
    target = row_filter.value
    if op == "not_empty":
        return not is_empty(value)
    if op == "empty":
        return is_empty(value)
    s = "" if value is None else str(value).strip()
    if op == "eq":
        return s == (target or "").strip()
    if op == "ne":
        return s != (target or "").strip()
    if op == "contains":
        return (target or "") in s
    if op == "not_contains":
        return (target or "") not in s
    if op in _NUMERIC_OPS:
        num = to_number(value)
        bound = to_number(target)
        if num is None or bound is None:
            return False
        return _COMPARE[op](num, bound)
    return True


def apply_cleanup(table: ResultTable, spec: CleanupSpec) -> ResultTable:
    """去首尾空白 → 应用行筛选 → 去重 → 需要时重排序号。"""
    out = _copy_table(table)
    if spec.trim:
        out.rows = [[v.strip() if isinstance(v, str) else v for v in row]
                    for row in out.rows]

    cols = _col_indexes(out)
    # 依次应用筛选条件，逐次过滤行。
    for f in spec.filters:
        if f.op not in FILTER_OPS or f.column not in cols:
            continue
        idx = cols[f.column]
        out.rows = [r for r in out.rows if _passes_filter(_cell(r, idx), f)]

    if spec.dedupe:
        key_idx = [cols[c] for c in (spec.dedupe_columns or [])
                   if c in cols]
        if not key_idx:
            key_idx = [i for i, c in enumerate(out.columns)
                       if c != SEQ_COLUMN]
        seen: set[tuple] = set()
        kept: list[list] = []
        for row in out.rows:
            key = tuple(norm_key(_cell(row, i)) for i in key_idx)
            if key in seen:
                continue
            seen.add(key)
            kept.append(row)
        out.rows = kept

    if len(out.rows) != len(table.rows) and out.columns[:1] == [SEQ_COLUMN]:
        for i, row in enumerate(out.rows):
            _ensure_len(row, 1)
            row[0] = i + 1
    return out


# --------------------------------------------------------------------------
# 派生列
# --------------------------------------------------------------------------
def apply_derived_columns(
        table: ResultTable,
        specs: list[DerivedColumn]) -> tuple[ResultTable, list[str]]:
    """按顺序编译/求值派生列；非法公式或未知列记警告并跳过。"""
    out = _copy_table(table)
    cols = list(out.columns)
    notes: list[str] = []
    for spec in specs or []:
        target = (spec.target or "").strip()
        if not target:
            notes.append("派生列：列名不能为空，已跳过")
            continue
        try:
            compiled = compile_formula(spec.formula, cols)
        except FormulaError as e:
            notes.append(f"派生列『{spec.target}』公式无效：{e}")
            continue
        if target in cols:
            idx = cols.index(target)
        else:
            idx = len(cols)
            cols.append(target)
        for row in out.rows:
            _ensure_len(row, idx + 1)
            values = {c: _cell(row, i) for i, c in enumerate(cols)}
            row[idx] = evaluate(compiled, values)
    out.columns = cols
    return out, notes


# --------------------------------------------------------------------------
# 分组汇总
# --------------------------------------------------------------------------
def _agg_value(func: str, cells: list):
    if func == "count":
        return sum(1 for v in cells if not is_empty(v))
    nums = []
    for v in cells:
        if is_empty(v):
            continue
        num = to_number(v)
        if num is not None:
            nums.append(num)
    if func == "sum":
        return _norm_num(sum(nums)) if nums else 0
    if not nums:
        return None
    if func == "avg":
        return _norm_num(sum(nums) / len(nums))
    if func == "min":
        return _norm_num(min(nums))
    if func == "max":
        return _norm_num(max(nums))
    return None


def _aggregate_name(agg: AggregateSpec) -> str:
    if (agg.target or "").strip():
        return agg.target.strip()
    label = AGG_LABELS.get(agg.func, agg.func)
    return f"{label}({agg.column})"


def build_group_by(table: ResultTable,
                   spec: GroupBySpec) -> ResultTable | None:
    """按分组列聚合；未启用或无有效分组列返回 None。"""
    if not spec.enabled:
        return None
    cols = _col_indexes(table)
    group_cols = [c for c in spec.group_columns if c in cols]
    if not group_cols:
        return None
    aggs = [a for a in spec.aggregations
            if a.column in cols and a.func in AGG_FUNCS]

    out_columns: list[str] = list(group_cols)
    used_names = set(out_columns)
    out_aggs: list[tuple[AggregateSpec, str]] = []
    for a in aggs:
        name = _aggregate_name(a)
        base = name
        n = 2
        while name in used_names:
            name = f"{base}{n}"
            n += 1
        used_names.add(name)
        out_columns.append(name)
        out_aggs.append((a, name))

    group_idx = [cols[c] for c in group_cols]
    groups: dict[tuple, tuple[list, list[list]]] = {}
    order: list[tuple] = []
    for row in table.rows:
        key = tuple(norm_key(_cell(row, i)) for i in group_idx)
        if key not in groups:
            display = [_cell(row, i) for i in group_idx]
            groups[key] = (display, [])
            order.append(key)
        groups[key][1].append(row)

    out_rows: list[list] = []
    for key in order:
        display, members = groups[key]
        out_row = list(display)
        for a, _name in out_aggs:
            idx = cols[a.column]
            cells = [_cell(r, idx) for r in members]
            out_row.append(_agg_value(a.func, cells))
        out_rows.append(out_row)

    return ResultTable(
        name=f"{table.name}{GROUP_SUFFIX}", columns=out_columns, rows=out_rows)


# --------------------------------------------------------------------------
# 描述统计
# --------------------------------------------------------------------------
def _numeric_values(table: ResultTable, idx: int) -> list[float]:
    out: list[float] = []
    for row in table.rows:
        v = _cell(row, idx)
        if is_empty(v):
            continue
        num = to_number(v)
        if num is not None:
            out.append(num)
    return out


def build_stats(table: ResultTable, spec: StatsSpec) -> ResultTable | None:
    """每个数值列输出一组统计指标；未启用返回 None。"""
    if not spec.enabled:
        return None
    metrics = [m for m in (spec.metrics or STAT_METRICS)
               if m in STAT_METRICS]
    if not metrics:
        metrics = list(STAT_METRICS)
    cols = _col_indexes(table)

    if spec.columns:
        candidates = [c for c in spec.columns if c in cols]
    else:
        candidates = [c for c in table.columns if c != SEQ_COLUMN]

    out_rows: list[list] = []
    for name in candidates:
        if name == SEQ_COLUMN:
            continue
        nums = _numeric_values(table, cols[name])
        if not nums:
            continue
        row: list = [name]
        for m in metrics:
            row.append(_metric_value(m, nums))
        out_rows.append(row)

    columns = ["列名"] + [STAT_LABELS[m] for m in metrics]
    return ResultTable(
        name=f"{table.name}{STATS_SUFFIX}", columns=columns, rows=out_rows)


def _metric_value(metric: str, nums: list[float]):
    if metric == "count":
        return len(nums)
    if metric == "sum":
        return _norm_num(sum(nums))
    if metric == "avg":
        return _norm_num(sum(nums) / len(nums))
    if metric == "median":
        return _norm_num(statistics.median(nums))
    if metric == "min":
        return _norm_num(min(nums))
    if metric == "max":
        return _norm_num(max(nums))
    if metric == "std":
        if len(nums) < 2:
            return 0
        return _norm_num(statistics.pstdev(nums))
    return None


# --------------------------------------------------------------------------
# 编排
# --------------------------------------------------------------------------
def _cleanup_active(spec: CleanupSpec) -> bool:
    return bool(spec.trim or spec.dedupe or spec.filters)


def table_has_config(ot) -> bool:
    return bool(ot.derived_columns or _cleanup_active(ot.cleanup)
                or ot.group_by.enabled or ot.stats.enabled)


def _generated_name(name: str, bases: list[str]) -> bool:
    for base in bases:
        for suffix in (GROUP_SUFFIX, STATS_SUFFIX):
            if re.fullmatch(re.escape(f"{base}{suffix}") + r"\d*", name):
                return True
    return False


def _unique_table_name(table: ResultTable, used: set[str]) -> ResultTable:
    if table.name not in used:
        return table
    base = table.name
    n = 2
    while f"{base}{n}" in used:
        n += 1
    table.name = f"{base}{n}"
    return table


def apply_analysis(tables: dict[str, ResultTable],
                   template) -> tuple[dict[str, ResultTable], list[str]]:
    """对全部结果表应用分析配置，返回 (新结果字典, 日志说明)。"""
    notes: list[str] = []
    bases = [ot.name for ot in template.output_tables]
    # 先丢弃上次生成的分组/统计表，保证重复运行不叠加。
    result: dict[str, ResultTable] = {
        name: t for name, t in tables.items()
        if not _generated_name(name, bases)
    }
    if not any(table_has_config(ot) for ot in template.output_tables):
        return result, notes

    generated: list[ResultTable] = []
    used = set(result.keys())
    for ot in template.output_tables:
        table = result.get(ot.name)
        if table is None:
            continue
        try:
            processed = table
            if _cleanup_active(ot.cleanup):
                processed = apply_cleanup(processed, ot.cleanup)
            if ot.derived_columns:
                processed, dnotes = apply_derived_columns(
                    processed, ot.derived_columns)
                notes.extend(dnotes)
            result[ot.name] = processed
        except Exception as e:  # noqa: BLE001 - 单表失败不影响其余
            notes.append(f"分析『{ot.name}』失败：{e}")
            continue

        try:
            grouped = build_group_by(processed, ot.group_by)
            if grouped is not None:
                grouped = _unique_table_name(grouped, used)
                used.add(grouped.name)
                generated.append(grouped)
                notes.append(f"分组汇总『{ot.name}』：{len(grouped.rows)} 行")
        except Exception as e:  # noqa: BLE001
            notes.append(f"分组汇总『{ot.name}』失败：{e}")

        try:
            stats = build_stats(processed, ot.stats)
            if stats is not None:
                stats = _unique_table_name(stats, used)
                used.add(stats.name)
                generated.append(stats)
                notes.append(f"描述统计『{ot.name}』：{len(stats.rows)} 行")
        except Exception as e:  # noqa: BLE001
            notes.append(f"描述统计『{ot.name}』失败：{e}")

    for t in generated:
        result[t.name] = t
    return result, notes

"""模板 dataclass 与 JSON 互转 + 校验。"""
from dataclasses import asdict

from app.core.formula import extract_refs, syntax_ok
from app.core.models import (AGG_FUNCS, FILTER_OPS, STAT_METRICS,
                             VALID_RULE_TYPES, AggregateSpec, CleanupSpec,
                             DerivedColumn, ExtractTemplate, FieldMapping,
                             GroupBySpec, OutputTable, RowFilter, SheetConfig,
                             StatsSpec, ValidationRule)

VALID_SOURCE = {"kv", "filename"}


# --------------------------------------------------------------------------
# dict -> dataclass
# --------------------------------------------------------------------------

def field_from_dict(d: dict) -> FieldMapping:
    return FieldMapping(
        target=d.get("target", ""),
        source=d.get("source", "kv"),
        is_key=d.get("is_key", False),
        key=d.get("key"),
        value_type=d.get("value_type", "text"),
        label_row=d.get("label_row"),
        label_col=d.get("label_col"),
        value_row=d.get("value_row"),
        value_col=d.get("value_col"),
    )


def sheet_from_dict(d: dict) -> SheetConfig:
    return SheetConfig(sheet_keyword=d.get("sheet_keyword", ""))


def rule_from_dict(d: dict) -> ValidationRule:
    return ValidationRule(
        type=d.get("type", "required"),
        columns=[str(c) for c in (d.get("columns") or [])],
        target=d.get("target", ""),
        min=d.get("min"),
        max=d.get("max"),
        tolerance=d.get("tolerance", 0.0) or 0.0,
    )


def derived_column_from_dict(d: dict) -> DerivedColumn:
    return DerivedColumn(target=d.get("target", ""),
                         formula=d.get("formula", ""))


def row_filter_from_dict(d: dict) -> RowFilter:
    return RowFilter(column=d.get("column", ""),
                     op=d.get("op", "not_empty"),
                     value=str(d.get("value", "") or ""))


def cleanup_from_dict(d: dict) -> CleanupSpec:
    return CleanupSpec(
        trim=bool(d.get("trim", False)),
        dedupe=bool(d.get("dedupe", False)),
        dedupe_columns=[str(c) for c in (d.get("dedupe_columns") or [])],
        filters=[row_filter_from_dict(f) for f in (d.get("filters") or [])],
    )


def aggregate_from_dict(d: dict) -> AggregateSpec:
    return AggregateSpec(column=d.get("column", ""),
                         func=d.get("func", "sum"),
                         target=d.get("target", ""))


def group_by_from_dict(d: dict) -> GroupBySpec:
    return GroupBySpec(
        enabled=bool(d.get("enabled", False)),
        group_columns=[str(c) for c in (d.get("group_columns") or [])],
        aggregations=[aggregate_from_dict(a)
                      for a in (d.get("aggregations") or [])],
    )


def stats_from_dict(d: dict) -> StatsSpec:
    return StatsSpec(
        enabled=bool(d.get("enabled", False)),
        columns=[str(c) for c in (d.get("columns") or [])],
        metrics=[str(m) for m in (d.get("metrics") or [])],
    )


def output_table_from_dict(d: dict) -> OutputTable:
    return OutputTable(
        name=d.get("name", ""),
        sheet=sheet_from_dict(d.get("sheet") or {}),
        fields=[field_from_dict(f) for f in (d.get("fields") or [])],
        validations=[rule_from_dict(r) for r in (d.get("validations") or [])],
        derived_columns=[derived_column_from_dict(x)
                         for x in (d.get("derived_columns") or [])],
        cleanup=cleanup_from_dict(d.get("cleanup") or {}),
        group_by=group_by_from_dict(d.get("group_by") or {}),
        stats=stats_from_dict(d.get("stats") or {}),
    )


def from_dict(data: dict) -> ExtractTemplate:
    return ExtractTemplate(
        name=data.get("name", ""),
        version=data.get("version", 2),
        output_tables=[output_table_from_dict(o) for o in (data.get("output_tables") or [])],
    )


# --------------------------------------------------------------------------
# dataclass -> dict
# --------------------------------------------------------------------------

def to_dict(template: ExtractTemplate) -> dict:
    return asdict(template)


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------

def validate(data: dict) -> list[str]:
    """校验模板 dict，返回错误信息列表（空列表 = 合法）。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["模板根节点必须是对象"]

    if not data.get("name"):
        errors.append("缺少模板名称 name")

    tables = data.get("output_tables")
    if not isinstance(tables, list) or not tables:
        errors.append("output_tables 必须是非空数组")
    else:
        for i, t in enumerate(tables):
            if not isinstance(t, dict):
                errors.append(f"output_tables[{i}] 必须是对象")
                continue
            if not t.get("name"):
                errors.append(f"output_tables[{i}] 缺少 name")
            for j, f in enumerate(t.get("fields") or []):
                if f.get("source") not in VALID_SOURCE:
                    errors.append(f"output_tables[{i}].fields[{j}].source 非法：{f.get('source')}")
            for k, r in enumerate(t.get("validations") or []):
                errors.extend(
                    _validate_rule(r, f"output_tables[{i}].validations[{k}]"))
            errors.extend(_validate_analysis(t, f"output_tables[{i}]"))

    return errors


def _validate_analysis(t: dict, prefix: str) -> list[str]:
    """校验分析准备配置（派生列 / 清洗 / 分组汇总 / 描述统计）。"""
    errors: list[str] = []
    available = [(f.get("target") or "").strip()
                 for f in (t.get("fields") or [])
                 if isinstance(f, dict)]
    available = [a for a in available if a]

    derived = t.get("derived_columns") or []
    if isinstance(derived, list):
        for k, d in enumerate(derived):
            dp = f"{prefix}.derived_columns[{k}]"
            errors.extend(_validate_derived(d, available, dp))
            if isinstance(d, dict) and (d.get("target") or "").strip():
                available.append(d["target"].strip())
    else:
        errors.append(f"{prefix}.derived_columns 必须是数组")

    cleanup = t.get("cleanup")
    if cleanup is not None:
        errors.extend(_validate_cleanup(cleanup, f"{prefix}.cleanup"))

    group_by = t.get("group_by")
    if group_by is not None:
        errors.extend(_validate_group_by(group_by, f"{prefix}.group_by"))

    stats = t.get("stats")
    if stats is not None:
        errors.extend(_validate_stats(stats, f"{prefix}.stats"))

    return errors


def _validate_derived(d, available: list[str], prefix: str) -> list[str]:
    if not isinstance(d, dict):
        return [f"{prefix} 必须是对象"]
    errors: list[str] = []
    target = (d.get("target") or "").strip()
    if not target:
        errors.append(f"{prefix}.target 不能为空")
    formula = d.get("formula") or ""
    if not syntax_ok(formula):
        errors.append(f"{prefix}.formula 公式非法")
    else:
        for ref in extract_refs(formula):
            if ref not in available:
                errors.append(f"{prefix}.formula 引用的列不存在：{ref}")
    return errors


def _validate_cleanup(c, prefix: str) -> list[str]:
    if not isinstance(c, dict):
        return [f"{prefix} 必须是对象"]
    errors: list[str] = []
    for key in ("trim", "dedupe"):
        if key in c and not isinstance(c[key], bool):
            errors.append(f"{prefix}.{key} 必须是布尔值")
    filters = c.get("filters")
    if filters is not None:
        if not isinstance(filters, list):
            errors.append(f"{prefix}.filters 必须是数组")
        else:
            for j, f in enumerate(filters):
                fp = f"{prefix}.filters[{j}]"
                if not isinstance(f, dict):
                    errors.append(f"{fp} 必须是对象")
                    continue
                if not (f.get("column") or "").strip():
                    errors.append(f"{fp}.column 不能为空")
                if f.get("op") not in FILTER_OPS:
                    errors.append(f"{fp}.op 非法：{f.get('op')}")
    return errors


def _validate_group_by(g, prefix: str) -> list[str]:
    if not isinstance(g, dict):
        return [f"{prefix} 必须是对象"]
    errors: list[str] = []
    if "enabled" in g and not isinstance(g["enabled"], bool):
        errors.append(f"{prefix}.enabled 必须是布尔值")
    aggs = g.get("aggregations")
    if aggs is not None:
        if not isinstance(aggs, list):
            errors.append(f"{prefix}.aggregations 必须是数组")
        else:
            for j, a in enumerate(aggs):
                ap = f"{prefix}.aggregations[{j}]"
                if not isinstance(a, dict):
                    errors.append(f"{ap} 必须是对象")
                    continue
                if not (a.get("column") or "").strip():
                    errors.append(f"{ap}.column 不能为空")
                if a.get("func") not in AGG_FUNCS:
                    errors.append(f"{ap}.func 非法：{a.get('func')}")
    return errors


def _validate_stats(s, prefix: str) -> list[str]:
    if not isinstance(s, dict):
        return [f"{prefix} 必须是对象"]
    errors: list[str] = []
    if "enabled" in s and not isinstance(s["enabled"], bool):
        errors.append(f"{prefix}.enabled 必须是布尔值")
    metrics = s.get("metrics")
    if metrics is not None:
        if not isinstance(metrics, list):
            errors.append(f"{prefix}.metrics 必须是数组")
        else:
            for j, m in enumerate(metrics):
                if m not in STAT_METRICS:
                    errors.append(
                        f"{prefix}.metrics[{j}] 非法：{m}")
    return errors


def _validate_rule(rule, prefix: str) -> list[str]:
    """校验单条校验规则的结构（不检查列是否存在于字段，运行期再报）。"""
    if not isinstance(rule, dict):
        return [f"{prefix} 必须是对象"]
    errors: list[str] = []
    rtype = rule.get("type")
    if rtype not in VALID_RULE_TYPES:
        return [f"{prefix}.type 非法：{rtype}"]
    columns = rule.get("columns") or []
    if not isinstance(columns, list):
        return [f"{prefix}.columns 必须是数组"]
    columns = [c for c in columns if isinstance(c, str) and c.strip()]
    if rtype in ("required", "number") and len(columns) < 1:
        errors.append(f"{prefix}.columns 至少包含 1 列")
    elif rtype == "unique" and len(columns) < 1:
        errors.append(f"{prefix}.columns 至少包含 1 列")
    elif rtype == "sum":
        if not (rule.get("target") or "").strip():
            errors.append(f"{prefix}.target 不能为空")
        if not columns:
            errors.append(f"{prefix}.columns 至少包含 1 个分项列")
    lo, hi = rule.get("min"), rule.get("max")
    for name, value in (("min", lo), ("max", hi)):
        if value is not None and not isinstance(value, (int, float)):
            errors.append(f"{prefix}.{name} 必须是数字")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
        errors.append(f"{prefix}.min 不能大于 max")
    return errors

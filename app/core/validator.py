"""数据校验（纯逻辑，无 Qt）。

按模板中每张结果表的 ``ValidationRule`` 检查汇总结果，返回
``ValidationIssue`` 列表。规则类型：必填 / 数值范围 / 唯一性 / 合计等式。
"""
from .models import (VALID_RULE_TYPES, ExtractTemplate, ResultTable,
                     ValidationIssue, ValidationRule, is_empty, norm_key,
                     to_number)

_EPS = 1e-9

# 保留旧的私有别名，避免破坏其他调用点（语义与 models 中的公共函数一致）。
_is_empty = is_empty
_to_number = to_number


def _fmt_num(n: float) -> str:
    if float(n).is_integer():
        return str(int(n))
    return f"{n:g}"


def _col_index(table: ResultTable, name: str):
    try:
        return table.columns.index(name)
    except ValueError:
        return None


def _cell(table: ResultTable, row: list, col: int):
    return row[col] if 0 <= col < len(row) else None


def _issue(table, row, column, rule, message) -> ValidationIssue:
    return ValidationIssue(table=table.name, row=row, column=column,
                           rule_type=rule.type, message=message)


def _table_issue(table, rule, message) -> ValidationIssue:
    return ValidationIssue(table=table.name, row=-1, column="",
                           rule_type=rule.type, message=message)


def describe_rule(rule: ValidationRule) -> str:
    """规则的中文描述（供对话框与日志复用）。"""
    cols = "、".join(rule.columns)
    if rule.type == "required":
        return f"必填：{cols}"
    if rule.type == "number":
        rng = ""
        if rule.min is not None and rule.max is not None:
            rng = f"（{_fmt_num(rule.min)} ~ {_fmt_num(rule.max)}）"
        elif rule.min is not None:
            rng = f"（≥ {_fmt_num(rule.min)}）"
        elif rule.max is not None:
            rng = f"（≤ {_fmt_num(rule.max)}）"
        return f"数值：{cols}{rng}"
    if rule.type == "unique":
        return f"唯一：{cols}"
    if rule.type == "sum":
        parts = " + ".join(rule.columns)
        tol = f"，容差 {_fmt_num(rule.tolerance)}" if rule.tolerance else ""
        return f"合计：{rule.target} = {parts}{tol}"
    return f"{rule.type}：{cols}"


def validate_table(table: ResultTable,
                   rules: list[ValidationRule]) -> list[ValidationIssue]:
    """对一张结果表应用全部规则，返回问题列表。"""
    issues: list[ValidationIssue] = []
    for rule in rules or []:
        issues.extend(_apply_rule(table, rule))
    return issues


def validate_results(results: dict[str, ResultTable],
                     template: ExtractTemplate) -> list[ValidationIssue]:
    """按模板逐张结果表校验（只校验配置了规则的输出表）。"""
    issues: list[ValidationIssue] = []
    for ot in template.output_tables:
        table = results.get(ot.name)
        if table is None:
            continue
        issues.extend(validate_table(table, ot.validations))
    return issues


def _apply_rule(table: ResultTable, rule: ValidationRule) -> list[ValidationIssue]:
    if rule.type not in VALID_RULE_TYPES:
        return [_table_issue(table, rule, f"未知的校验类型：{rule.type}")]

    needed = list(rule.columns)
    if rule.type == "sum":
        needed = [rule.target] + needed
    missing = [c for c in needed if c and c not in table.columns]
    if missing:
        return [_table_issue(table, rule, "规则引用的列不存在：" + "、".join(missing))]

    if rule.type == "required":
        return _check_required(table, rule)
    if rule.type == "number":
        return _check_number(table, rule)
    if rule.type == "unique":
        return _check_unique(table, rule)
    return _check_sum(table, rule)


def _check_required(table, rule) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for name in rule.columns:
        col = _col_index(table, name)
        for r, row in enumerate(table.rows):
            if _is_empty(_cell(table, row, col)):
                issues.append(_issue(table, r, name, rule, "必填项为空"))
    return issues


def _check_number(table, rule) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for name in rule.columns:
        col = _col_index(table, name)
        for r, row in enumerate(table.rows):
            raw = _cell(table, row, col)
            if _is_empty(raw):
                continue  # 空值交给「必填」规则
            num = _to_number(raw)
            if num is None:
                issues.append(_issue(table, r, name, rule,
                                     f"不是有效数字：{raw}"))
            elif rule.min is not None and num < rule.min - _EPS:
                issues.append(_issue(
                    table, r, name, rule,
                    f"数值 {_fmt_num(num)} 小于最小值 {_fmt_num(rule.min)}"))
            elif rule.max is not None and num > rule.max + _EPS:
                issues.append(_issue(
                    table, r, name, rule,
                    f"数值 {_fmt_num(num)} 大于最大值 {_fmt_num(rule.max)}"))
    return issues


def _check_unique(table, rule) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    cols = [_col_index(table, name) for name in rule.columns]
    show_col = rule.columns[0] if rule.columns else ""
    groups: dict[tuple, list[int]] = {}
    for r, row in enumerate(table.rows):
        vals = tuple(norm_key(_cell(table, row, c)) for c in cols)
        if all(v == "" for v in vals):
            continue  # 空键不参与唯一性比较
        groups.setdefault(vals, []).append(r)
    for rows in groups.values():
        if len(rows) < 2:
            continue
        human = [r + 1 for r in rows]
        for r in rows:
            others = "、".join(str(x) for x in human if x != r + 1)
            issues.append(_issue(table, r, show_col, rule,
                                 f"与第 {others} 行重复"))
    return issues


def _check_sum(table, rule) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    total_col = _col_index(table, rule.target)
    add_cols = [(name, _col_index(table, name)) for name in rule.columns]
    tol = max(float(rule.tolerance or 0.0), _EPS)
    for r, row in enumerate(table.rows):
        raw_total = _cell(table, row, total_col)
        if _is_empty(raw_total):
            issues.append(_issue(table, r, rule.target, rule, "合计为空"))
            continue
        total = _to_number(raw_total)
        if total is None:
            issues.append(_issue(table, r, rule.target, rule,
                                 f"合计不是有效数字：{raw_total}"))
            continue
        subtotal = 0.0
        bad = False
        for name, col in add_cols:
            raw = _cell(table, row, col)
            if _is_empty(raw):
                continue  # 空分项按 0 计
            num = _to_number(raw)
            if num is None:
                issues.append(_issue(table, r, name, rule,
                                     f"分项不是有效数字：{raw}"))
                bad = True
            else:
                subtotal += num
        if bad:
            continue
        if abs(total - subtotal) > tol:
            issues.append(_issue(
                table, r, rule.target, rule,
                f"合计 {_fmt_num(total)} ≠ 分项之和 {_fmt_num(subtotal)}"
                f"（差 {_fmt_num(total - subtotal)}）"))
    return issues

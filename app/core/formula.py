"""安全的公式解析与求值（不使用 eval / compile）。

公式语法：以 ``[列名]`` 引用单元格，支持 ``+ - * / %``、一元正负号、
括号，以及白名单函数 ``round/abs/int/float/min/max``。

只解析 AST 白名单节点；属性访问、下标、lambda、推导式、关键字参数等
一律拒绝，避免执行任意代码。引用单元格为空或非数值、除零、溢出等
运行时问题都返回 ``None``（结果留空），不抛异常。
"""
import ast
import re
from dataclasses import dataclass, field

from .models import is_empty, to_number

_REF_RE = re.compile(r"\[([^\[\]]*)\]")

# 内部变量名前缀：列引用先替换成 _ref_0 之类，避免列名中的字符干扰解析。
_REF_PREFIX = "_ref_"

_FUNC_ARITY = {
    "round": (1, 2),
    "abs": (1, 1),
    "int": (1, 1),
    "float": (1, 1),
    "min": (1, None),   # 任意多参
    "max": (1, None),
}

_FUNCS = {
    "round": round,
    "abs": abs,
    "int": int,
    "float": float,
    "min": min,
    "max": max,
}

_BIN_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
}


class FormulaError(ValueError):
    """公式语法/引用错误，消息为中文。"""


@dataclass
class CompiledFormula:
    """编译后的公式：AST + 变量到列名的映射。"""
    tree: ast.Expression
    mapping: dict[str, str] = field(default_factory=dict)  # _ref_0 -> 列名
    refs: list[str] = field(default_factory=list)          # 按首次出现顺序


def extract_refs(formula: str) -> list[str]:
    """按首次出现顺序返回公式中引用的列名（去空白、忽略空引用）。"""
    seen: list[str] = []
    for m in _REF_RE.finditer(formula or ""):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def _rewrite(formula: str) -> tuple[str, dict[str, str], list[str]]:
    """把 ``[列名]`` 替换成内部变量名，返回 (重写文本, 映射, 引用顺序)。"""
    mapping: dict[str, str] = {}
    refs: list[str] = []

    def repl(m):
        name = m.group(1).strip()
        if not name:
            raise FormulaError("列引用不能为空：[]")
        if name not in mapping:
            mapping[name] = f"{_REF_PREFIX}{len(refs)}"
            refs.append(name)
        return mapping[name]

    replaced = _REF_RE.sub(repl, formula or "")
    if "[" in replaced or "]" in replaced:
        raise FormulaError("列引用格式错误：请使用 [列名]")
    return replaced, mapping, refs


def _check_node(node: ast.AST):
    """递归检查白名单节点（只走语义子节点，跳过运算符/上下文节点）。"""
    if isinstance(node, ast.Expression):
        _check_node(node.body)
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _BIN_OPS:
            raise FormulaError("不支持的运算符")
        _check_node(node.left)
        _check_node(node.right)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub)):
            raise FormulaError("不支持的一元运算符")
        _check_node(node.operand)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(
                node.value, (int, float)):
            raise FormulaError("只允许数字常量")
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise FormulaError("函数调用形式非法")
        name = node.func.id
        if name not in _FUNC_ARITY:
            raise FormulaError(f"未知函数：{name}")
        if node.keywords:
            raise FormulaError("函数不支持关键字参数")
        lo, hi = _FUNC_ARITY[name]
        argc = len(node.args)
        if argc < lo or (hi is not None and argc > hi):
            raise FormulaError(f"函数 {name} 参数个数不正确")
        for arg in node.args:
            _check_node(arg)
    elif isinstance(node, ast.Name):
        if not node.id.startswith(_REF_PREFIX):
            raise FormulaError(f"未知标识符：{node.id}")
    else:
        raise FormulaError(f"公式包含不支持的语法：{type(node).__name__}")


def _parse(formula: str) -> tuple[ast.Expression, dict[str, str], list[str]]:
    if not (formula or "").strip():
        raise FormulaError("公式不能为空")
    replaced, mapping, refs = _rewrite(formula)
    try:
        tree = ast.parse(replaced, mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"公式语法错误：{e.msg}") from None
    _check_node(tree)
    return tree, mapping, refs


def syntax_ok(formula: str) -> bool:
    """仅检查结构与函数（不检查列是否存在）；供模板 schema 校验。"""
    try:
        _parse(formula)
        return True
    except FormulaError:
        return False


def validate_formula(formula: str, columns: list[str]) -> tuple[bool, str]:
    """检查公式是否合法且引用的列都存在。返回 (是否合法, 错误消息)。"""
    try:
        compile_formula(formula, columns)
        return True, ""
    except FormulaError as e:
        return False, str(e)


def compile_formula(formula: str, columns: list[str]) -> CompiledFormula:
    """编译公式；语法错误、未知函数或引用不存在的列时抛 FormulaError。"""
    tree, mapping, refs = _parse(formula)
    available = set(columns or [])
    for name in refs:
        if name not in available:
            raise FormulaError(f"引用的列不存在：{name}")
    # 反转成 变量名 -> 列名，求值时直接用列名取值。
    var_to_col = {var: col for col, var in mapping.items()}
    return CompiledFormula(tree=tree, mapping=var_to_col, refs=refs)


def _eval(node: ast.AST, env: dict[str, float]):
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        val = _eval(node.operand, env)
        return val if isinstance(node.op, ast.UAdd) else -val
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS[type(node.op)]
        return op(_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.Call):
        func = _FUNCS[node.func.id]
        args = [_eval(a, env) for a in node.args]
        return func(*args)
    raise FormulaError(f"无法求值的语法：{type(node).__name__}")


def evaluate(compiled: CompiledFormula,
             values: dict[str, object]) -> int | float | None:
    """按行求值；任何引用为空/非数值或运行时错误都返回 None。"""
    env: dict[str, float] = {}
    for var, col in compiled.mapping.items():
        raw = values.get(col)
        if is_empty(raw):
            return None
        num = to_number(raw)
        if num is None:
            return None
        env[var] = num
    try:
        result = _eval(compiled.tree, env)
    except (ZeroDivisionError, OverflowError, ValueError, TypeError,
            FormulaError):
        return None
    if isinstance(result, bool):
        return None
    if isinstance(result, float):
        if result != result or result in (float("inf"), float("-inf")):
            return None
        if result.is_integer():
            return int(result)
    return result

"""AI 扫描表单：把 sheet 内容发给 DeepSeek，取回「标签 → 值」映射。

纯逻辑（不依赖 Qt）：渲染表格文本 → 组装消息 → 调用 chat completions →
解析返回的 JSON 成 `FieldMapping`。网络调用走 stdlib `urllib.request`
（不引入 requests，保持 PyInstaller onefile 简单）。
"""
import datetime
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path

from app.core.models import FieldMapping, SheetData
from app.paths import data_dir

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

# 打包后（onefile）由 app.paths 解析 exe 附近的数据根目录。
LOG_PATH = data_dir() / "logs" / "ai_scan.log"


class AiScanError(Exception):
    """AI 扫描相关的可展示错误（网络、鉴权、解析等）。"""


# ----------------------------------------------------------------------
# 表格 → 文本
# ----------------------------------------------------------------------
def _cell_text(v) -> str:
    if v is None:
        return ""
    # 单元格内的换行/制表符会撑破「一行一记录」的渲染，让后续行号错位；统一压成单空格。
    return " ".join(str(v).split())


def build_sheet_text(sheet: SheetData, max_rows: int = 200, max_cols: int = 40) -> str:
    """把网格渲染成文本，超限截断并附注。

    每行形如 `行N: 列=值 | 列=值 | …`，只列出非空格（行号、列号 1 起）。
    显式写出每格的列号，模型不必靠数制表符去猜列位——稀疏表（大片空格）
    最容易在这儿列号漂移（107-2 曾把「数量」列 10 数成空列 7）。
    """
    grid = sheet.grid
    total_rows = len(grid)
    total_cols = max((len(row) for row in grid), default=0)

    n_rows = min(total_rows, max_rows)
    n_cols = min(total_cols, max_cols)

    lines = []
    for r in range(n_rows):
        row = grid[r]
        cells = []
        for c in range(n_cols):
            text = _cell_text(row[c]) if c < len(row) else ""
            if text:
                cells.append(f"{c + 1}={text}")
        lines.append(f"行{r + 1}: " + " | ".join(cells))

    text = "\n".join(lines)
    if total_rows > max_rows or total_cols > max_cols:
        text += (f"\n（注：表格较大，仅显示前 {max_rows} 行、前 {max_cols} 列，"
                 "可能遗漏字段）")
    return text


# ----------------------------------------------------------------------
# 消息组装
# ----------------------------------------------------------------------
_SYSTEM_PROMPT = (
    "你是一个从中文 Excel 报表/表单中抽取「标签 → 值」映射的助手。\n"
    "表格按行给出，每行形如「行N: 列=值 | 列=值 | …」，只列出非空的单元格；\n"
    "行号、列号都从 1 开始，每个单元格前面的数字就是它的列号。\n"
    "请只依据表格里真实出现的文本判断，不要臆造表中没有的字段。\n"
    "只输出 JSON，不要输出任何解释文字。"
)


def build_messages(sheet_text: str) -> list[dict]:
    user = (
        "下面是一张中文表格（每行「行N: 列=值 | …」，行号、列号从 1 开始，空单元格不列出）：\n\n"
        + sheet_text
        + "\n\n请找出其中所有「标签 → 值」映射。表格主要有三种版式，都要处理：\n\n"
        "【版式一 · 相邻型】标签（如「单位详细名称：」）的值就挨着它：\n"
        "  - 值取标签「右侧最近的非空单元格」（中间可以隔着空白列），或「正下方最近的非空单元格」。\n"
        "  - 跨列居中的大标题（整张表最上面的表名）、带「说明：」「注：」「审核关系」的说明文字、\n"
        "    页脚（单位负责人／统计负责人／填表人／联系电话／报出日期等）都不是标签，请忽略。\n"
        "  - 报表模板自身的管理信息（表号、制表机关、批准文号、有效期至、报表年份等）不是业务字段，\n"
        "    不要输出；但填报单位的标识信息（统一社会信用代码、单位详细名称）要保留。\n\n"
        "【版式二 · 横向表格】上半部有表头行，表头行里每一格是一个「列标签」\n"
        "（如「项目名称」「项目来源」「项目开展形式」…）；表头行下方是若干数据行。\n"
        "  - 每个「列标签 × 数据行」算一个字段：值的列 = 该表头所在列，值的行 = 该数据行。\n"
        "  - 有多个数据行时，把序号加在标签名末尾（自上而下 1、2、3…），编号与标签之间不留空格：\n"
        "    例如同一列标签「项目名称」，第 1/2/3 个数据行分别输出「项目名称1」「项目名称2」「项目名称3」。\n"
        "  - 表头里的「序号」列，以及「甲」「乙」「1」「2」「3」…这类行号/代码格不是标签，忽略；\n"
        "    「合计」「总计」行不算数据行，忽略。\n\n"
        "【版式三 · 纵向指标表】表头行有「指标名称」「计量单位」「代码」「数量」这类列；\n"
        "  每一行是一个指标：标签在「指标名称」列，值在「数量／指标值」列。\n"
        "  - 中间的「计量单位」列（如「人」「千元」「个」）和「代码」列（如「1」「7」「19」）都不是值，\n"
        "    一定要取「数量」列那一格。\n\n"
        "输出规则：\n"
        "  - label：标签文本，去掉结尾的「：」「:」和首尾空白，标签内部也不要多余空格；\n"
        "    带括号单位说明的（如「项目经费支出（千元）」）连单位一起作为标签，编号加在最后，\n"
        "    如「项目经费支出（千元）1」。\n"
        "  - label_row/label_col：标签本身所在格（横向表格即表头格，同一列的多个数据行共用这个位置）。\n"
        "  - value_row/value_col：该字段取值所在格（整数，1 起）。直接写该单元格前面标的列号即可；\n"
        "    空单元格没有列出，所以不要指向表里没出现过的格子。\n"
        "  - 取值格为空的字段不要输出（有标签没值的，直接跳过）。\n"
        "  - 同一 label 只出现一次，不要重复。\n"
        "只返回 JSON，例如：\n"
        '{"pairs":['
        '{"label":"单位详细名称","label_row":5,"label_col":1,"value_row":5,"value_col":3},'
        '{"label":"项目名称1","label_row":6,"label_col":3,"value_row":12,"value_col":3},'
        '{"label":"项目名称2","label_row":6,"label_col":3,"value_row":13,"value_col":3}'
        ']}'
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# ----------------------------------------------------------------------
# 网络调用
# ----------------------------------------------------------------------
def default_caller(messages: list[dict], api_key: str, timeout: float = 30.0) -> str:
    """POST 到 DeepSeek chat completions，返回 assistant 文本内容。"""
    body = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        friendly = {
            401: "API Key 无效或未授权（401），请检查设置里的 Key",
            402: "账户余额不足（402），请先充值",
            429: "请求过于频繁，请稍后再试（429）",
        }.get(e.code, f"服务返回错误（HTTP {e.code}）")
        raise AiScanError(friendly) from e
    except urllib.error.URLError as e:
        raise AiScanError(f"网络连接失败：{e.reason}") from e
    except (TimeoutError, socket.timeout) as e:
        raise AiScanError("请求超时，请检查网络后重试") from e
    except json.JSONDecodeError as e:
        raise AiScanError("服务返回内容无法解析") from e

    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise AiScanError("服务返回结构异常") from e


# ----------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------
def _strip_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _to_pos_int(v) -> int | None:
    """把坐标值转成正整数，非法/非正返回 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v > 0 else None
    if isinstance(v, float):
        return int(v) if v > 0 and v.is_integer() else None
    if isinstance(v, str):
        s = v.strip()
        return int(s) if s.isdigit() and int(s) > 0 else None
    return None


def _cell_is_empty(sheet: SheetData, row: int, col: int) -> bool:
    """坐标（1 起）处为空或越界 → True。"""
    r, c = row - 1, col - 1
    grid = sheet.grid
    if 0 <= r < len(grid) and 0 <= c < len(grid[r]):
        v = grid[r][c]
        return v is None or str(v).strip() == ""
    return True


def parse_pairs(content: str, sheet: SheetData) -> list[FieldMapping]:
    """解析模型返回的 JSON 成字段列表。非法项丢弃，无法解析则抛 AiScanError。"""
    text = _strip_fences(content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise AiScanError("AI 返回内容无法解析") from e

    if isinstance(data, list):
        pairs = data
    elif isinstance(data, dict):
        pairs = data.get("pairs")
    else:
        pairs = None
    if not isinstance(pairs, list):
        raise AiScanError("AI 返回内容无法解析")

    max_row = sheet.max_row
    max_col = sheet.max_col
    fields: list[FieldMapping] = []
    for item in pairs:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        label = label.strip().rstrip(":：").strip()  # 去掉结尾冒号与空白
        if not label:
            continue
        vr = _to_pos_int(item.get("value_row"))
        vc = _to_pos_int(item.get("value_col"))
        if vr is None or vc is None or vr > max_row or vc > max_col:
            continue  # 值坐标缺失或越界 → 丢弃该项
        if _cell_is_empty(sheet, vr, vc):
            continue  # 有标签无值（如空数据行/空列）→ 丢弃，避免导出空字段
        lr = _to_pos_int(item.get("label_row"))
        lc = _to_pos_int(item.get("label_col"))
        if lr is None or lr > max_row:
            lr = None
        if lc is None or lc > max_col:
            lc = None
        fields.append(FieldMapping(
            target=label, source="kv", key=label,
            label_row=lr, label_col=lc, value_row=vr, value_col=vc,
        ))
    return fields


# ----------------------------------------------------------------------
# 日志（复盘提示词用）
# ----------------------------------------------------------------------
def _cell_value(sheet: SheetData, row, col):
    if row is None or col is None:
        return None
    r, c = row - 1, col - 1
    grid = sheet.grid
    if 0 <= r < len(grid) and 0 <= c < len(grid[r]):
        return grid[r][c]
    return None


def _log_exchange(sheet: SheetData, messages: list[dict], content: str,
                  fields: list[FieldMapping], log_path: Path | None = None) -> None:
    """把一次请求（messages）、原始返回、解析结果写入日志，便于复盘提示词。"""
    try:
        path = log_path or LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "=" * 72,
            f"[{ts}] sheet={sheet.name!r} max_row={sheet.max_row} "
            f"max_col={sheet.max_col} 解析字段数={len(fields)}",
            "--- 解析结果 ---",
        ]
        for f in fields:
            val = _cell_value(sheet, f.value_row, f.value_col)
            lines.append(f"  {f.target}  label=({f.label_row},{f.label_col})  "
                         f"value=({f.value_row},{f.value_col}) -> {val!r}")
        lines.append("--- 原始返回 ---")
        lines.append(content)
        lines.append("")
        path.open("a", encoding="utf-8").write("\n".join(lines) + "\n")
    except OSError:
        pass  # 记日志失败不能影响主流程


# ----------------------------------------------------------------------
# 串起来
# ----------------------------------------------------------------------
def recommend_fields(sheet: SheetData, api_key: str, *,
                     caller=default_caller, timeout: float = 30.0,
                     max_rows: int = 200, max_cols: int = 40,
                     log_path: Path | None = None) -> list[FieldMapping]:
    """渲染 → 组装消息 → 调用模型 → 解析，返回推荐字段。

    `caller` 可注入用于测试（签名同 `default_caller`）；只有走默认网络 caller
    时才写日志（避免测试污染 `data/logs`）。
    """
    if not api_key:
        raise AiScanError("未配置 DeepSeek API Key")
    sheet_text = build_sheet_text(sheet, max_rows=max_rows, max_cols=max_cols)
    messages = build_messages(sheet_text)
    content = caller(messages, api_key, timeout=timeout)
    fields = parse_pairs(content, sheet)
    if caller is default_caller:
        _log_exchange(sheet, messages, content, fields, log_path)
    return fields

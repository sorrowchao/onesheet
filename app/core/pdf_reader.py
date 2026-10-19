"""读 PDF → 统一 SheetData（纯逻辑，无 Qt）。

- **文字页**：先用 pdfplumber 抽表格（`表1`、`表2`…）；抽不到表格时按词的
  坐标重建「行/列」版式（`正文`），单格行里的「标签：值」会拆成两列。
- **扫描页**：把页面渲染成 JPEG，交给 OpenAI 兼容的**视觉模型**（复用
  `ai_scan.default_caller` 与同一套 Key/地址），返回结构化的表格行
  （`扫描`）。
- 各页的同一种表格按页序拼成一个 sheet（见 `_merge_pages`），跨页字段
  映射与不同页数的文件都能对齐。

不引入本地 OCR：RapidOCR / onnxruntime 会让 onefile 增大约 100MB。
`pdf_open` / `caller` 可注入，测试无需真实 PDF 或网络。
"""
import base64
import datetime
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.paths import data_dir

from .ai_scan import AiScanError, default_caller, _strip_fences
from .models import SheetData

# 扫描页判定：去掉空白后文字层少于该字符数，视为无文字层。
MIN_TEXT_CHARS = 30
# 同一个词的行分组容差（pt）与分列间隙（pt）。
ROW_TOLERANCE = 3.0
COLUMN_GAP = 12.0
RENDER_DPI = 150

LOG_PATH = data_dir() / "logs" / "pdf_vision.log"

_CJK_SPACE = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")


class PdfScanError(ValueError):
    """PDF 读取/扫描页识别失败（带中文提示）。"""


@dataclass
class VisionConfig:
    """视觉模型配置：与 AI 扫描共用 Key 与 API 地址。"""
    api_key: str
    api_url: str = ""
    model: str = ""
    timeout: float = 120.0


def _default_pdf_open(path: str):
    import pdfplumber
    return pdfplumber.open(path)


_VISION_SYSTEM_PROMPT = (
    "你是一个把扫描件页面转成结构化表格的助手。"
    "请识别图片里的表格与「标签：值」表单，只输出 JSON，不要输出解释文字。"
)

_VISION_USER_TEXT = (
    "请把这张图片里的表格内容按行列结构返回。要求：\n"
    "1. 只返回 JSON：{\"rows\": [[\"第一行第一格\", \"第一行第二格\"], …]}。\n"
    "2. 每一行是一个数组，按从左到右的顺序给出该行的单元格文本；\n"
    "   空单元格用空字符串 \"\" 占位，保持行内列位置对齐。\n"
    "3. 「标签：值」横排在同一行时，保留为一行里的两个单元格（标签去掉结尾冒号）。\n"
    "4. 忠实转写，不要臆造图片里没有的内容；跨行标题单独占一行。\n"
    "5. 表格之后如果还有成对的「标签：值」，也按行返回。"
)


# ----------------------------------------------------------------------
# 网格工具
# ----------------------------------------------------------------------
def _normalize_value(v):
    if v is None:
        return None
    if isinstance(v, str):
        text = " ".join(v.split())
        return text or None
    return v


def _rows_to_grid(rows: list[list]) -> list[list]:
    """空值转 None、补齐成矩形、去掉全空尾行/尾列。"""
    grid = [[_normalize_value(v) for v in row] for row in rows if isinstance(row, list)]
    while grid and all(v is None for v in grid[-1]):
        grid.pop()
    if not grid:
        return []
    max_col = max(len(row) for row in grid)
    while max_col > 0 and all(
            len(row) < max_col or row[max_col - 1] is None for row in grid):
        max_col -= 1
    for row in grid:
        del row[max_col:]
        row.extend([None] * (max_col - len(row)))
    return grid


def _make_sheet(name: str, rows: list[list]) -> SheetData | None:
    grid = _rows_to_grid(rows)
    if not grid:
        return None
    return SheetData(name, grid, [], len(grid), max(len(r) for r in grid))


def _merge_pages(sheets: list[SheetData]) -> list[SheetData]:
    """把各页的同一种表格按页序拼成一个 sheet（`表1` / `正文` / `扫描`）。

    跨页表格在 PDF 里是同一张表，拆成每页一个 sheet 会让字段映射按页
    分裂：末页往往只有一两行，AI 扫描也只能得到极少字段，而且不同文件
    页数不同时行位置无法复用。拼接后所有文件的行/列位置一致；列数
    按最宽的一页补齐（`_rows_to_grid` 负责），不截断任何数据。
    """
    groups: dict[str, list[SheetData]] = {}
    order: list[str] = []
    for sheet in sheets:
        kind = sheet.name.rsplit("-", 1)[-1]
        if kind not in groups:
            groups[kind] = []
            order.append(kind)
        groups[kind].append(sheet)

    merged: list[SheetData] = []
    for kind in order:
        group = groups[kind]
        if len(group) == 1:
            only = group[0]
            only.name = kind
            merged.append(only)
            continue
        rows: list[list] = []
        for sheet in group:
            rows.extend(list(row) for row in sheet.grid)
        combined = _make_sheet(kind, rows)
        if combined is not None:
            merged.append(combined)
    return merged


# ----------------------------------------------------------------------
# 文字页
# ----------------------------------------------------------------------
def _page_text_length(page) -> int:
    try:
        text = page.extract_text() or ""
    except Exception:  # noqa: BLE001 — 个别页面文字层损坏时按扫描页处理
        return 0
    return len("".join(text.split()))


def _table_rows(table) -> list[list]:
    return [list(row) for row in table]


def _text_tables(page, page_no: int) -> list[SheetData]:
    try:
        tables = page.extract_tables() or []
    except Exception:  # noqa: BLE001
        tables = []
    sheets: list[SheetData] = []
    for k, table in enumerate(tables, start=1):
        if not table:
            continue
        sheet = _make_sheet(f"第{page_no}页-表{k}", _table_rows(table))
        if sheet is not None:
            sheets.append(sheet)
    return sheets


def _group_words(words: list[dict]) -> list[list[dict]]:
    """按 top 坐标（±ROW_TOLERANCE）聚成行，行内按 x0 排序。"""
    ordered = sorted(words, key=lambda w: (w["top"], w["x0"]))
    rows: list[list[dict]] = []
    current: list[dict] = []
    for word in ordered:
        if not current:
            current = [word]
            continue
        avg_top = sum(w["top"] for w in current) / len(current)
        if abs(word["top"] - avg_top) <= ROW_TOLERANCE:
            current.append(word)
        else:
            rows.append(sorted(current, key=lambda w: w["x0"]))
            current = [word]
    if current:
        rows.append(sorted(current, key=lambda w: w["x0"]))
    return rows


def _row_cells(words: list[dict]) -> list[str]:
    """按 x 方向间隙（>COLUMN_GAP）分列；中文词之间不插空格。"""
    cells: list[list[dict]] = []
    for word in words:
        if cells and word["x0"] - cells[-1][-1]["x1"] <= COLUMN_GAP:
            cells[-1].append(word)
        else:
            cells.append([word])
    texts = []
    for cell in cells:
        text = " ".join(w["text"].strip() for w in cell if w["text"].strip())
        texts.append(_CJK_SPACE.sub("", text))
    return texts


def _split_label_value(cells: list[str]) -> list[str]:
    """单格行含 `：` / `:` / 制表符时拆成 [标签, 值]。"""
    if len(cells) != 1:
        return cells
    text = cells[0]
    for sep in ("：", ":", "\t"):
        idx = text.find(sep)
        if idx > 0:
            label = text[:idx].strip()
            value = text[idx + 1:].strip()
            if label:
                return [label, value]
    return cells


def _text_layout(page, page_no: int) -> SheetData | None:
    try:
        words = page.extract_words() or []
    except Exception:  # noqa: BLE001
        return None
    rows = []
    for word_row in _group_words(words):
        cells = _row_cells(word_row)
        if cells:
            rows.append(_split_label_value(cells))
    return _make_sheet(f"第{page_no}页-正文", rows)


# ----------------------------------------------------------------------
# 扫描页（视觉模型）
# ----------------------------------------------------------------------
def _page_image_data_url(page) -> str:
    """把页面渲染成 JPEG 并编码为 data URL。"""
    image = page.to_image(resolution=RENDER_DPI).original
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _vision_messages(data_url: str) -> list[dict]:
    return [
        {"role": "system", "content": _VISION_SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": _VISION_USER_TEXT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]},
    ]


def _parse_vision_rows(content: str) -> list[list]:
    text = _strip_fences(content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise PdfScanError("扫描页识别失败：模型返回内容无法解析") from e
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("rows")
    else:
        rows = None
    if not isinstance(rows, list):
        raise PdfScanError("扫描页识别失败：模型返回内容无法解析")
    return [row for row in rows if isinstance(row, list)]


def _log_vision(page_no: int, model: str, content: str, rows: list[list],
                log_path: Path | None = None) -> None:
    try:
        path = log_path or LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "=" * 72,
            f"[{ts}] 第{page_no}页 扫描件 model={model!r} 解析行数={len(rows)}",
            "--- 原始返回 ---",
            content,
            "",
        ]
        path.open("a", encoding="utf-8").write("\n".join(lines) + "\n")
    except OSError:
        pass  # 记日志失败不能影响主流程


def _scan_page(page, page_no: int, vision: VisionConfig, caller,
               log_path: Path | None = None) -> SheetData | None:
    if vision is None or not vision.api_key:
        raise PdfScanError(
            "该 PDF 页面没有文字层（可能是扫描件）。\n"
            "请先在「数据 → AI 接口设置」中配置支持图片输入的视觉模型"
            "（如 gpt-4o、qwen-vl-max），再重新预览。")
    try:
        data_url = _page_image_data_url(page)
    except Exception as e:  # noqa: BLE001 — 渲染失败（缺少 Pillow/pypdfium2 等）
        raise PdfScanError(f"扫描页渲染失败：{e}") from e

    messages = _vision_messages(data_url)
    try:
        content = caller(messages, vision.api_key, timeout=vision.timeout,
                         api_url=vision.api_url, model=vision.model)
    except AiScanError as e:
        raise PdfScanError(f"扫描页识别失败：{e}") from e

    rows = _parse_vision_rows(content)
    if caller is default_caller:
        _log_vision(page_no, vision.model, content, rows, log_path)
    return _make_sheet(f"第{page_no}页-扫描", rows)


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------
def read_pdf(path: str, *, vision: VisionConfig | None = None,
             progress_cb=None, cancel_cb=None, pdf_open=None,
             caller=None, log_path: Path | None = None) -> list[SheetData]:
    """读取 PDF 的所有页面，返回 SheetData 列表。

    文字页直接解析；扫描页交给视觉模型。`cancel_cb` 为真时停止并返回
    已解析的 sheet；`progress_cb(已完成页数, 总页数)` 每页回调一次。
    跨页的同一张表按页序拼成一个 sheet（`表1`/`正文`/`扫描`），列数取
    各页最大值补齐，所以整篇的字段位置稳定、换页不再冲突。
    """
    open_pdf = pdf_open or _default_pdf_open
    call = caller or default_caller
    sheets: list[SheetData] = []

    try:
        pdf = open_pdf(path)
    except Exception as e:  # noqa: BLE001
        raise _open_error(e) from e

    with pdf:
        try:
            pages = list(pdf.pages)
        except Exception as e:  # noqa: BLE001 — 加密/损坏常在这里暴露
            raise _open_error(e) from e
        total = len(pages)
        for i, page in enumerate(pages, start=1):
            if cancel_cb is not None and cancel_cb():
                break
            page_no = i
            try:
                if _page_text_length(page) >= MIN_TEXT_CHARS:
                    page_sheets = _text_tables(page, page_no)
                    if not page_sheets:
                        layout = _text_layout(page, page_no)
                        if layout is not None:
                            page_sheets = [layout]
                else:
                    scanned = _scan_page(page, page_no, vision, call, log_path)
                    page_sheets = [scanned] if scanned is not None else []
            except PdfScanError:
                raise
            except Exception as e:  # noqa: BLE001
                raise PdfScanError(f"第{page_no}页解析失败：{e}") from e
            sheets.extend(page_sheets)
            if progress_cb:
                progress_cb(i, total)
    return _merge_pages(sheets)


def _open_error(e: Exception) -> PdfScanError:
    name = type(e).__name__
    if "Password" in name:
        return PdfScanError("PDF 已加密，请先用其他工具移除密码后再导入")
    return PdfScanError(f"无法读取 PDF：{e}")

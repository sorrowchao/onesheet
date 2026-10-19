"""读 Word（.docx）→ 统一 SheetData（纯逻辑，无 Qt）。

- 文档里每个表格转成一个 sheet（表1、表2…，按文档顺序编号）。
- 非空段落转成「正文」sheet：含第一个 `：`/`:`/制表符的行拆成「标签/值」两列，
  这样 Word 里手写的「姓名：张三」也能被现有表单识别规则处理。
- 合并单元格按底层 `<w:tc>` 分组重建 Region（横向 gridSpan 与纵向 vMerge 都会
  让多个网格位置共享同一个 `<w:tc>`）。
"""
from .models import SheetData, Region

_DOCX_ERROR_HINT = "无法读取 Word 文档（可能已损坏或被加密，请另存为 .docx 后重试）"


class DocxReadError(ValueError):
    """Word 文档读取失败（带中文提示）。"""


def _cell_text(cell) -> str | None:
    text = " ".join(cell.text.split())
    return text or None


def _split_paragraph(text: str) -> list[str]:
    """按第一个 `：` / `:` / 制表符拆成 [标签, 值]；没有分隔符则单列。"""
    for sep in ("：", ":", "\t"):
        idx = text.find(sep)
        if idx >= 0:
            label = text[:idx].strip()
            value = text[idx + 1:].strip()
            if label:
                return [label, value or None]
            break
    return [text.strip() or None]


def _table_sheet(table, name: str) -> SheetData | None:
    """把一个 docx 表格转成 SheetData；空表返回 None。"""
    try:
        rows = list(table.rows)
    except Exception as e:  # noqa: BLE001 — 个别损坏表格结构异常
        raise DocxReadError(_DOCX_ERROR_HINT) from e
    if not rows:
        return None

    cells_grid = []
    positions: dict[int, list[tuple[int, int]]] = {}
    for r, row in enumerate(rows):
        row_cells = list(row.cells)
        cells_grid.append(row_cells)
        for c, cell in enumerate(row_cells):
            positions.setdefault(id(cell._tc), []).append((r, c))

    max_col = max((len(row) for row in cells_grid), default=0)
    if max_col == 0:
        return None
    grid: list[list] = [[None] * max_col for _ in cells_grid]
    for r, row_cells in enumerate(cells_grid):
        for c, cell in enumerate(row_cells):
            grid[r][c] = _cell_text(cell)

    merged: list[Region] = []
    for coords in positions.values():
        if len(coords) < 2:
            continue
        top = min(r for r, _c in coords)
        left = min(c for _r, c in coords)
        bottom = max(r for r, _c in coords)
        right = max(c for _r, c in coords)
        merged.append(Region(top + 1, left + 1, bottom + 1, right + 1))
        # 与 Excel 一致：合并区只有左上角保留值，其余位置留空。
        for r, c in coords:
            if (r, c) != (top, left):
                grid[r][c] = None

    grid = _trim(grid)
    if not grid:
        return None
    return SheetData(name, grid, merged, len(grid),
                     max((len(row) for row in grid), default=0))


def _trim(grid: list[list]) -> list[list]:
    """去掉全空的尾行与尾列。"""
    while grid and all(v is None for v in grid[-1]):
        grid.pop()
    if not grid:
        return []
    max_col = max(len(row) for row in grid)
    while max_col > 0 and all(row[max_col - 1] is None for row in grid):
        max_col -= 1
    for row in grid:
        del row[max_col:]
    return grid


def _paragraph_sheet(paragraphs) -> SheetData | None:
    rows: list[list] = []
    for p in paragraphs:
        text = " ".join(p.text.split())
        if text:
            rows.append(_split_paragraph(text))
    if not rows:
        return None
    max_col = max(len(row) for row in rows)
    for row in rows:
        row.extend([None] * (max_col - len(row)))
    rows = _trim(rows)
    if not rows:
        return None
    return SheetData("正文", rows, [], len(rows),
                     max((len(row) for row in rows), default=0))


def read_docx(path: str) -> list[SheetData]:
    """读取一个 .docx，返回 [表1, 表2, …, 正文]（没有内容的类型自动省略）。"""
    try:
        from docx import Document
    except ImportError as e:  # pragma: no cover — 依赖缺失时给出明确提示
        raise DocxReadError("未安装 python-docx，无法读取 Word 文件") from e

    try:
        document = Document(path)
    except Exception as e:  # noqa: BLE001 — python-docx 的异常类型较多
        raise DocxReadError(_DOCX_ERROR_HINT) from e

    sheets: list[SheetData] = []
    try:
        for i, table in enumerate(document.tables, start=1):
            sheet = _table_sheet(table, f"表{i}")
            if sheet is not None:
                sheets.append(sheet)
        paragraphs = _paragraph_sheet(document.paragraphs)
    except DocxReadError:
        raise
    except Exception as e:  # noqa: BLE001
        raise DocxReadError(_DOCX_ERROR_HINT) from e

    if paragraphs is not None:
        sheets.append(paragraphs)
    return sheets

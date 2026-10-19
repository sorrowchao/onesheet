"""读 Excel（.xlsx / .xls）→ 统一 SheetData。

`detect_format` 还负责识别 Word / PDF / CSV（供 `document_reader` 分发），
但本模块只负责 Excel 的实际读取。
"""
import zipfile
from pathlib import Path

from .models import SheetData, Region

EXCEL_FORMATS = ("xlsx", "xls")

# 读写前最多读 1KB 用于识别；PDF 的 `%PDF-` 可能不在最前面（允许少量前导字节）。
_HEAD_SIZE = 1024


def detect_format(path: str) -> str:
    """按文件头魔数判断真实格式，返回 xlsx/xls/docx/pdf/csv；未识别按扩展名回退。

    docx 与 xlsx 都是 ZIP，必须看压缩包成员名才能区分：
    `word/document.xml` → docx，`xl/workbook.xml` → xlsx。
    """
    head = _read_head(path)
    if b"%PDF-" in head:
        return "pdf"
    if head[:4] == b"PK\x03\x04":            # ZIP → .xlsx / .xlsm / .docx
        member = _zip_member(path)
        if member is not None:
            return member
        # 读不出成员表时按扩展名回退（避免把可疑 ZIP 当成 Excel）。
        ext = Path(path).suffix.lower()
        return "docx" if ext == ".docx" else "xlsx"
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":  # OLE2 → .xls / .doc
        if Path(path).suffix.lower() == ".doc":
            raise ValueError("不支持旧版 Word（.doc），请另存为 .docx 后再导入")
        return "xls"

    ext = Path(path).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return "xlsx"
    if ext == ".xls":
        return "xls"
    if ext == ".docx":
        return "docx"
    if ext == ".pdf":
        return "pdf"
    if ext == ".csv":
        return "csv"
    raise ValueError(f"不支持的格式：{ext}")


def _zip_member(path: str) -> str | None:
    """判断 ZIP 是 docx 还是 xlsx；读不出成员表返回 None。"""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return None
    if "word/document.xml" in names:
        return "docx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    return None


def read_excel(path: str) -> list[SheetData]:
    """读取一个 Excel 文件的所有 sheet，返回 SheetData 列表。

    按文件头魔数判断真实格式，避免扩展名与内容不符导致读取失败
    （如 .xls 被改名为 .xlsx）。
    """
    fmt = detect_format(path)
    if fmt not in EXCEL_FORMATS:
        raise ValueError(f"不是 Excel 文件：{path}")
    if fmt == "xlsx":
        return _read_openpyxl(path)
    return _read_xlrd(path)


def _read_head(path: str) -> bytes:
    """读取文件前 1KB；无法读取（如文件不存在）时返回空字节串。"""
    try:
        with open(path, "rb") as f:
            return f.read(_HEAD_SIZE)
    except OSError:
        return b""


def find_sheet(sheets: list[SheetData], keyword: str) -> SheetData | None:
    """按 sheet 名关键字匹配，找不到返回 None。空关键字返回第一个。"""
    if not sheets:
        return None
    if not keyword:
        return sheets[0]
    for s in sheets:
        if keyword in s.name:
            return s
    return None


def _read_openpyxl(path: str) -> list[SheetData]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=False, data_only=True)
    result: list[SheetData] = []
    for ws in wb.worksheets:
        max_row = ws.max_row or 0
        max_col = ws.max_column or 0
        grid: list[list] = []
        for r in range(1, max_row + 1):
            row = [ws.cell(row=r, column=c).value for c in range(1, max_col + 1)]
            grid.append(row)
        merged = [
            Region(rng.min_row, rng.min_col, rng.max_row, rng.max_col)
            for rng in ws.merged_cells.ranges
        ]
        result.append(SheetData(ws.title, grid, merged, max_row, max_col))
    wb.close()
    return result


def _read_xlrd(path: str) -> list[SheetData]:
    import xlrd
    wb = xlrd.open_workbook(path)
    result: list[SheetData] = []
    for ws in wb.sheets():
        max_row = ws.nrows
        max_col = ws.ncols
        grid = [[ws.cell_value(r, c) for c in range(max_col)] for r in range(max_row)]
        # xlrd merged_cells: (rlo, rhi, clo, chi)，0-based，rhi/chi 为开区间
        merged = [
            Region(rlo + 1, clo + 1, rhi, chi)
            for (rlo, rhi, clo, chi) in ws.merged_cells
        ]
        result.append(SheetData(ws.name, grid, merged, max_row, max_col))
    return result

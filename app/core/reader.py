"""读 Excel（.xlsx / .xls）→ 统一 SheetData。"""
from pathlib import Path

from .models import SheetData, Region


def detect_format(path: str) -> str:
    """按文件头魔数判断真实格式，返回 'xlsx' / 'xls'；未识别时按扩展名回退。"""
    head = _read_head(path)
    if head[:4] == b"PK\x03\x04":            # ZIP → .xlsx / .xlsm
        return "xlsx"
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":  # OLE2 → .xls
        return "xls"

    ext = Path(path).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return "xlsx"
    if ext == ".xls":
        return "xls"
    raise ValueError(f"不支持的格式：{ext}")


def read_excel(path: str) -> list[SheetData]:
    """读取一个 Excel 文件的所有 sheet，返回 SheetData 列表。

    按文件头魔数判断真实格式，避免扩展名与内容不符导致读取失败
    （如 .xls 被改名为 .xlsx）。
    """
    if detect_format(path) == "xlsx":
        return _read_openpyxl(path)
    return _read_xlrd(path)


def _read_head(path: str) -> bytes:
    """读取文件前 8 字节；无法读取（如文件不存在）时返回空字节串。"""
    try:
        with open(path, "rb") as f:
            return f.read(8)
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

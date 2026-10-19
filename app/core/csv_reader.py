"""读 CSV → 统一 SheetData（纯逻辑，无 Qt）。

编码依次尝试 UTF-8（含 BOM）→ UTF-16（有 BOM 时）→ GB18030；分隔符用
`csv.Sniffer` 嗅探（`, ; \\t |`），失败回退逗号。

单元格文本原样保留（不转数字），避免 `007` 之类丢失前导零；数值转换交给
模板里的 `value_type`。
"""
import codecs
import csv
import io

from .models import SheetData

# 跨文件稳定的 sheet 名，模板才能用 sheet_keyword 关键字匹配。
CSV_SHEET_NAME = "CSV"

_DELIMITERS = ",;\t|"
_SNIFF_LINES = 20


class CsvReadError(ValueError):
    """CSV 解码/解析失败（带中文提示）。"""


def _decode(data: bytes) -> str:
    """按 BOM/编码顺序解码；全部失败抛 CsvReadError。"""
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError as e:
            raise CsvReadError(f"CSV 编码无法识别：{e}") from e
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CsvReadError("CSV 编码无法识别（已尝试 UTF-8 / GB18030）")


def _sniff_delimiter(text: str) -> str:
    """嗅探分隔符；样本不足/失败时回退逗号。"""
    sample = "\n".join(text.splitlines()[:_SNIFF_LINES])
    if not sample.strip():
        return ","
    try:
        return csv.Sniffer().sniff(sample, delimiters=_DELIMITERS).delimiter
    except csv.Error:
        return ","


def _to_grid(rows: list[list[str]]) -> list[list]:
    """空串转 None，并去掉全空的尾行与尾列。"""
    grid: list[list] = [[None if cell == "" else cell for cell in row]
                        for row in rows]
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


def read_csv(path: str) -> list[SheetData]:
    """读取一个 CSV 文件，返回只含一个 sheet 的列表（sheet 名固定为 CSV）。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise CsvReadError(f"无法读取 CSV 文件：{e}") from e

    text = _decode(data)
    delimiter = _sniff_delimiter(text)
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    except csv.Error as e:
        raise CsvReadError(f"CSV 解析失败：{e}") from e

    grid = _to_grid(rows)
    max_row = len(grid)
    max_col = max((len(row) for row in grid), default=0)
    return [SheetData(CSV_SHEET_NAME, grid, [], max_row, max_col)]

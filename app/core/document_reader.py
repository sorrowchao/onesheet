"""统一文件读取入口：按真实格式分发给 Excel / Word / PDF / CSV 读取器。

所有格式最终都转成 `list[SheetData]`，因此预览、detector、extractor、聚合、
导出与模板逻辑完全复用。反向写入仍只支持 Excel（见 `partition_excel_files`）。
"""
from pathlib import Path

from .csv_reader import read_csv
from .docx_reader import read_docx
from .models import SheetData
from .pdf_reader import read_pdf
from .reader import EXCEL_FORMATS, detect_format, read_excel


def read_document(path: str, *, vision=None, progress_cb=None,
                  cancel_cb=None) -> list[SheetData]:
    """读取任意受支持的文件，返回 SheetData 列表。

    `vision` 仅供 PDF 扫描页使用（`pdf_reader.VisionConfig`）；
    `progress_cb(已完成页数, 总页数)` / `cancel_cb` 目前只在 PDF 逐页解析时
    生效（取消时返回已解析的 sheet）。
    """
    fmt = detect_format(path)
    if fmt in EXCEL_FORMATS:
        return read_excel(path)
    if fmt == "docx":
        return read_docx(path)
    if fmt == "pdf":
        return read_pdf(path, vision=vision, progress_cb=progress_cb,
                        cancel_cb=cancel_cb)
    if fmt == "csv":
        return read_csv(path)
    raise ValueError(f"不支持的文件格式：{fmt}")


def is_excel_file(path: str) -> bool:
    """按真实格式判断是否 Excel；不存在/无法识别的文件返回 False。"""
    if not Path(path).is_file():
        return False
    try:
        return detect_format(path) in EXCEL_FORMATS
    except (OSError, ValueError):
        return False


def partition_excel_files(files: list[str]) -> tuple[list[str], list[str]]:
    """把文件分成 (Excel, 非 Excel)，保持原顺序。"""
    excel: list[str] = []
    skipped: list[str] = []
    for path in files:
        (excel if is_excel_file(path) else skipped).append(path)
    return excel, skipped

"""后台批量任务（QThread）。"""
from PySide6.QtCore import QThread, Signal

from app.core.aggregator import aggregate
from app.core.ai_scan import recommend_fields
from app.core.extractor import extract_file
from app.core.models import (ExtractTemplate, OutputTable, ResultTable,
                             SheetData)
from app.core.reader import read_excel
from app.core.writer import write_back


class ExtractWorker(QThread):
    """批量抽取线程：逐个读文件 → 抽取 → 合并，信号回传进度与结果。"""

    progress = Signal(int, int)      # 已完成数, 总数
    file_ok = Signal(str)            # 成功处理的一个文件路径
    file_error = Signal(str, str)    # 失败文件路径, 错误信息
    done = Signal(dict)              # {表名: ResultTable} 合并后的最终结果
    cancelled = Signal(int, int)     # 已处理数, 总数（用户取消，不更新结果）

    def __init__(self, files: list[str], template: ExtractTemplate, parent=None):
        super().__init__(parent)
        self.files = list(files)
        self.template = template
        self._cancelled = False

    def cancel(self) -> None:
        """请求取消：当前文件处理完后停止。"""
        self._cancelled = True

    def run(self) -> None:
        per_file: list[dict[str, ResultTable]] = []
        total = len(self.files)
        for i, path in enumerate(self.files):
            if self._cancelled:
                self.cancelled.emit(i, total)
                return
            try:
                sheets = read_excel(path)
                per_file.append(extract_file(sheets, self.template))
                self.file_ok.emit(path)
            except Exception as e:  # noqa: BLE001 — 单文件失败不中断整体
                self.file_error.emit(path, str(e))
            self.progress.emit(i + 1, total)

        self.done.emit(aggregate(per_file))


class WriteBackWorker(QThread):
    """反向写入线程：把汇总表每行回填到对应分表，信号回传进度与报告。"""

    progress = Signal(int, int)      # 已完成数, 总数
    done = Signal(dict)              # 报告：{written, unmatched, errors, unused_rows}

    def __init__(self, files: list[str], output_table: OutputTable,
                 summary: ResultTable, key_cols: list[int], output_dir: str, parent=None):
        super().__init__(parent)
        self.files = list(files)
        self.output_table = output_table
        self.summary = summary
        self.key_cols = key_cols
        self.output_dir = output_dir
        self._cancelled = False

    def cancel(self) -> None:
        """请求取消：当前文件写完后停止（已写入的文件保留）。"""
        self._cancelled = True

    def run(self) -> None:
        report = write_back(
            self.files, self.output_table, self.summary, self.key_cols, self.output_dir,
            progress_cb=lambda d, t: self.progress.emit(d, t),
            cancel_cb=lambda: self._cancelled,
        )
        self.done.emit(report)


class AiScanWorker(QThread):
    """AI 扫描表单线程：把 sheet 发给 DeepSeek，回传推荐字段。"""

    done = Signal(object)      # list[FieldMapping]
    error = Signal(str)        # 友好错误信息

    def __init__(self, sheet: SheetData, api_key: str, caller=None,
                 timeout: float = 30.0, parent=None):
        super().__init__(parent)
        self.sheet = sheet
        self.api_key = api_key
        self.caller = caller
        self.timeout = timeout

    def run(self) -> None:
        try:
            kwargs = {} if self.caller is None else {"caller": self.caller}
            fields = recommend_fields(self.sheet, self.api_key, timeout=self.timeout, **kwargs)
        except Exception as e:  # noqa: BLE001 — 统一转成错误信号
            self.error.emit(str(e))
            return
        self.done.emit(fields)

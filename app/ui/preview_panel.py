"""中间：表格预览 + 手动配对（点标签 → 点值）。"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel,
                               QTableWidget, QTableWidgetItem,
                               QTableWidgetSelectionRange, QVBoxLayout, QWidget)

from app.core.detector import clean_label
from app.core.models import SheetData

MAX_PREVIEW_ROWS = 1000


class PreviewPanel(QWidget):
    # 手动配对完成：标签文本, 标签行, 标签列, 值行, 值列（均为 1-based）
    pair_picked = Signal(str, int, int, int, int)
    # 配对步骤提示（显示到状态栏）
    pair_step = Signal(str)
    # 当前显示的 sheet 变化（用于右侧「值预览」刷新）
    sheet_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        header = QHBoxLayout()
        self.header_label = QLabel("预览")
        self.header_label.setObjectName("sectionHeader")
        header.addWidget(self.header_label)
        self.sheet_combo = QComboBox()
        header.addWidget(self.sheet_combo, 1)
        layout.addLayout(header)

        self.table = QTableWidget()
        # 允许多选，便于同时高亮「标签」与「值」两个单元格。
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self.table)

        self._sheets: list[SheetData] = []
        self._pair_mode = False
        self._pair_state: str | None = None      # 'label' -> 'value'
        self._pair_label: tuple | None = None     # (文本, 行, 列)
        self._pair_accepted = True
        self._pair_reject_msg = ""
        self.sheet_combo.currentIndexChanged.connect(self._on_sheet_index)

    # ------------------------------------------------------------------
    def set_sheets(self, sheets: list[SheetData]):
        self._sheets = sheets
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        for s in sheets:
            self.sheet_combo.addItem(s.name)
        self.sheet_combo.blockSignals(False)
        if sheets:
            self.show_sheet(sheets[0])

    def current_sheet(self) -> SheetData | None:
        idx = self.sheet_combo.currentIndex()
        if 0 <= idx < len(self._sheets):
            return self._sheets[idx]
        return None

    def _on_sheet_index(self, idx: int):
        if 0 <= idx < len(self._sheets):
            self.show_sheet(self._sheets[idx])

    # ------------------------------------------------------------------
    def show_sheet(self, sheet: SheetData):
        self.table.clear()
        rows = min(sheet.max_row, MAX_PREVIEW_ROWS)
        cols = sheet.max_col
        self.table.setRowCount(rows)
        self.table.setColumnCount(cols)
        for r in range(rows):
            for c in range(cols):
                v = sheet.grid[r][c]
                if v is not None:
                    self.table.setItem(r, c, QTableWidgetItem(str(v)))
        for reg in sheet.merged:
            if reg.top - 1 < rows and reg.left - 1 < cols:
                self.table.setSpan(reg.top - 1, reg.left - 1,
                                   min(reg.bottom, rows) - reg.top + 1,
                                   reg.right - reg.left + 1)
        self.table.resizeColumnsToContents()
        self.sheet_changed.emit(sheet)

    # ------------------------------------------------------------------
    # 字段定位：选中配置区的字段后，高亮预览里的标签 / 值单元格
    # ------------------------------------------------------------------
    @staticmethod
    def _find_text(sheet: SheetData, text: str):
        """在 sheet 里查找与 text 完全相同的单元格，返回 0-based (行, 列)。"""
        for r, row in enumerate(sheet.grid):
            for c, v in enumerate(row):
                if isinstance(v, str) and v.strip() == text:
                    return r, c
        return None

    def highlight_field(self, field) -> None:
        """滚动并选中字段对应的标签/值单元格。

        没有固定位置的字段（仅按标签文本匹配）会在当前 sheet 里查找标签文字。
        """
        sheet = self.current_sheet()
        if sheet is None or field is None:
            return
        targets: list[tuple[int, int]] = []
        for r, c in ((field.label_row, field.label_col),
                     (field.value_row, field.value_col)):
            if r is not None and c is not None:
                targets.append((r - 1, c - 1))
        if not targets:
            text = str(field.key or field.target or "").strip()
            pos = self._find_text(sheet, text) if text else None
            if pos is not None:
                targets.append(pos)
        if not targets:
            return

        rows, cols = self.table.rowCount(), self.table.columnCount()
        targets = [(r, c) for r, c in targets if 0 <= r < rows and 0 <= c < cols]
        if not targets:
            return

        focus_r, focus_c = targets[-1]
        self.table.setCurrentCell(focus_r, focus_c)
        self.table.scrollTo(self.table.model().index(focus_r, focus_c),
                            QAbstractItemView.ScrollHint.PositionAtCenter)
        self.table.clearSelection()
        for r, c in targets:
            self.table.setRangeSelected(
                QTableWidgetSelectionRange(r, c, r, c), True)

    # ------------------------------------------------------------------
    # 手动配对模式
    # ------------------------------------------------------------------
    def set_pair_mode(self, on: bool):
        self._pair_mode = on
        self._pair_state = "label" if on else None
        self._pair_label = None
        if on:
            self.pair_step.emit("请点击「标签」单元格（如「姓名」）")
        else:
            self.pair_step.emit("已退出配对模式")

    def is_pair_mode(self) -> bool:
        return self._pair_mode

    def mark_pair_rejected(self, msg: str = ""):
        """配对被拒（如值位置重复）：保持标签，等待重新点值。"""
        self._pair_accepted = False
        self._pair_reject_msg = msg

    def _on_cell_clicked(self, r: int, c: int):
        if not self._pair_mode:
            return
        sheet = self.current_sheet()
        if sheet is None:
            return
        grid = sheet.grid
        v = grid[r][c] if r < len(grid) and c < len(grid[r]) else None

        if self._pair_state == "label":
            text = clean_label(str(v)) if isinstance(v, str) and str(v).strip() else ""
            if not text:
                self.pair_step.emit("该单元格没有文字，请点击有文字的「标签」")
                return
            self._pair_label = (text, r + 1, c + 1)
            self._pair_state = "value"
            self.pair_step.emit(f"已选标签「{text}」，请点击它对应的「值」")
        elif self._pair_state == "value":
            text, lr, lc = self._pair_label
            self._pair_accepted = True
            self.pair_picked.emit(text, lr, lc, r + 1, c + 1)
            if not self._pair_accepted:
                self.pair_step.emit(self._pair_reject_msg or "该值位置已被占用，请重新点击「值」")
                return
            self._pair_label = None
            self._pair_state = "label"
            self.pair_step.emit(f"已配对「{text}」；继续点下一个「标签」，或再点「手动配对」结束")

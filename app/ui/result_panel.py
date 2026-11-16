"""汇总结果预览（多 tab，一个 tab 一张表）。

结果表可编辑：支持复制/粘贴（TSV，可直接与 Excel 互贴）、清除内容、
插入/删除行、撤销/重做，以及右键菜单。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QApplication, QMenu, QTableWidget,
                               QTableWidgetItem, QTabWidget)

from app.core.models import SEQ_COLUMN, ResultTable, ValidationIssue

# 撤销栈上限（每次快照整表内容，避免无限增长）
_MAX_UNDO = 100


class ResultTableWidget(QTableWidget):
    """可编辑的结果表格：复制/粘贴、增删行、撤销/重做。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._restoring = False           # 程序化改动时抑制撤销记录
        self._undo: list[tuple[int, list[list[str]]]] = []
        self._redo: list[tuple[int, list[list[str]]]] = []
        self._state = self._snapshot()    # 最近一次已提交状态
        self._marks: dict[tuple[int, int], str] = {}  # 校验失败标记 (行, 列) -> 提示
        self._error_bg = QColor("#3a2f16")   # 深色主题默认，主窗口按主题覆盖
        self._error_fg = QColor("#e2c08d")
        self.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemChanged.connect(self._on_item_changed)

    def setItem(self, row: int, column: int, item: QTableWidgetItem):
        """结果表所有单元格内容统一居中（含粘贴/撤销新建的单元格）。

        若该格带校验标记，同步恢复底色与提示（撤销/重做会重建单元格）。
        """
        if item is not None:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        super().setItem(row, column, item)
        if item is not None and (row, column) in self._marks:
            prev = self._restoring
            self._restoring = True   # 设置底色会触发 itemChanged，别当作编辑
            try:
                self._apply_mark(item, self._marks[(row, column)])
            finally:
                self._restoring = prev

    # ------------------------------------------------------------------
    # 校验标记
    # ------------------------------------------------------------------
    def set_error_style(self, bg: str, fg: str):
        """设置校验失败单元格的底色/文字色（主题切换时由主窗口调用）。"""
        self._error_bg = QColor(bg)
        self._error_fg = QColor(fg)
        prev = self._restoring
        self._restoring = True
        try:
            for (r, c), msg in self._marks.items():
                item = self.item(r, c)
                if item is not None:
                    self._apply_mark(item, msg)
        finally:
            self._restoring = prev

    def apply_marks(self, marks: dict[tuple[int, int], str]):
        """整体替换校验标记并刷新显示。"""
        prev = self._restoring
        self._restoring = True
        try:
            for (r, c) in list(self._marks):
                item = self.item(r, c)
                if item is not None:
                    self._clear_mark(item)
            self._marks = dict(marks)
            for (r, c), msg in self._marks.items():
                item = self.item(r, c)
                if item is not None:
                    self._apply_mark(item, msg)
        finally:
            self._restoring = prev

    def clear_marks(self):
        prev = self._restoring
        self._restoring = True
        try:
            for (r, c) in list(self._marks):
                item = self.item(r, c)
                if item is not None:
                    self._clear_mark(item)
            self._marks = {}
        finally:
            self._restoring = prev

    def _apply_mark(self, item: QTableWidgetItem, msg: str):
        item.setBackground(QBrush(self._error_bg))
        item.setForeground(QBrush(self._error_fg))
        item.setToolTip(msg)

    @staticmethod
    def _clear_mark(item: QTableWidgetItem):
        item.setData(Qt.ItemDataRole.BackgroundRole, None)
        item.setData(Qt.ItemDataRole.ForegroundRole, None)
        item.setToolTip("")

    # ------------------------------------------------------------------
    # 快照 / 撤销
    # ------------------------------------------------------------------
    def _snapshot(self) -> tuple[int, list[list[str]]]:
        rows = [
            [(self.item(r, c).text() if self.item(r, c) is not None else "")
             for c in range(self.columnCount())]
            for r in range(self.rowCount())
        ]
        return self.columnCount(), rows

    def _restore(self, snapshot: tuple[int, list[list[str]]]):
        cols, rows = snapshot
        self._restoring = True
        try:
            self.setColumnCount(cols)
            self.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, text in enumerate(row):
                    item = self.item(r, c)
                    if item is None:
                        if text:
                            self.setItem(r, c, QTableWidgetItem(text))
                    elif item.text() != text:
                        item.setText(text)
        finally:
            self._restoring = False

    def _record(self):
        """改动前调用：把最近一次状态压入撤销栈。"""
        self._undo.append(self._state)
        if len(self._undo) > _MAX_UNDO:
            self._undo.pop(0)
        self._redo.clear()

    def _commit(self):
        self._state = self._snapshot()

    def _on_item_changed(self, item):
        if self._restoring:
            return
        # 用户改动了校验失败单元格：旧标记已过期，先清掉。
        pos = (item.row(), item.column())
        if pos in self._marks:
            self._marks.pop(pos, None)
            prev = self._restoring
            self._restoring = True
            try:
                self._clear_mark(item)
            finally:
                self._restoring = prev
        self._record()
        self._commit()

    def reset_history(self):
        """清空撤销历史（用于初次填充结果后）。"""
        self._undo.clear()
        self._redo.clear()
        self._state = self._snapshot()

    def undo(self):
        if not self._undo:
            return
        current = self._snapshot()
        previous = self._undo.pop()
        self._redo.append(current)
        self._restore(previous)
        self._state = self._snapshot()

    def redo(self):
        if not self._redo:
            return
        current = self._snapshot()
        nxt = self._redo.pop()
        self._undo.append(current)
        self._restore(nxt)
        self._state = self._snapshot()

    # ------------------------------------------------------------------
    # 复制 / 粘贴
    # ------------------------------------------------------------------
    def copy_selection(self):
        """把选中区域复制为 TSV（可直接粘贴到 Excel）。"""
        ranges = self.selectedRanges()
        if not ranges:
            return
        top = min(r.topRow() for r in ranges)
        bottom = max(r.bottomRow() for r in ranges)
        left = min(r.leftColumn() for r in ranges)
        right = max(r.rightColumn() for r in ranges)
        lines = []
        for row in range(top, bottom + 1):
            cells = []
            for col in range(left, right + 1):
                item = self.item(row, col)
                cells.append(item.text() if item is not None else "")
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))

    def paste(self):
        """从剪贴板粘贴 TSV，从当前单元格开始，必要时自动扩展行列。"""
        text = QApplication.clipboard().text()
        if not text:
            return
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        while lines and lines[-1] == "":
            lines.pop()
        if not lines:
            return
        grid = [line.split("\t") for line in lines]
        r0 = max(self.currentRow(), 0)
        c0 = max(self.currentColumn(), 0)
        need_rows = r0 + len(grid)
        need_cols = c0 + max(len(row) for row in grid)

        self._record()
        self._restoring = True
        try:
            if need_rows > self.rowCount():
                self.setRowCount(need_rows)
            if need_cols > self.columnCount():
                self.setColumnCount(need_cols)
            for i, row in enumerate(grid):
                for j, value in enumerate(row):
                    pos = (r0 + i, c0 + j)
                    item = self.item(*pos)
                    if item is None:
                        if value:
                            self.setItem(*pos, QTableWidgetItem(value))
                    else:
                        item.setText(value)
                    if pos in self._marks:
                        self._marks.pop(pos, None)
                        if item is not None:
                            self._clear_mark(item)
        finally:
            self._restoring = False
        self._commit()

    # ------------------------------------------------------------------
    # 行操作 / 清除
    # ------------------------------------------------------------------
    def clear_selected_cells(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        self._record()
        self._restoring = True
        try:
            for idx in indexes:
                pos = (idx.row(), idx.column())
                item = self.item(*pos)
                if item is not None:
                    item.setText("")
                if pos in self._marks:
                    self._marks.pop(pos, None)
                    if item is not None:
                        self._clear_mark(item)
        finally:
            self._restoring = False
        self._commit()

    def insert_row_above(self):
        row = max(self.currentRow(), 0)
        self._record()
        self.clear_marks()   # 行号整体位移，旧标记作废
        self._restoring = True
        try:
            self.insertRow(row)
        finally:
            self._restoring = False
        self._renumber_seq()
        self._commit()

    def delete_selected_rows(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()})
        if not rows and self.currentRow() >= 0:
            rows = [self.currentRow()]
        if not rows:
            return
        self._record()
        self.clear_marks()   # 行号整体位移，旧标记作废
        self._restoring = True
        try:
            for row in reversed(rows):
                self.removeRow(row)
        finally:
            self._restoring = False
        self._renumber_seq()
        self._commit()

    def _renumber_seq(self):
        """首列为「序号」时，按当前行顺序重排序号。"""
        if self.columnCount() == 0:
            return
        header = self.horizontalHeaderItem(0)
        if header is None or header.text() != SEQ_COLUMN:
            return
        self._restoring = True
        try:
            for r in range(self.rowCount()):
                item = self.item(r, 0)
                if item is None:
                    self.setItem(r, 0, QTableWidgetItem(str(r + 1)))
                else:
                    item.setText(str(r + 1))
        finally:
            self._restoring = False

    # ------------------------------------------------------------------
    # 右键菜单 / 快捷键
    # ------------------------------------------------------------------
    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("复制", self.copy_selection)
        menu.addAction("粘贴", self.paste)
        menu.addSeparator()
        menu.addAction("插入行", self.insert_row_above)
        menu.addAction("删除行", self.delete_selected_rows)
        menu.addAction("清除内容", self.clear_selected_cells)
        menu.addSeparator()
        menu.addAction("撤销", self.undo)
        menu.addAction("重做", self.redo)
        menu.exec(self.viewport().mapToGlobal(pos))

    def keyPressEvent(self, event):
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        key = event.key()
        if ctrl and key == Qt.Key.Key_C:
            self.copy_selection()
            return
        if ctrl and key == Qt.Key.Key_V:
            self.paste()
            return
        if ctrl and key == Qt.Key.Key_Z:
            self.redo() if shift else self.undo()
            return
        if ctrl and key == Qt.Key.Key_Y:
            self.redo()
            return
        if key == Qt.Key.Key_Delete:
            self.clear_selected_cells()
            return
        super().keyPressEvent(event)


class ResultPanel(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tables: dict[str, ResultTable] = {}  # 原始结果（供类型还原）

    def show_results(self, tables: dict[str, ResultTable]):
        self.clear()
        self._tables = {name: rt for name, rt in tables.items()}
        for name, rt in tables.items():
            w = ResultTableWidget()
            w.blockSignals(True)
            try:
                w.setColumnCount(len(rt.columns))
                w.setHorizontalHeaderLabels(rt.columns)
                w.setRowCount(len(rt.rows))
                for r, row in enumerate(rt.rows):
                    for c, v in enumerate(row):
                        if v is not None:
                            w.setItem(r, c, QTableWidgetItem(str(v)))
            finally:
                w.blockSignals(False)
            w.resizeColumnsToContents()
            w.resizeRowsToContents()  # 多行单元格（如同类行堆叠）需要撑高才看得全
            w.reset_history()
            self.addTab(w, name)

    def set_error_style(self, bg: str, fg: str):
        """把校验失败配色应用到所有结果表（主题切换时调用）。"""
        for i in range(self.count()):
            w = self.widget(i)
            if isinstance(w, ResultTableWidget):
                w.set_error_style(bg, fg)

    def apply_validation(self, issues: list[ValidationIssue]):
        """把校验问题映射到各标签页的单元格并高亮（无问题的表清空标记）。"""
        grouped: dict[str, list[ValidationIssue]] = {}
        for it in issues:
            if it.row >= 0:
                grouped.setdefault(it.table, []).append(it)
        for i in range(self.count()):
            name = self.tabText(i)
            w = self.widget(i)
            if not isinstance(w, ResultTableWidget):
                continue
            col_by_name: dict[str, int] = {}
            for c in range(w.columnCount()):
                header = w.horizontalHeaderItem(c)
                if header is not None:
                    col_by_name.setdefault(header.text(), c)
            marks: dict[tuple[int, int], str] = {}
            for it in grouped.get(name, []):
                col = col_by_name.get(it.column)
                if col is None or not (0 <= it.row < w.rowCount()):
                    continue
                marks[(it.row, col)] = it.message
            w.apply_marks(marks)

    def read_results(self) -> dict[str, ResultTable]:
        """把当前所有标签页（含用户编辑）读回 ResultTable。

        单元格文本按原始类型还原：原本是数字的单元格改回数字，字符串保持字符串。
        """
        tables: dict[str, ResultTable] = {}
        for i in range(self.count()):
            name = self.tabText(i)
            w = self.widget(i)
            if not isinstance(w, QTableWidget):
                continue
            columns = [
                w.horizontalHeaderItem(c).text() if w.horizontalHeaderItem(c) else ""
                for c in range(w.columnCount())
            ]
            baseline = self._tables.get(name)
            rows: list[list] = []
            for r in range(w.rowCount()):
                row = []
                for c in range(w.columnCount()):
                    item = w.item(r, c)
                    if item is None or item.text() == "":
                        row.append(None)
                        continue
                    original = self._baseline_cell(baseline, r, c)
                    row.append(self._coerce(item.text(), original))
                rows.append(row)
            tables[name] = ResultTable(name=name, columns=columns, rows=rows)
        return tables

    @staticmethod
    def _baseline_cell(baseline: ResultTable | None, r: int, c: int):
        if baseline is None or r >= len(baseline.rows):
            return None
        row = baseline.rows[r]
        return row[c] if c < len(row) else None

    @staticmethod
    def _coerce(text: str, original):
        """按原始类型把编辑文本还原成 int/float，其余保持字符串。"""
        if isinstance(original, bool):
            return text
        t = text.strip()
        if isinstance(original, int):
            try:
                return int(t)
            except ValueError:
                return text
        if isinstance(original, float):
            try:
                return float(t)
            except ValueError:
                return text
        return text

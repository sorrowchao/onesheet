"""右侧：配置面板（结果表 + 字段映射表）。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFormLayout,
                               QGroupBox, QHeaderView, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QMessageBox, QPushButton,
                               QScrollArea, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from app.core.extractor import object_name_from_path
from app.core.models import (ExtractTemplate, FieldMapping,
                             OutputTable, SheetConfig, SheetData, dedupe_targets)


class _FieldsTable(QTableWidget):
    """字段映射表：选中整行后可上下拖动重排，只发出 (源行, 目标插入行)。

    不做 Qt 默认的单元格移动，实际重排交给 ConfigPanel 依据 _form_fields 完成。
    """

    rows_moved = Signal(int, int)  # (源行, 目标插入行 0..rowCount)

    def __init__(self, rows: int, cols: int, parent=None):
        super().__init__(rows, cols, parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # 允许多选，方便一次删除多个字段（拖动重排仍只作用于当前行）
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def dropEvent(self, event):
        if event.source() is not self:
            event.ignore()
            return
        src = self.currentRow()
        pos = event.position().toPoint()
        idx = self.indexAt(pos)
        if idx.isValid():
            dst = idx.row()
            if pos.y() > self.visualRect(idx).center().y():
                dst += 1
        else:
            dst = self.rowCount()
        # 交给我们自己重排，阻止 Qt 的默认单元格移动
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        if src >= 0:
            self.rows_moved.emit(src, dst)


class ConfigPanel(QWidget):
    template_changed = Signal()
    form_scan_requested = Signal()   # 请求扫描当前预览 sheet 的表单标签
    ai_scan_requested = Signal()     # 请求用 AI 识别当前预览 sheet 的表单标签
    pair_requested = Signal()        # 请求进入预览区「手动配对」模式
    open_template_requested = Signal()  # 请求打开模板
    save_template_requested = Signal()  # 请求保存模板
    manage_templates_requested = Signal()  # 请求打开模板管理器
    field_selected = Signal(object)   # 字段表当前行变化（FieldMapping）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidePanel")
        self._loading = False
        self._tables: list[OutputTable] = []
        self._form_fields: list[FieldMapping] = []   # 当前结果表的候选字段
        self._checked: set[int] = set()               # 候选字段中被勾选的索引
        self._sheet: SheetData | None = None          # 用于「值预览」列
        self._current_path: str | None = None         # 当前预览文件（文件名列预览）

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        body = QWidget()
        body.setObjectName("sideBody")
        scroll.setWidget(body)
        root = QVBoxLayout(body)

        self.header_label = QLabel("配置")
        self.header_label.setObjectName("sectionHeader")
        root.addWidget(self.header_label)

        # --- 模板名 ---
        name_box = QGroupBox("模板")
        name_layout = QFormLayout(name_box)
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_edit)
        name_layout.addRow("模板名", self.name_edit)
        tpl_btns = QHBoxLayout()
        self.btn_open_tpl = QPushButton("打开模板")
        self.btn_open_tpl.clicked.connect(self.open_template_requested.emit)
        self.btn_save_tpl = QPushButton("保存模板")
        self.btn_save_tpl.clicked.connect(self.save_template_requested.emit)
        self.btn_manage_tpl = QPushButton("管理")
        self.btn_manage_tpl.setToolTip(
            "模板管理器：查看 data/templates 下的模板，可重命名 / 复制 / 删除")
        self.btn_manage_tpl.clicked.connect(self.manage_templates_requested.emit)
        tpl_btns.addWidget(self.btn_open_tpl)
        tpl_btns.addWidget(self.btn_save_tpl)
        tpl_btns.addWidget(self.btn_manage_tpl)
        tpl_btns.addStretch(1)
        name_layout.addRow("", tpl_btns)
        root.addWidget(name_box)

        # --- 结果表列表 ---
        tables_box = QGroupBox("结果表（一张结果表对应一个 sheet）")
        tables_layout = QVBoxLayout(tables_box)
        self.table_list = QListWidget()
        self.table_list.currentRowChanged.connect(self._on_table_selected)
        self.table_list.setMaximumHeight(90)
        tables_layout.addWidget(self.table_list)
        tbtns = QHBoxLayout()
        btn_add_t = QPushButton("添加结果表")
        btn_add_t.clicked.connect(self._add_table)
        btn_del_t = QPushButton("删除结果表")
        btn_del_t.clicked.connect(self._del_table)
        tbtns.addWidget(btn_add_t)
        tbtns.addWidget(btn_del_t)
        tbtns.addStretch(1)
        tables_layout.addLayout(tbtns)
        root.addWidget(tables_box)

        # --- 当前结果表配置 ---
        cfg_box = QGroupBox("当前结果表配置")
        cfg_layout = QVBoxLayout(cfg_box)

        form = QFormLayout()
        self.table_name_edit = QLineEdit()
        self.table_name_edit.textChanged.connect(self._on_edit)
        form.addRow("结果表名", self.table_name_edit)

        self.sheet_kw_edit = QLineEdit()
        self.sheet_kw_edit.textChanged.connect(self._on_edit)
        form.addRow("sheet 关键字", self.sheet_kw_edit)
        cfg_layout.addLayout(form)

        # --- 字段映射表（标签 → 取值位置） ---
        self.fields_box = QGroupBox("字段映射（标签 → 取值位置，可直接改行/列）")
        fields_layout = QVBoxLayout(self.fields_box)
        self.fields_table = _FieldsTable(0, 5)
        self.fields_table.setObjectName("fieldsTable")
        self.fields_table.setHorizontalHeaderLabels(["导出", "标签", "值行", "值列", "值预览"])
        self.fields_table.verticalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignCenter)
        self.fields_table.itemChanged.connect(self._on_field_item_changed)
        self.fields_table.rows_moved.connect(self._move_field_to)
        self.fields_table.currentCellChanged.connect(self._on_field_selected)
        self.fields_table.setMinimumHeight(240)
        self.fields_table.setColumnWidth(0, 44)
        # 首列固定宽度，勾选框用 QSS margin 居中（见 theme.py）。
        self.fields_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed)
        self.fields_table.setColumnWidth(1, 150)
        self.fields_table.setColumnWidth(2, 52)
        self.fields_table.setColumnWidth(3, 52)
        self.fields_table.setColumnWidth(4, 170)
        self.fields_table.horizontalHeader().setStretchLastSection(True)
        fields_layout.addWidget(self.fields_table)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("主键字段"))
        self.key_combo = QComboBox()
        self.key_combo.setToolTip(
            "选一个字段作为主键：反向写入时「匹配字段」默认只勾它、其余不勾。"
            "（不选则沿用默认：只勾未被改动的列）")
        self.key_combo.currentIndexChanged.connect(self._on_key_changed)
        key_row.addWidget(self.key_combo, 1)
        fields_layout.addLayout(key_row)

        # 第一行：生成字段 / 添加字段；第二行：勾选、移动、删除。
        fbtns = QHBoxLayout()
        self.btn_scan = QPushButton("扫描表单")
        self.btn_scan.clicked.connect(self.form_scan_requested.emit)
        self.btn_ai = QPushButton("AI 扫描表单")
        self.btn_ai.setToolTip("调用 DeepSeek 识别当前预览 sheet 的「标签:值」，结果可再勾选/修改")
        self.btn_ai.clicked.connect(self.ai_scan_requested.emit)
        self.btn_pair = QPushButton("手动配对")
        self.btn_pair.clicked.connect(self.pair_requested.emit)
        btn_add_f = QPushButton("添加字段")
        btn_add_f.clicked.connect(self._add_field_row)
        self.btn_add_filename = QPushButton("添加文件名")
        self.btn_add_filename.setToolTip(
            "添加「文件名」列：取文件名里的汉字；文件名没有汉字时取所在文件夹名。\n"
            "例：国能混凝土107-1.xlsx → 国能混凝土；采购部/107-1.xlsx → 采购部")
        self.btn_add_filename.clicked.connect(self._add_filename_field)
        for b in (self.btn_scan, self.btn_ai, self.btn_pair,
                  btn_add_f, self.btn_add_filename):
            fbtns.addWidget(b)
        fbtns.addStretch(1)
        fields_layout.addLayout(fbtns)

        fbtns2 = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_all.clicked.connect(self._select_all_form)
        btn_invert = QPushButton("反选")
        btn_invert.setToolTip("反转所有字段的导出勾选")
        btn_invert.clicked.connect(self._invert_checked)
        btn_none = QPushButton("全不选")
        btn_none.setToolTip("取消所有字段的勾选（不删除）")
        btn_none.clicked.connect(self._clear_form)
        btn_up = QPushButton("上移")
        btn_up.clicked.connect(lambda: self._move_field(-1))
        btn_down = QPushButton("下移")
        btn_down.clicked.connect(lambda: self._move_field(1))
        btn_del_f = QPushButton("删除选中")
        btn_del_f.setToolTip("删除当前选中的一个或多个字段（可 Ctrl/Shift 多选）")
        btn_del_f.clicked.connect(self._del_field_row)
        btn_clear = QPushButton("清空")
        btn_clear.setToolTip("删除全部字段（清空映射表）")
        btn_clear.clicked.connect(self._clear_all_form)
        for b in (btn_all, btn_invert, btn_none, btn_up, btn_down,
                  btn_del_f, btn_clear):
            fbtns2.addWidget(b)
        fbtns2.addStretch(1)
        fields_layout.addLayout(fbtns2)
        cfg_layout.addWidget(self.fields_box)

        root.addWidget(cfg_box)
        root.addStretch(1)

    # ------------------------------------------------------------------
    # 供外部调用
    # ------------------------------------------------------------------
    def set_sheet(self, sheet: SheetData | None):
        """当前预览的 sheet 变化时，刷新「值预览」列。"""
        self._sheet = sheet
        self._refresh_value_preview()

    def set_current_file(self, path: str | None):
        """当前预览文件变化时，刷新「文件名」字段的值预览。"""
        self._current_path = path
        self._refresh_value_preview()

    def set_template(self, tpl: ExtractTemplate):
        self._loading = True
        try:
            self.name_edit.setText(tpl.name)
            self._tables = [self._clone_table(t) for t in tpl.output_tables]
            self._rebuild_table_list()
        finally:
            self._loading = False

    def get_template(self) -> ExtractTemplate:
        self._read_fields_table()
        self._read_current_form()
        return ExtractTemplate(
            name=self.name_edit.text().strip() or "未命名模板",
            output_tables=self._tables,
        )

    def _on_field_selected(self, row: int, _col: int,
                           _prev_row: int, _prev_col: int):
        """字段表当前行变化：通知外部在预览区定位该字段。"""
        if self._loading:
            return
        if 0 <= row < len(self._form_fields):
            self.field_selected.emit(self._form_fields[row])

    def set_form_fields(self, fields: list[FieldMapping]):
        """扫描表单后注入字段（带位置），默认全部勾选。"""
        self._ensure_table()
        self._form_fields = list(fields)
        dedupe_targets(self._form_fields)
        self._checked = set(range(len(self._form_fields)))
        self._rebuild_fields_table()

    def add_pair(self, label_text: str, label_row: int, label_col: int,
                 value_row: int, value_col: int) -> str | None:
        """手动配对完成：加入候选字段并默认勾选。

        标签允许重复（供后期提醒修改）；但值的位置不能重复。
        返回 None 表示成功；返回字符串表示被拒绝的原因。
        """
        self._ensure_table()
        # 值的位置不能重复：同一值单元格只能被一个标签使用
        for x in self._form_fields:
            if x.value_row == value_row and x.value_col == value_col:
                return f"值位置（第 {value_row} 行第 {value_col} 列）已被「{x.target}」占用"
        f = FieldMapping(target=label_text, source="kv", key=label_text,
                         label_row=label_row, label_col=label_col,
                         value_row=value_row, value_col=value_col)
        self._form_fields.append(f)
        dedupe_targets(self._form_fields)
        self._checked.add(len(self._form_fields) - 1)
        self._rebuild_fields_table()
        return None

    # ------------------------------------------------------------------
    # 内部：表格/列表重建
    # ------------------------------------------------------------------
    @staticmethod
    def _clone_field(f: FieldMapping) -> FieldMapping:
        return FieldMapping(target=f.target, source=f.source, is_key=f.is_key,
                            key=f.key, value_type=f.value_type,
                            label_row=f.label_row, label_col=f.label_col,
                            value_row=f.value_row, value_col=f.value_col)

    @classmethod
    def _clone_table(cls, t: OutputTable) -> OutputTable:
        return OutputTable(
            name=t.name,
            sheet=SheetConfig(sheet_keyword=t.sheet.sheet_keyword),
            fields=[cls._clone_field(f) for f in t.fields],
        )

    def _rebuild_table_list(self, select_row: int = 0):
        self.table_list.blockSignals(True)
        self.table_list.clear()
        for t in self._tables:
            self.table_list.addItem(t.name)
        self.table_list.blockSignals(False)
        if self._tables:
            row = min(max(select_row, 0), len(self._tables) - 1)
            self.table_list.setCurrentRow(row)
            self._populate_form(self._tables[row])
        else:
            self._populate_form(None)

    def _on_table_selected(self, row: int):
        if self._loading or row < 0 or row >= len(self._tables):
            return
        self._populate_form(self._tables[row])

    def _populate_form(self, t: OutputTable | None):
        self._loading = True
        try:
            if t is None:
                self.table_name_edit.setText("")
                self.sheet_kw_edit.setText("")
                self._form_fields = []
            else:
                self.table_name_edit.setText(t.name)
                self.sheet_kw_edit.setText(t.sheet.sheet_keyword)
                self._form_fields = [self._clone_field(f) for f in t.fields]
            self._checked = set(range(len(self._form_fields)))
            self._rebuild_fields_table()
        finally:
            self._loading = False

    # ------------------------------------------------------------------
    # 字段映射表
    # ------------------------------------------------------------------
    def _rebuild_fields_table(self):
        self._loading = True
        try:
            self.fields_table.blockSignals(True)
            self.fields_table.setRowCount(len(self._form_fields))
            center = Qt.AlignmentFlag.AlignCenter
            for r, f in enumerate(self._form_fields):
                check = QTableWidgetItem()
                check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                check.setCheckState(Qt.Checked if r in self._checked else Qt.Unchecked)
                check.setTextAlignment(center)
                self.fields_table.setItem(r, 0, check)
                label = QTableWidgetItem(f.target or str(f.key or ""))
                label.setTextAlignment(center)
                self.fields_table.setItem(r, 1, label)
                from_filename = f.source == "filename"
                value_row = QTableWidgetItem(str(f.value_row) if f.value_row else "")
                value_row.setTextAlignment(center)
                value_col = QTableWidgetItem(str(f.value_col) if f.value_col else "")
                value_col.setTextAlignment(center)
                if from_filename:
                    # 文件名列不按单元格取值，位置列不可编辑。
                    value_row.setFlags(value_row.flags() & ~Qt.ItemIsEditable)
                    value_col.setFlags(value_col.flags() & ~Qt.ItemIsEditable)
                self.fields_table.setItem(r, 2, value_row)
                self.fields_table.setItem(r, 3, value_col)
                preview = QTableWidgetItem(self._preview_text(f))
                preview.setTextAlignment(center)
                preview.setFlags(preview.flags() & ~Qt.ItemIsEditable)
                self.fields_table.setItem(r, 4, preview)
            self.fields_table.blockSignals(False)
            self._rebuild_key_combo()
        finally:
            self._loading = False
        self._read_fields_table()

    def _rebuild_key_combo(self):
        """同步「主键字段」下拉框：第 0 项为「（无）」，其后对应各字段。"""
        self.key_combo.blockSignals(True)
        self.key_combo.clear()
        self.key_combo.addItem("（无）")
        for f in self._form_fields:
            self.key_combo.addItem(f.target or str(f.key or "") or "（未命名）")
        key_i = next((i for i, f in enumerate(self._form_fields) if f.is_key), None)
        self.key_combo.setCurrentIndex(key_i + 1 if key_i is not None else 0)
        self.key_combo.blockSignals(False)

    def _on_key_changed(self, idx: int):
        if self._loading:
            return
        for i, f in enumerate(self._form_fields):
            f.is_key = (idx > 0 and i == idx - 1)
        if idx > 0:
            # 主键字段必须导出，否则不会进入模板，反向写入时也就无从匹配。
            self.fields_table.blockSignals(True)
            item = self.fields_table.item(idx - 1, 0)
            if item is not None:
                item.setCheckState(Qt.Checked)
            self.fields_table.blockSignals(False)
        self._read_fields_table()
        self.template_changed.emit()

    def _preview_text(self, f: FieldMapping) -> str:
        if f.source == "filename":
            return object_name_from_path(self._current_path)
        if f.value_row is None or f.value_col is None or self._sheet is None:
            return ""
        grid = self._sheet.grid
        r, c = f.value_row - 1, f.value_col - 1
        if 0 <= r < len(grid) and 0 <= c < len(grid[r]):
            v = grid[r][c]
            return "" if v is None else str(v)
        return ""

    def _refresh_value_preview(self):
        self._loading = True
        try:
            for r in range(self.fields_table.rowCount()):
                if 0 <= r < len(self._form_fields):
                    item = self.fields_table.item(r, 4)
                    if item is not None:
                        item.setText(self._preview_text(self._form_fields[r]))
        finally:
            self._loading = False

    @staticmethod
    def _parse_int(item: QTableWidgetItem | None):
        if item is None:
            return None
        text = item.text().strip()
        return int(text) if text.isdigit() else None

    def _on_field_item_changed(self, item: QTableWidgetItem):
        if self._loading:
            return
        col = item.column()
        r = item.row()
        if 0 <= r < len(self._form_fields):
            f = self._form_fields[r]
            if col == 1:
                text = item.text().strip()
                f.target = text
                if f.source != "filename":
                    f.key = text
                dedupe_targets(self._form_fields)
                # 重名标签可能被自动改名，整表刷新以同步显示
                self._rebuild_fields_table()
                self.template_changed.emit()
                return
            elif col == 2:
                f.value_row = self._parse_int(item)
            elif col == 3:
                f.value_col = self._parse_int(item)
        self._refresh_value_preview()
        self._read_fields_table()
        self.template_changed.emit()

    def _read_fields_table(self):
        row = self.table_list.currentRow()
        if row < 0 or row >= len(self._tables):
            return
        fields: list[FieldMapping] = []
        checked: set[int] = set()
        for r in range(self.fields_table.rowCount()):
            if r >= len(self._form_fields):
                continue
            check = self.fields_table.item(r, 0)
            if check is None or check.checkState() != Qt.Checked:
                continue
            checked.add(r)
            f = self._form_fields[r]
            if f.target:
                fields.append(f)
        self._checked = checked
        self._tables[row].fields = fields

    def _add_field_row(self):
        self._ensure_table()
        self._form_fields.append(FieldMapping(target="", source="kv", key=""))
        self._checked.add(len(self._form_fields) - 1)
        self._rebuild_fields_table()
        self.fields_table.setCurrentCell(len(self._form_fields) - 1, 1)
        self.fields_table.editItem(self.fields_table.item(len(self._form_fields) - 1, 1))

    def _add_filename_field(self):
        """添加一行「文件名」字段（取文件名/文件夹名里的汉字），已有则不重复添加。"""
        self._ensure_table()
        for i, f in enumerate(self._form_fields):
            if f.source == "filename":
                self.fields_table.setCurrentCell(i, 1)
                return
        self._form_fields.append(FieldMapping(target="文件名", source="filename"))
        dedupe_targets(self._form_fields)
        self._checked.add(len(self._form_fields) - 1)
        self._rebuild_fields_table()
        self.fields_table.setCurrentCell(len(self._form_fields) - 1, 1)
        self.template_changed.emit()

    def _selected_rows(self) -> list[int]:
        """当前选中的字段行号（升序去重）；无选中时回退到当前行。"""
        sm = self.fields_table.selectionModel()
        rows = sorted({idx.row() for idx in sm.selectedRows()}) if sm else []
        if not rows:
            r = self.fields_table.currentRow()
            if r >= 0:
                rows = [r]
        return rows

    def _del_field_row(self):
        """删除选中的（一个或多个）字段。"""
        rows = [r for r in self._selected_rows() if 0 <= r < len(self._form_fields)]
        if not rows:
            return
        deleted = set(rows)
        for r in sorted(deleted, reverse=True):
            self._form_fields.pop(r)
        # 勾选索引重映射：跳过被删的，删掉一个在前的就整体左移
        self._checked = {
            i - sum(1 for d in deleted if d < i)
            for i in self._checked if i not in deleted
        }
        self._rebuild_fields_table()
        self.template_changed.emit()

    def _move_field(self, delta: int):
        """把当前字段上移(-1)/下移(+1)。只改结果列顺序，不影响抽取/回填。"""
        r = self.fields_table.currentRow()
        if 0 <= r < len(self._form_fields):
            self._move_field_to(r, r - 1 if delta < 0 else r + 2)

    def _move_field_to(self, src: int, dst: int):
        """把 src 行字段移动到 dst（插入位置，0..len）。只改结果列顺序，不影响抽取/回填。"""
        n = len(self._form_fields)
        if not (0 <= src < n) or dst == src or dst == src + 1:
            return
        if dst > src:
            dst -= 1
        dst = max(0, min(dst, n - 1))
        if dst == src:
            return
        field = self._form_fields.pop(src)
        self._form_fields.insert(dst, field)
        # 勾选状态随字段一起移动
        was_checked = src in self._checked
        moved: set[int] = set()
        for i in self._checked:
            if i != src:
                moved.add(i - 1 if i > src else i)
        if was_checked:
            moved.add(dst)
        self._checked = moved
        self._rebuild_fields_table()
        self.fields_table.setCurrentCell(dst, 1)
        self.template_changed.emit()

    def _set_all_checked(self, state: Qt.CheckState):
        """把全部字段的导出勾选统一设为 state；不删除字段。"""
        self.fields_table.blockSignals(True)
        for r in range(self.fields_table.rowCount()):
            item = self.fields_table.item(r, 0)
            if item is not None:
                item.setCheckState(state)
        self.fields_table.blockSignals(False)
        self._read_fields_table()
        self.template_changed.emit()

    def _select_all_form(self):
        self._set_all_checked(Qt.Checked)

    def _clear_form(self):
        self._set_all_checked(Qt.Unchecked)

    def _invert_checked(self):
        """反转全部字段的导出勾选；不删除字段。"""
        self.fields_table.blockSignals(True)
        for r in range(self.fields_table.rowCount()):
            item = self.fields_table.item(r, 0)
            if item is not None:
                item.setCheckState(
                    Qt.Unchecked if item.checkState() == Qt.Checked
                    else Qt.Checked)
        self.fields_table.blockSignals(False)
        self._read_fields_table()
        self.template_changed.emit()

    def _clear_all_form(self):
        """清空：删除全部字段（不可撤销，先确认）。"""
        if not self._form_fields:
            return
        answer = QMessageBox.question(
            self, "清空字段",
            f"确定要删除全部 {len(self._form_fields)} 个字段吗？（不可撤销）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._form_fields = []
        self._checked = set()
        self._rebuild_fields_table()
        self.template_changed.emit()

    # ------------------------------------------------------------------
    # 内部：读写
    # ------------------------------------------------------------------
    def _read_current_form(self):
        row = self.table_list.currentRow()
        if row < 0 or row >= len(self._tables):
            return
        t = self._tables[row]
        t.name = self.table_name_edit.text().strip() or "结果表"
        t.sheet.sheet_keyword = self.sheet_kw_edit.text().strip()
        self.table_list.blockSignals(True)
        self.table_list.item(row).setText(t.name)
        self.table_list.blockSignals(False)

    # ------------------------------------------------------------------
    # 增删
    # ------------------------------------------------------------------
    def _add_table(self):
        self._read_current_form()
        self._tables.append(OutputTable(name=f"结果表{len(self._tables) + 1}"))
        self._rebuild_table_list(select_row=len(self._tables) - 1)

    def _ensure_table(self):
        """没有结果表时自动创建一个，避免扫描/配对的字段因无处保存而丢失。"""
        if not self._tables:
            self._add_table()

    def _del_table(self):
        row = self.table_list.currentRow()
        if 0 <= row < len(self._tables):
            self._tables.pop(row)
            self._rebuild_table_list(select_row=min(row, len(self._tables) - 1))

    # ------------------------------------------------------------------
    def _on_edit(self, *_):
        if self._loading:
            return
        self._read_current_form()
        self.template_changed.emit()

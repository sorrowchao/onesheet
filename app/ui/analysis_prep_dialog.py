"""分析准备配置对话框。

为当前结果表配置四类加工：派生列 / 清洗去重 / 分组汇总 / 描述统计。
配置保存在模板的 ``OutputTable`` 上，随模板 JSON 一起存取；
手动「运行分析」才生效，分组汇总 / 描述统计会生成额外结果页签。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from app.core.analysis import (AGG_LABELS, STAT_LABELS, clone_aggregate,
                               clone_cleanup, clone_derived, clone_filter,
                               clone_group_by, clone_stats)
from app.core.formula import validate_formula
from app.core.models import (AGG_FUNCS, FILTER_OPS, SEQ_COLUMN, STAT_METRICS,
                             AggregateSpec, CleanupSpec, DerivedColumn,
                             GroupBySpec, OutputTable, RowFilter, StatsSpec)

_FILTER_LABELS = {
    "not_empty": "非空", "empty": "为空", "eq": "等于", "ne": "不等于",
    "gt": "大于", "ge": "大于等于", "lt": "小于", "le": "小于等于",
    "contains": "包含", "not_contains": "不包含",
}
_EMPTY_OPS = ("not_empty", "empty")


def _section(title: str) -> QLabel:
    label = QLabel(title)
    label.setObjectName("sectionHeader")
    return label


def _checked_texts(widget: QListWidget) -> list[str]:
    out: list[str] = []
    for i in range(widget.count()):
        item = widget.item(i)
        if item.checkState() == Qt.CheckState.Checked:
            out.append(item.text())
    return out


def _fill_check_list(widget: QListWidget, names: list[str],
                     checked: list[str] | None = None):
    """填充可勾选列表；checked 为 None 时全部勾选。"""
    widget.clear()
    wanted = None if checked is None else set(checked)
    for name in names:
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        state = (Qt.CheckState.Checked
                 if wanted is None or name in wanted
                 else Qt.CheckState.Unchecked)
        item.setCheckState(state)
        widget.addItem(item)


def _fill_metric_list(widget: QListWidget, checked: list[str] | None):
    """填充指标列表：显示中文名，UserRole 存指标键。"""
    widget.clear()
    wanted = None if checked is None else set(checked)
    for key in STAT_METRICS:
        item = QListWidgetItem(STAT_LABELS.get(key, key))
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            Qt.CheckState.Checked
            if wanted is None or key in wanted
            else Qt.CheckState.Unchecked)
        widget.addItem(item)


def _checked_metric_keys(widget: QListWidget) -> list[str]:
    out: list[str] = []
    for i in range(widget.count()):
        item = widget.item(i)
        if item.checkState() == Qt.CheckState.Checked:
            out.append(item.data(Qt.ItemDataRole.UserRole))
    return out


def _ok_cancel(layout):
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok
        | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
    layout.addWidget(buttons)
    return buttons


# --------------------------------------------------------------------------
# 子对话框
# --------------------------------------------------------------------------
class DerivedColumnEditDialog(QDialog):
    """新增 / 编辑一个派生列。"""

    def __init__(self, columns: list[str], export_columns: list[str],
                 derived: DerivedColumn | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑派生列")
        self.setMinimumWidth(460)
        self._columns = list(columns)
        self._export_columns = set(export_columns)
        self._result: DerivedColumn | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(_section("派生列"))
        form = QFormLayout()
        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText("新列名，如 合计")
        form.addRow("列名", self.target_edit)

        self.formula_edit = QLineEdit()
        self.formula_edit.setPlaceholderText("如 [基本工资] + [绩效]")
        form.addRow("公式", self.formula_edit)

        self.insert_combo = QComboBox()
        self.insert_combo.addItem("插入列引用…", "")
        for name in self._columns:
            self.insert_combo.addItem(f"[{name}]", name)
        self.insert_combo.activated.connect(self._insert_ref)
        form.addRow("", self.insert_combo)
        layout.addLayout(form)

        hint = QLabel("支持 + - * / %、括号、一元正负号；函数 round/abs/int/"
                      "float/min/max。引用为空或非数值时结果留空。")
        hint.setObjectName("dialogHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = _ok_cancel(layout)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        if derived is not None:
            self.target_edit.setText(derived.target)
            self.formula_edit.setText(derived.formula)

    def _insert_ref(self, index: int):
        name = self.insert_combo.itemData(index)
        if name:
            self.formula_edit.insert(f"[{name}]")
        self.insert_combo.setCurrentIndex(0)

    def column(self) -> DerivedColumn | None:
        return self._result

    def accept(self):
        target = self.target_edit.text().strip()
        if not target:
            QMessageBox.warning(self, "提示", "请填写列名")
            return
        if target in self._export_columns:
            QMessageBox.warning(self, "提示", f"列名与已有导出列重名：{target}")
            return
        formula = self.formula_edit.text().strip()
        ok, msg = validate_formula(formula, self._columns)
        if not ok:
            QMessageBox.warning(self, "提示", msg)
            return
        self._result = DerivedColumn(target=target, formula=formula)
        super().accept()


class FilterEditDialog(QDialog):
    """新增 / 编辑一条行筛选条件。"""

    def __init__(self, columns: list[str], row_filter: RowFilter | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑筛选条件")
        self.setMinimumWidth(380)
        self._result: RowFilter | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(_section("筛选条件"))
        form = QFormLayout()
        self.col_combo = QComboBox()
        self.col_combo.addItems(columns)
        form.addRow("列", self.col_combo)

        self.op_combo = QComboBox()
        for op in FILTER_OPS:
            self.op_combo.addItem(_FILTER_LABELS.get(op, op), op)
        self.op_combo.currentIndexChanged.connect(self._on_op_changed)
        form.addRow("条件", self.op_combo)

        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("比较值（数值条件按数字比较）")
        self.value_label = QLabel("值")
        form.addRow(self.value_label, self.value_edit)
        layout.addLayout(form)

        buttons = _ok_cancel(layout)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        if row_filter is not None:
            if row_filter.column:
                self.col_combo.setCurrentText(row_filter.column)
            idx = self.op_combo.findData(row_filter.op)
            if idx >= 0:
                self.op_combo.setCurrentIndex(idx)
            self.value_edit.setText(row_filter.value)
        self._on_op_changed()

    def _on_op_changed(self, *_):
        need_value = self.op_combo.currentData() not in _EMPTY_OPS
        self.value_label.setVisible(need_value)
        self.value_edit.setVisible(need_value)

    def filter(self) -> RowFilter | None:
        return self._result

    def accept(self):
        column = self.col_combo.currentText().strip()
        if not column:
            QMessageBox.warning(self, "提示", "请选择列")
            return
        op = self.op_combo.currentData()
        value = self.value_edit.text() if op not in _EMPTY_OPS else ""
        self._result = RowFilter(column=column, op=op, value=value)
        super().accept()


class AggregateEditDialog(QDialog):
    """新增 / 编辑一条分组聚合。"""

    def __init__(self, columns: list[str], agg: AggregateSpec | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑聚合")
        self.setMinimumWidth(380)
        self._result: AggregateSpec | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(_section("聚合"))
        form = QFormLayout()
        self.col_combo = QComboBox()
        self.col_combo.addItems(columns)
        form.addRow("列", self.col_combo)

        self.func_combo = QComboBox()
        for func in AGG_FUNCS:
            self.func_combo.addItem(AGG_LABELS.get(func, func), func)
        form.addRow("方式", self.func_combo)

        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText("留空自动命名，如 合计(工资)")
        form.addRow("输出列", self.target_edit)
        layout.addLayout(form)

        buttons = _ok_cancel(layout)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        if agg is not None:
            if agg.column:
                self.col_combo.setCurrentText(agg.column)
            idx = self.func_combo.findData(agg.func)
            if idx >= 0:
                self.func_combo.setCurrentIndex(idx)
            self.target_edit.setText(agg.target)

    def aggregate(self) -> AggregateSpec | None:
        return self._result

    def accept(self):
        column = self.col_combo.currentText().strip()
        if not column:
            QMessageBox.warning(self, "提示", "请选择列")
            return
        self._result = AggregateSpec(
            column=column, func=self.func_combo.currentData(),
            target=self.target_edit.text().strip())
        super().accept()


# --------------------------------------------------------------------------
# 主对话框
# --------------------------------------------------------------------------
class AnalysisPrepDialog(QDialog):
    """分析准备：四个页签编辑四类配置。"""

    def __init__(self, output_table: OutputTable, parent=None):
        super().__init__(parent)
        self.setWindowTitle("分析准备")
        self.setMinimumSize(620, 480)

        self._base_columns = self._export_columns(output_table)
        self._derived = [clone_derived(d) for d in output_table.derived_columns]
        self._cleanup = clone_cleanup(output_table.cleanup)
        self._filters = [clone_filter(f) for f in output_table.cleanup.filters]
        self._group = clone_group_by(output_table.group_by)
        self._aggs = [clone_aggregate(a) for a in output_table.group_by.aggregations]
        self._stats = clone_stats(output_table.stats)

        layout = QVBoxLayout(self)
        layout.addWidget(_section(f"分析准备 — {output_table.name or '结果表'}"))

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_derived_tab(), "派生列")
        self.tabs.addTab(self._build_cleanup_tab(), "清洗/去重")
        self.tabs.addTab(self._build_group_tab(), "分组汇总")
        self.tabs.addTab(self._build_stats_tab(), "描述统计")
        layout.addWidget(self.tabs, 1)

        buttons = _ok_cancel(layout)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    # ------------------------------------------------------------------
    # 派生列
    # ------------------------------------------------------------------
    def _build_derived_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("按顺序计算，后面的公式可以引用前面新增的派生列。")
        hint.setObjectName("dialogHint")
        layout.addWidget(hint)

        self.derived_table = QTableWidget(0, 2)
        self.derived_table.setHorizontalHeaderLabels(["列名", "公式"])
        self._prep_table(self.derived_table)
        self.derived_table.cellDoubleClicked.connect(lambda *_: self._edit_derived)
        layout.addWidget(self.derived_table, 1)

        row = QHBoxLayout()
        for text, slot in (("添加", self._add_derived),
                           ("编辑", self._edit_derived),
                           ("删除", self._del_derived)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch(1)
        layout.addLayout(row)
        self._refresh_derived_table()
        return page

    def _refresh_derived_table(self):
        self.derived_table.setRowCount(len(self._derived))
        for r, d in enumerate(self._derived):
            for c, text in enumerate((d.target, d.formula)):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.derived_table.setItem(r, c, item)

    def _available_columns(self) -> list[str]:
        names = list(self._base_columns)
        for d in self._derived:
            name = (d.target or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    def _add_derived(self):
        dlg = DerivedColumnEditDialog(self._available_columns(),
                                      self._base_columns, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.column():
            self._derived.append(dlg.column())
            self._refresh_derived_table()
            self._refresh_column_widgets()

    def _edit_derived(self):
        row = self.derived_table.currentRow()
        if not (0 <= row < len(self._derived)):
            return
        dlg = DerivedColumnEditDialog(
            self._available_columns(), self._base_columns,
            self._derived[row], self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.column():
            self._derived[row] = dlg.column()
            self._refresh_derived_table()
            self._refresh_column_widgets()

    def _del_derived(self):
        row = self.derived_table.currentRow()
        if not (0 <= row < len(self._derived)):
            return
        self._derived.pop(row)
        self._refresh_derived_table()
        self._refresh_column_widgets()

    # ------------------------------------------------------------------
    # 清洗/去重
    # ------------------------------------------------------------------
    def _build_cleanup_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.trim_cb = QCheckBox("去首尾空白")
        self.trim_cb.setChecked(self._cleanup.trim)
        layout.addWidget(self.trim_cb)

        self.dedupe_cb = QCheckBox("去重复行")
        self.dedupe_cb.setChecked(self._cleanup.dedupe)
        self.dedupe_cb.toggled.connect(self._on_dedupe_toggled)
        layout.addWidget(self.dedupe_cb)

        dedupe_box = QGroupBox("去重列（全不选 = 按全部列，不含序号）")
        dedupe_layout = QVBoxLayout(dedupe_box)
        self.dedupe_list = QListWidget()
        self.dedupe_list.setMaximumHeight(120)
        _fill_check_list(self.dedupe_list, self._available_columns(),
                         self._cleanup.dedupe_columns)
        dedupe_layout.addWidget(self.dedupe_list)
        layout.addWidget(dedupe_box)
        self._dedupe_box = dedupe_box

        filters_box = QGroupBox("筛选条件（全部满足才保留该行）")
        filters_layout = QVBoxLayout(filters_box)
        self.filter_table = QTableWidget(0, 3)
        self.filter_table.setHorizontalHeaderLabels(["列", "条件", "值"])
        self._prep_table(self.filter_table)
        self.filter_table.cellDoubleClicked.connect(lambda *_: self._edit_filter)
        filters_layout.addWidget(self.filter_table, 1)
        row = QHBoxLayout()
        for text, slot in (("添加", self._add_filter),
                           ("编辑", self._edit_filter),
                           ("删除", self._del_filter)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch(1)
        filters_layout.addLayout(row)
        layout.addWidget(filters_box, 1)

        self._refresh_filter_table()
        self._on_dedupe_toggled(self.dedupe_cb.isChecked())
        return page

    def _on_dedupe_toggled(self, checked: bool):
        self._dedupe_box.setEnabled(checked)

    def _refresh_filter_table(self):
        self.filter_table.setRowCount(len(self._filters))
        for r, f in enumerate(self._filters):
            cells = (f.column, _FILTER_LABELS.get(f.op, f.op), f.value)
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.filter_table.setItem(r, c, item)

    def _add_filter(self):
        columns = self._available_columns()
        if not columns:
            QMessageBox.information(self, "提示", "当前结果表还没有可用字段")
            return
        dlg = FilterEditDialog(columns, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.filter():
            self._filters.append(dlg.filter())
            self._refresh_filter_table()

    def _edit_filter(self):
        row = self.filter_table.currentRow()
        if not (0 <= row < len(self._filters)):
            return
        dlg = FilterEditDialog(self._available_columns(), self._filters[row],
                               self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.filter():
            self._filters[row] = dlg.filter()
            self._refresh_filter_table()

    def _del_filter(self):
        row = self.filter_table.currentRow()
        if not (0 <= row < len(self._filters)):
            return
        self._filters.pop(row)
        self._refresh_filter_table()

    # ------------------------------------------------------------------
    # 分组汇总
    # ------------------------------------------------------------------
    def _build_group_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.group_enabled_cb = QCheckBox("启用分组汇总")
        self.group_enabled_cb.setChecked(self._group.enabled)
        self.group_enabled_cb.toggled.connect(self._on_group_toggled)
        layout.addWidget(self.group_enabled_cb)

        self.group_body = QWidget()
        body = QVBoxLayout(self.group_body)
        body.setContentsMargins(0, 0, 0, 0)

        group_box = QGroupBox("分组列（按首次出现顺序输出）")
        gl = QVBoxLayout(group_box)
        self.group_list = QListWidget()
        self.group_list.setMaximumHeight(110)
        _fill_check_list(self.group_list, self._available_columns(),
                         self._group.group_columns)
        gl.addWidget(self.group_list)
        body.addWidget(group_box)

        agg_box = QGroupBox("聚合")
        al = QVBoxLayout(agg_box)
        self.agg_table = QTableWidget(0, 3)
        self.agg_table.setHorizontalHeaderLabels(["列", "方式", "输出列"])
        self._prep_table(self.agg_table)
        self.agg_table.cellDoubleClicked.connect(lambda *_: self._edit_agg)
        al.addWidget(self.agg_table, 1)
        row = QHBoxLayout()
        for text, slot in (("添加", self._add_agg),
                           ("编辑", self._edit_agg),
                           ("删除", self._del_agg)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch(1)
        al.addLayout(row)
        body.addWidget(agg_box, 1)
        layout.addWidget(self.group_body, 1)

        self._refresh_agg_table()
        self._on_group_toggled(self.group_enabled_cb.isChecked())
        return page

    def _on_group_toggled(self, checked: bool):
        self.group_body.setEnabled(checked)

    def _refresh_agg_table(self):
        self.agg_table.setRowCount(len(self._aggs))
        for r, a in enumerate(self._aggs):
            cells = (a.column, AGG_LABELS.get(a.func, a.func), a.target)
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.agg_table.setItem(r, c, item)

    def _add_agg(self):
        columns = self._available_columns()
        if not columns:
            QMessageBox.information(self, "提示", "当前结果表还没有可用字段")
            return
        dlg = AggregateEditDialog(columns, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.aggregate():
            self._aggs.append(dlg.aggregate())
            self._refresh_agg_table()

    def _edit_agg(self):
        row = self.agg_table.currentRow()
        if not (0 <= row < len(self._aggs)):
            return
        dlg = AggregateEditDialog(self._available_columns(), self._aggs[row],
                                  self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.aggregate():
            self._aggs[row] = dlg.aggregate()
            self._refresh_agg_table()

    def _del_agg(self):
        row = self.agg_table.currentRow()
        if not (0 <= row < len(self._aggs)):
            return
        self._aggs.pop(row)
        self._refresh_agg_table()

    # ------------------------------------------------------------------
    # 描述统计
    # ------------------------------------------------------------------
    def _build_stats_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.stats_enabled_cb = QCheckBox("启用描述统计")
        self.stats_enabled_cb.setChecked(self._stats.enabled)
        self.stats_enabled_cb.toggled.connect(self._on_stats_toggled)
        layout.addWidget(self.stats_enabled_cb)

        self.stats_body = QWidget()
        body = QVBoxLayout(self.stats_body)
        body.setContentsMargins(0, 0, 0, 0)

        self.stats_all_cb = QCheckBox("全部数值列")
        self.stats_all_cb.setChecked(not self._stats.columns)
        self.stats_all_cb.toggled.connect(self._on_stats_all_toggled)
        body.addWidget(self.stats_all_cb)

        cols_box = QGroupBox("统计列")
        cl = QVBoxLayout(cols_box)
        self.stats_list = QListWidget()
        self.stats_list.setMaximumHeight(110)
        _fill_check_list(self.stats_list, self._available_columns(),
                         self._stats.columns or None)
        cl.addWidget(self.stats_list)
        body.addWidget(cols_box)
        self._stats_cols_box = cols_box

        metrics_box = QGroupBox("指标（全不选 = 全部）")
        ml = QVBoxLayout(metrics_box)
        self.metrics_list = QListWidget()
        self.metrics_list.setMaximumHeight(160)
        _fill_metric_list(self.metrics_list, self._stats.metrics or None)
        ml.addWidget(self.metrics_list)
        body.addWidget(metrics_box, 1)
        layout.addWidget(self.stats_body, 1)

        self._on_stats_toggled(self.stats_enabled_cb.isChecked())
        self._on_stats_all_toggled(self.stats_all_cb.isChecked())
        return page

    def _on_stats_toggled(self, checked: bool):
        self.stats_body.setEnabled(checked)

    def _on_stats_all_toggled(self, checked: bool):
        self._stats_cols_box.setEnabled(not checked)

    # ------------------------------------------------------------------
    # 共用
    # ------------------------------------------------------------------
    @staticmethod
    def _prep_table(table: QTableWidget):
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)

    @staticmethod
    def _export_columns(output_table: OutputTable) -> list[str]:
        out: list[str] = []
        for f in output_table.fields:
            name = (f.target or "").strip()
            if name and name != SEQ_COLUMN and name not in out:
                out.append(name)
        return out

    def _refresh_column_widgets(self):
        """派生列变化后刷新各页签的列勾选列表（保留原勾选状态）。"""
        columns = self._available_columns()
        for widget in (self.dedupe_list, self.group_list, self.stats_list):
            checked = _checked_texts(widget)
            widget.blockSignals(True)
            _fill_check_list(widget, columns, checked)
            widget.blockSignals(False)

    # ------------------------------------------------------------------
    def specs(self):
        """返回当前配置的深拷贝 (derived, cleanup, group_by, stats)。"""
        derived = [clone_derived(d) for d in self._derived]
        cleanup = CleanupSpec(
            trim=self.trim_cb.isChecked(),
            dedupe=self.dedupe_cb.isChecked(),
            dedupe_columns=_checked_texts(self.dedupe_list),
            filters=[clone_filter(f) for f in self._filters],
        )
        group_by = GroupBySpec(
            enabled=self.group_enabled_cb.isChecked(),
            group_columns=_checked_texts(self.group_list),
            aggregations=[clone_aggregate(a) for a in self._aggs],
        )
        stats_columns = ([] if self.stats_all_cb.isChecked()
                         else _checked_texts(self.stats_list))
        stats = StatsSpec(
            enabled=self.stats_enabled_cb.isChecked(),
            columns=stats_columns,
            metrics=_checked_metric_keys(self.metrics_list),
        )
        return derived, cleanup, group_by, stats

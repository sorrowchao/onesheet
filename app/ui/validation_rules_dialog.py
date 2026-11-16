"""校验规则编辑对话框。

为当前结果表配置数据校验规则：必填 / 数值范围 / 唯一 / 合计。
规则保存在模板的 `OutputTable.validations` 中，随模板 JSON 一起存取。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from app.core.models import OutputTable, ValidationRule
from app.core.validator import describe_rule

_TYPE_CHOICES = (
    ("required", "必填"),
    ("number", "数值范围"),
    ("unique", "唯一"),
    ("sum", "合计"),
)


def _clone_rule(rule: ValidationRule) -> ValidationRule:
    return ValidationRule(type=rule.type, columns=list(rule.columns),
                          target=rule.target, min=rule.min, max=rule.max,
                          tolerance=rule.tolerance)


class RuleEditDialog(QDialog):
    """新增 / 编辑单条规则。"""

    def __init__(self, columns: list[str], rule: ValidationRule | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑校验规则")
        self.setMinimumWidth(420)
        self._result: ValidationRule | None = None
        self._columns = list(columns)
        if rule is not None:
            for name in [*rule.columns, rule.target]:
                if name and name not in self._columns:
                    self._columns.append(name)

        layout = QVBoxLayout(self)
        header = QLabel("校验规则")
        header.setObjectName("sectionHeader")
        layout.addWidget(header)

        form = QFormLayout()
        self.type_combo = QComboBox()
        for key, label in _TYPE_CHOICES:
            self.type_combo.addItem(label, key)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("规则类型", self.type_combo)

        self.col_combo = QComboBox()
        self.col_combo.addItems(self._columns)
        self.col_row_label = QLabel("列")
        form.addRow(self.col_row_label, self.col_combo)

        self.multi_list = QListWidget()
        self.multi_list.setMaximumHeight(110)
        for name in self._columns:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.multi_list.addItem(item)
        self.multi_label = QLabel("列（可多选）")
        form.addRow(self.multi_label, self.multi_list)

        self.target_combo = QComboBox()
        self.target_combo.addItems(self._columns)
        self.target_label = QLabel("合计列")
        form.addRow(self.target_label, self.target_combo)

        self.min_edit = QLineEdit()
        self.min_edit.setPlaceholderText("不限")
        self.min_label = QLabel("最小值")
        form.addRow(self.min_label, self.min_edit)

        self.max_edit = QLineEdit()
        self.max_edit.setPlaceholderText("不限")
        self.max_label = QLabel("最大值")
        form.addRow(self.max_label, self.max_edit)

        self.tol_spin = QDoubleSpinBox()
        self.tol_spin.setRange(0.0, 1e12)
        self.tol_spin.setDecimals(6)
        self.tol_spin.setValue(0.0)
        self.tol_label = QLabel("允许误差")
        form.addRow(self.tol_label, self.tol_spin)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if rule is not None:
            self._load(rule)
        else:
            self._select_columns([])
        self._on_type_changed()

    # ------------------------------------------------------------------
    def rule(self) -> ValidationRule | None:
        return self._result

    def _type(self) -> str:
        return self.type_combo.currentData()

    def _on_type_changed(self, *_):
        rtype = self._type()
        singles = rtype in ("required", "number")
        self.col_row_label.setVisible(singles)
        self.col_combo.setVisible(singles)
        multi = rtype in ("unique", "sum")
        self.multi_label.setVisible(multi)
        self.multi_list.setVisible(multi)
        self.target_label.setVisible(rtype == "sum")
        self.target_combo.setVisible(rtype == "sum")
        self.min_label.setVisible(rtype == "number")
        self.min_edit.setVisible(rtype == "number")
        self.max_label.setVisible(rtype == "number")
        self.max_edit.setVisible(rtype == "number")
        self.tol_label.setVisible(rtype == "sum")
        self.tol_spin.setVisible(rtype == "sum")
        if rtype == "unique":
            self.multi_label.setText("列（可多选，组合唯一）")
        elif rtype == "sum":
            self.multi_label.setText("分项列（可多选）")

    def _checked_columns(self) -> list[str]:
        out: list[str] = []
        for i in range(self.multi_list.count()):
            item = self.multi_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.text())
        return out

    def _select_columns(self, names: list[str]):
        wanted = set(names)
        for i in range(self.multi_list.count()):
            item = self.multi_list.item(i)
            item.setCheckState(
                Qt.CheckState.Checked if item.text() in wanted
                else Qt.CheckState.Unchecked)

    def _parse_optional(self, edit: QLineEdit, label: str):
        text = edit.text().strip()
        if not text:
            return None
        try:
            return float(text.replace(",", "").replace("，", ""))
        except ValueError:
            QMessageBox.warning(self, "提示", f"{label}不是有效数字：{text}")
            return _INVALID

    def _load(self, rule: ValidationRule):
        idx = self.type_combo.findData(rule.type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        if rule.columns:
            self.col_combo.setCurrentText(rule.columns[0])
        if rule.target:
            self.target_combo.setCurrentText(rule.target)
        self._select_columns(rule.columns)
        if rule.min is not None:
            self.min_edit.setText(str(rule.min))
        if rule.max is not None:
            self.max_edit.setText(str(rule.max))
        self.tol_spin.setValue(float(rule.tolerance or 0.0))

    def accept(self):
        rtype = self._type()
        if rtype in ("required", "number"):
            columns = [self.col_combo.currentText()] if self.col_combo.currentText() else []
        else:
            columns = self._checked_columns()
        if not columns:
            QMessageBox.warning(self, "提示", "请至少选择一列")
            return
        target = self.target_combo.currentText() if rtype == "sum" else ""
        if rtype == "sum" and not target:
            QMessageBox.warning(self, "提示", "请选择合计列")
            return
        lo = hi = None
        if rtype == "number":
            lo = self._parse_optional(self.min_edit, "最小值")
            if lo is _INVALID:
                return
            hi = self._parse_optional(self.max_edit, "最大值")
            if hi is _INVALID:
                return
            if lo is not None and hi is not None and lo > hi:
                QMessageBox.warning(self, "提示", "最小值不能大于最大值")
                return
        self._result = ValidationRule(
            type=rtype,
            columns=columns,
            target=target,
            min=lo,
            max=hi,
            tolerance=(self.tol_spin.value() if rtype == "sum" else 0.0),
        )
        super().accept()


_INVALID = object()


class ValidationRulesDialog(QDialog):
    """当前结果表的校验规则列表。"""

    def __init__(self, output_table: OutputTable, parent=None):
        super().__init__(parent)
        self.setWindowTitle("校验规则")
        self.setMinimumSize(520, 360)
        self._rules = [_clone_rule(r) for r in output_table.validations]
        self._columns = self._available_columns(output_table)

        layout = QVBoxLayout(self)
        header = QLabel(f"校验规则 — {output_table.name or '结果表'}")
        header.setObjectName("sectionHeader")
        layout.addWidget(header)

        hint = QLabel("抽取完成后自动校验；反向写入前也会检查目标结果表。")
        hint.setObjectName("dialogHint")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["类型", "规则"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 96)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(lambda *_: self._edit())
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        btn_add = QPushButton("添加")
        btn_add.clicked.connect(self._add)
        btn_edit = QPushButton("编辑")
        btn_edit.clicked.connect(self._edit)
        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self._delete)
        row.addWidget(btn_add)
        row.addWidget(btn_edit)
        row.addWidget(btn_del)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh()

    def rules(self) -> list[ValidationRule]:
        return [_clone_rule(r) for r in self._rules]

    # ------------------------------------------------------------------
    @staticmethod
    def _available_columns(output_table: OutputTable) -> list[str]:
        out: list[str] = []
        for f in output_table.fields:
            name = (f.target or "").strip()
            if name and name not in out:
                out.append(name)
        return out

    def _refresh(self):
        self.table.setRowCount(len(self._rules))
        for r, rule in enumerate(self._rules):
            type_item = QTableWidgetItem(self._type_label(rule.type))
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_item = QTableWidgetItem(describe_rule(rule))
            desc_item.setToolTip(describe_rule(rule))
            self.table.setItem(r, 0, type_item)
            self.table.setItem(r, 1, desc_item)

    @staticmethod
    def _type_label(rtype: str) -> str:
        return dict(_TYPE_CHOICES).get(rtype, rtype)

    def _selected_rule(self) -> int:
        return self.table.currentRow()

    def _add(self):
        if not self._columns:
            QMessageBox.information(self, "提示", "当前结果表还没有可用字段")
            return
        dlg = RuleEditDialog(self._columns, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.rule():
            self._rules.append(dlg.rule())
            self._refresh()
            self.table.selectRow(len(self._rules) - 1)

    def _edit(self):
        row = self._selected_rule()
        if not (0 <= row < len(self._rules)):
            return
        dlg = RuleEditDialog(self._columns, self._rules[row], self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.rule():
            self._rules[row] = dlg.rule()
            self._refresh()
            self.table.selectRow(row)

    def _delete(self):
        row = self._selected_rule()
        if not (0 <= row < len(self._rules)):
            return
        self._rules.pop(row)
        self._refresh()
        if self._rules:
            self.table.selectRow(min(row, len(self._rules) - 1))

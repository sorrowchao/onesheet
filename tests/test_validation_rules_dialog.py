"""校验规则对话框单元测试（离屏）。"""
import sys
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

from app.core.models import (FieldMapping, OutputTable, SheetConfig,
                             ValidationRule)
from app.ui.validation_rules_dialog import RuleEditDialog, ValidationRulesDialog

# 必须在构造任何 QWidget 之前创建 QApplication。
_app = QApplication.instance() or QApplication(sys.argv)


class RuleEditDialogTest(unittest.TestCase):
    def _dialog(self, columns=None, rule=None):
        return RuleEditDialog(columns or ["姓名", "金额"], rule)

    def _set_type(self, dialog, rtype):
        dialog.type_combo.setCurrentIndex(dialog.type_combo.findData(rtype))

    def test_required_rule(self):
        d = self._dialog()
        self._set_type(d, "required")
        d.col_combo.setCurrentText("姓名")
        d.accept()
        self.assertEqual(d.rule(),
                         ValidationRule(type="required", columns=["姓名"]))

    def test_number_rule_with_range(self):
        d = self._dialog()
        self._set_type(d, "number")
        d.col_combo.setCurrentText("金额")
        d.min_edit.setText("10")
        d.max_edit.setText("20")
        d.accept()
        rule = d.rule()
        self.assertEqual((rule.min, rule.max), (10.0, 20.0))

    def test_number_invalid_text_keeps_dialog_open(self):
        d = self._dialog()
        self._set_type(d, "number")
        d.col_combo.setCurrentText("金额")
        d.min_edit.setText("abc")
        with mock.patch(
                "app.ui.validation_rules_dialog.QMessageBox.warning") as warn:
            d.accept()
        warn.assert_called_once()
        self.assertIsNone(d.rule())

    def test_number_min_greater_than_max_rejected(self):
        d = self._dialog()
        self._set_type(d, "number")
        d.col_combo.setCurrentText("金额")
        d.min_edit.setText("20")
        d.max_edit.setText("10")
        with mock.patch(
                "app.ui.validation_rules_dialog.QMessageBox.warning") as warn:
            d.accept()
        warn.assert_called_once()
        self.assertIsNone(d.rule())

    def test_unique_rule_multi_columns(self):
        d = self._dialog(["姓名", "工号"])
        self._set_type(d, "unique")
        d._select_columns(["姓名", "工号"])
        d.accept()
        self.assertEqual(d.rule().type, "unique")
        self.assertEqual(d.rule().columns, ["姓名", "工号"])

    def test_no_column_rejected(self):
        d = self._dialog()
        self._set_type(d, "unique")
        d._select_columns([])
        with mock.patch(
                "app.ui.validation_rules_dialog.QMessageBox.warning") as warn:
            d.accept()
        warn.assert_called_once()
        self.assertIsNone(d.rule())

    def test_sum_rule(self):
        d = self._dialog(["基本工资", "绩效", "总计"])
        self._set_type(d, "sum")
        d._select_columns(["基本工资", "绩效"])
        d.target_combo.setCurrentText("总计")
        d.tol_spin.setValue(0.5)
        d.accept()
        rule = d.rule()
        self.assertEqual(rule.type, "sum")
        self.assertEqual(rule.target, "总计")
        self.assertEqual(rule.columns, ["基本工资", "绩效"])
        self.assertAlmostEqual(rule.tolerance, 0.5)

    def test_load_existing_rule_round_trip(self):
        rule = ValidationRule(type="number", columns=["金额"], min=1, max=2)
        d = self._dialog(rule=rule)
        d.accept()
        self.assertEqual(d.rule(), rule)


class ValidationRulesDialogTest(unittest.TestCase):
    def setUp(self):
        self.ot = OutputTable(
            name="汇总", sheet=SheetConfig(),
            fields=[FieldMapping(target="姓名"), FieldMapping(target="金额"),
                    FieldMapping(target="金额")],
            validations=[ValidationRule(type="required", columns=["姓名"])])
        self.dlg = ValidationRulesDialog(self.ot)

    def tearDown(self):
        self.dlg.deleteLater()

    def test_available_columns_skips_empty_and_duplicates(self):
        self.assertEqual(
            ValidationRulesDialog._available_columns(self.ot),
            ["姓名", "金额"])

    def test_lists_existing_rules(self):
        self.assertEqual(self.dlg.table.rowCount(), 1)
        self.assertEqual(self.dlg.table.item(0, 0).text(), "必填")
        self.assertIn("姓名", self.dlg.table.item(0, 1).text())

    def test_rules_returns_copies(self):
        rules = self.dlg.rules()
        rules[0].columns.append("金额")
        self.assertEqual(self.dlg.rules()[0].columns, ["姓名"])

    def test_delete_rule(self):
        self.dlg.table.selectRow(0)
        self.dlg._delete()
        self.assertEqual(self.dlg.rules(), [])
        self.assertEqual(self.dlg.table.rowCount(), 0)

    def test_type_label(self):
        self.assertEqual(ValidationRulesDialog._type_label("sum"), "合计")
        self.assertEqual(ValidationRulesDialog._type_label("other"), "other")


if __name__ == "__main__":
    unittest.main()

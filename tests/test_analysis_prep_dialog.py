"""分析准备对话框单元测试（离屏）。"""
import sys
import unittest
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.core.models import (AggregateSpec, CleanupSpec, DerivedColumn,
                             FieldMapping, GroupBySpec, OutputTable, RowFilter,
                             SheetConfig, StatsSpec)
from app.ui.analysis_prep_dialog import (AggregateEditDialog,
                                         AnalysisPrepDialog,
                                         DerivedColumnEditDialog,
                                         FilterEditDialog)

# 必须在构造任何 QWidget 之前创建 QApplication。
_app = QApplication.instance() or QApplication(sys.argv)


def _table(**kwargs):
    return OutputTable(
        name="汇总", sheet=SheetConfig(),
        fields=[FieldMapping(target="工资"), FieldMapping(target="绩效")],
        **kwargs)


class DerivedColumnEditDialogTest(unittest.TestCase):
    def test_valid_column(self):
        d = DerivedColumnEditDialog(["工资", "绩效"], ["工资", "绩效"])
        d.target_edit.setText("合计")
        d.formula_edit.setText("[工资] + [绩效]")
        d.accept()
        self.assertEqual(d.column().target, "合计")
        self.assertEqual(d.column().formula, "[工资] + [绩效]")

    def test_empty_target_rejected(self):
        d = DerivedColumnEditDialog(["工资"], ["工资"])
        d.formula_edit.setText("[工资]")
        with mock.patch(
                "app.ui.analysis_prep_dialog.QMessageBox.warning") as warn:
            d.accept()
        warn.assert_called_once()
        self.assertIsNone(d.column())

    def test_duplicate_export_column_rejected(self):
        d = DerivedColumnEditDialog(["工资"], ["工资"])
        d.target_edit.setText("工资")
        d.formula_edit.setText("1 + 1")
        with mock.patch(
                "app.ui.analysis_prep_dialog.QMessageBox.warning") as warn:
            d.accept()
        warn.assert_called_once()
        self.assertIsNone(d.column())

    def test_invalid_formula_rejected(self):
        d = DerivedColumnEditDialog(["工资"], ["工资"])
        d.target_edit.setText("坏")
        d.formula_edit.setText("__import__('os')")
        with mock.patch(
                "app.ui.analysis_prep_dialog.QMessageBox.warning") as warn:
            d.accept()
        warn.assert_called_once()
        self.assertIsNone(d.column())

    def test_insert_reference(self):
        d = DerivedColumnEditDialog(["工资"], ["工资"])
        d._insert_ref(1)
        self.assertIn("[工资]", d.formula_edit.text())


class FilterEditDialogTest(unittest.TestCase):
    def test_empty_op_hides_value(self):
        d = FilterEditDialog(["工资"])
        d.op_combo.setCurrentIndex(d.op_combo.findData("not_empty"))
        self.assertTrue(d.value_edit.isHidden())
        d.accept()
        self.assertEqual(d.filter(), RowFilter(column="工资", op="not_empty"))

    def test_numeric_op(self):
        d = FilterEditDialog(["工资"])
        d.op_combo.setCurrentIndex(d.op_combo.findData("gt"))
        d.value_edit.setText("100")
        d.accept()
        self.assertEqual(d.filter(), RowFilter(column="工资", op="gt",
                                               value="100"))


class AggregateEditDialogTest(unittest.TestCase):
    def test_default(self):
        d = AggregateEditDialog(["工资"])
        d.func_combo.setCurrentIndex(d.func_combo.findData("avg"))
        d.accept()
        self.assertEqual(d.aggregate(),
                         AggregateSpec(column="工资", func="avg"))


class AnalysisPrepDialogTest(unittest.TestCase):
    def test_four_tabs(self):
        d = AnalysisPrepDialog(_table())
        texts = [d.tabs.tabText(i) for i in range(d.tabs.count())]
        self.assertEqual(texts, ["派生列", "清洗/去重", "分组汇总", "描述统计"])

    def test_specs_clones(self):
        ot = _table(
            derived_columns=[DerivedColumn(target="合计", formula="[工资]")],
            cleanup=CleanupSpec(trim=True),
            group_by=GroupBySpec(enabled=True, group_columns=["工资"]),
            stats=StatsSpec(enabled=True))
        d = AnalysisPrepDialog(ot)
        derived, cleanup, group_by, stats = d.specs()
        self.assertEqual(derived[0].target, "合计")
        self.assertTrue(cleanup.trim)
        self.assertTrue(group_by.enabled)
        self.assertTrue(stats.enabled)
        # 返回的是拷贝：改动不影响内部状态
        derived[0].target = "改"
        cleanup.trim = False
        derived2, cleanup2, _, _ = d.specs()
        self.assertEqual(derived2[0].target, "合计")
        self.assertTrue(cleanup2.trim)

    def test_enabled_toggles_round_trip(self):
        ot = _table(group_by=GroupBySpec(enabled=True),
                    stats=StatsSpec(enabled=True))
        d = AnalysisPrepDialog(ot)
        self.assertTrue(d.specs()[2].enabled)
        self.assertTrue(d.specs()[3].enabled)
        d.group_enabled_cb.setChecked(False)
        d.stats_enabled_cb.setChecked(False)
        _, _, group_by, stats = d.specs()
        self.assertFalse(group_by.enabled)
        self.assertFalse(stats.enabled)

    def test_dedupe_and_group_columns(self):
        ot = _table(
            cleanup=CleanupSpec(dedupe=True, dedupe_columns=["工资"]),
            group_by=GroupBySpec(enabled=True, group_columns=["绩效"]))
        d = AnalysisPrepDialog(ot)
        _, cleanup, group_by, _ = d.specs()
        self.assertEqual(cleanup.dedupe_columns, ["工资"])
        self.assertEqual(group_by.group_columns, ["绩效"])

    def test_stats_all_columns_default(self):
        d = AnalysisPrepDialog(_table(stats=StatsSpec(enabled=True)))
        self.assertTrue(d.stats_all_cb.isChecked())
        _, _, _, stats = d.specs()
        self.assertEqual(stats.columns, [])

    def test_stats_metrics_round_trip(self):
        d = AnalysisPrepDialog(_table(
            stats=StatsSpec(enabled=True, metrics=["avg"])))
        _, _, _, stats = d.specs()
        self.assertEqual(stats.metrics, ["avg"])
        # 指标列表默认全部勾选时返回全部键
        d2 = AnalysisPrepDialog(_table(stats=StatsSpec(enabled=True)))
        _, _, _, stats2 = d2.specs()
        self.assertEqual(stats2.metrics,
                         ["count", "sum", "avg", "median", "min", "max", "std"])


if __name__ == "__main__":
    unittest.main()

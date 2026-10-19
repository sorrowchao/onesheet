"""ConfigPanel 字段上移/下移测试（离屏）。"""
import sys
import unittest
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QMessageBox,
                               QTableWidgetSelectionRange)

from app.core.models import FieldMapping
from app.ui.config_panel import ConfigPanel

# 必须在构造任何 QWidget 之前创建 QApplication。
_app = QApplication.instance() or QApplication(sys.argv)


def _fields(*names):
    return [FieldMapping(target=n, source="kv", key=n) for n in names]


class MoveFieldTest(unittest.TestCase):
    def setUp(self):
        self.panel = ConfigPanel()
        self.panel.set_form_fields(_fields("A", "B", "C", "D"))

    def tearDown(self):
        self.panel.deleteLater()

    def _order(self):
        return [f.target for f in self.panel._form_fields]

    def test_move_down(self):
        self.panel.fields_table.setCurrentCell(0, 1)
        self.panel._move_field(1)
        self.assertEqual(self._order(), ["B", "A", "C", "D"])

    def test_move_up(self):
        self.panel.fields_table.setCurrentCell(3, 1)
        self.panel._move_field(-1)
        self.assertEqual(self._order(), ["A", "B", "D", "C"])

    def test_bounds_noop(self):
        self.panel.fields_table.setCurrentCell(0, 1)
        self.panel._move_field(-1)  # 已在顶部
        self.assertEqual(self._order(), ["A", "B", "C", "D"])
        self.panel.fields_table.setCurrentCell(3, 1)
        self.panel._move_field(1)  # 已在底部
        self.assertEqual(self._order(), ["A", "B", "C", "D"])

    def test_field_cells_centered(self):
        self.assertEqual(
            self.panel.fields_table.verticalHeader().defaultAlignment(),
            Qt.AlignmentFlag.AlignCenter)
        for r in range(self.panel.fields_table.rowCount()):
            for c in range(self.panel.fields_table.columnCount()):
                item = self.panel.fields_table.item(r, c)
                self.assertTrue(
                    item.textAlignment() & Qt.AlignmentFlag.AlignHCenter,
                    f"单元格 ({r}, {c}) 未水平居中")

    def test_checked_state_moves_with_field(self):
        # 取消勾选 B（索引 1），把 A 与 B 交换后，未勾选状态应落到 B 的新位置
        self.panel.fields_table.item(1, 0).setCheckState(Qt.Unchecked)
        self.panel._read_fields_table()
        self.panel.fields_table.setCurrentCell(0, 1)
        self.panel._move_field(1)
        self.assertEqual(self._order(), ["B", "A", "C", "D"])
        self.assertNotIn(0, self.panel._checked)  # B 仍未勾选
        self.assertIn(1, self.panel._checked)     # A 仍勾选


class DragMoveToTest(unittest.TestCase):
    """拖动重排：_move_field_to(源行, 目标插入行)。"""

    def setUp(self):
        self.panel = ConfigPanel()
        self.panel.set_form_fields(_fields("A", "B", "C", "D"))

    def tearDown(self):
        self.panel.deleteLater()

    def _order(self):
        return [f.target for f in self.panel._form_fields]

    def test_drag_to_end(self):
        self.panel._move_field_to(0, 4)          # A 拖到最后
        self.assertEqual(self._order(), ["B", "C", "D", "A"])

    def test_drag_to_front(self):
        self.panel._move_field_to(3, 0)          # D 拖到最前
        self.assertEqual(self._order(), ["D", "A", "B", "C"])

    def test_drag_to_middle(self):
        self.panel._move_field_to(0, 3)          # A 拖到 C 之后
        self.assertEqual(self._order(), ["B", "C", "A", "D"])

    def test_drag_same_position_noop(self):
        self.panel._move_field_to(1, 1)          # 放到自己上面
        self.panel._move_field_to(1, 2)          # 放到自己下面
        self.assertEqual(self._order(), ["A", "B", "C", "D"])

    def test_drag_checked_state_moves(self):
        self.panel.fields_table.item(0, 0).setCheckState(Qt.Unchecked)  # A 不勾
        self.panel._read_fields_table()
        self.panel._move_field_to(0, 4)          # A 拖到最后
        self.assertEqual(self._order(), ["B", "C", "D", "A"])
        self.assertNotIn(3, self.panel._checked)  # A 到末尾仍不勾
        self.assertTrue({0, 1, 2} <= self.panel._checked)


class DeleteAndClearTest(unittest.TestCase):
    """删除选中（可多选）与清空全部字段。"""

    def setUp(self):
        self.panel = ConfigPanel()
        self.panel.set_form_fields(_fields("A", "B", "C", "D"))

    def tearDown(self):
        self.panel.deleteLater()

    def _order(self):
        return [f.target for f in self.panel._form_fields]

    def test_delete_single(self):
        self.panel.fields_table.selectRow(1)   # B
        self.panel._del_field_row()
        self.assertEqual(self._order(), ["A", "C", "D"])

    def test_delete_multiple(self):
        self.panel.fields_table.setRangeSelected(
            QTableWidgetSelectionRange(1, 0, 2, 4), True)  # B + C
        self.panel._del_field_row()
        self.assertEqual(self._order(), ["A", "D"])

    def test_delete_multiple_noncontiguous_remaps_checked(self):
        self.panel.fields_table.item(2, 0).setCheckState(Qt.Unchecked)  # C 不勾
        self.panel._read_fields_table()
        # 选中 B(1) 与 D(3)，删掉后剩 A、C
        self.panel.fields_table.setRangeSelected(
            QTableWidgetSelectionRange(1, 0, 1, 4), True)
        self.panel.fields_table.setRangeSelected(
            QTableWidgetSelectionRange(3, 0, 3, 4), True)
        self.panel._del_field_row()
        self.assertEqual(self._order(), ["A", "C"])
        self.assertIn(0, self.panel._checked)      # A 仍勾选
        self.assertNotIn(1, self.panel._checked)   # C 到索引 1，仍未勾选

    def test_invert_checked(self):
        self.panel.fields_table.item(1, 0).setCheckState(Qt.Unchecked)  # B 不勾
        self.panel._read_fields_table()
        self.panel._invert_checked()
        self.assertEqual(self.panel._checked, {1})

    def test_clear_form_only_unchecks(self):
        self.panel._clear_form()                    # 全不选
        self.assertEqual(self._order(), ["A", "B", "C", "D"])  # 字段仍在
        self.assertEqual(self.panel._checked, set())

    def test_clear_all_removes_fields(self):
        with mock.patch("app.ui.config_panel.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.Yes):
            self.panel._clear_all_form()
        self.assertEqual(self._order(), [])
        self.assertEqual(self.panel._checked, set())

    def test_clear_all_cancel_keeps_fields(self):
        with mock.patch("app.ui.config_panel.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.No):
            self.panel._clear_all_form()
        self.assertEqual(self._order(), ["A", "B", "C", "D"])


class AiScanButtonTest(unittest.TestCase):
    """点击「AI 扫描表单」按钮应发出 ai_scan_requested 信号。"""

    def setUp(self):
        self.panel = ConfigPanel()

    def tearDown(self):
        self.panel.deleteLater()

    def test_click_emits_signal(self):
        fired = []
        self.panel.ai_scan_requested.connect(lambda: fired.append(True))
        self.panel.btn_ai.click()
        self.assertEqual(fired, [True])


class TemplateButtonTest(unittest.TestCase):
    """点击「打开模板 / 保存模板」按钮应发出对应信号。"""

    def setUp(self):
        self.panel = ConfigPanel()

    def tearDown(self):
        self.panel.deleteLater()

    def test_template_buttons_emit_signals(self):
        open_fired, save_fired = [], []
        self.panel.open_template_requested.connect(lambda: open_fired.append(True))
        self.panel.save_template_requested.connect(lambda: save_fired.append(True))
        self.panel.btn_open_tpl.click()
        self.panel.btn_save_tpl.click()
        self.assertEqual(open_fired, [True])
        self.assertEqual(save_fired, [True])


class KeyComboTest(unittest.TestCase):
    """「主键字段」下拉框：单选，且进入 get_template 的字段。"""

    def setUp(self):
        self.panel = ConfigPanel()
        self.panel.set_form_fields(_fields("A", "B", "C"))

    def tearDown(self):
        self.panel.deleteLater()

    def _keys(self):
        return [f.target for f in self.panel._form_fields if f.is_key]

    def test_default_is_none(self):
        self.assertEqual(self.panel.key_combo.currentIndex(), 0)
        self.assertEqual(self._keys(), [])

    def test_select_one_key(self):
        self.panel.key_combo.setCurrentIndex(2)  # 第 2 项 = 字段 B
        self.assertEqual(self._keys(), ["B"])

    def test_select_new_key_replaces_old(self):
        self.panel.key_combo.setCurrentIndex(2)  # B
        self.panel.key_combo.setCurrentIndex(3)  # C
        self.assertEqual(self._keys(), ["C"])

    def test_back_to_none_clears(self):
        self.panel.key_combo.setCurrentIndex(1)
        self.panel.key_combo.setCurrentIndex(0)
        self.assertEqual(self._keys(), [])

    def test_key_reaches_template(self):
        self.panel.key_combo.setCurrentIndex(1)  # A
        tpl = self.panel.get_template()
        fields = tpl.output_tables[0].fields
        self.assertEqual([f.target for f in fields if f.is_key], ["A"])

    def test_key_follows_reorder(self):
        self.panel.key_combo.setCurrentIndex(1)  # A 为主键
        self.panel.fields_table.setCurrentCell(0, 1)
        self.panel._move_field(1)                # A 下移
        self.assertEqual(self._keys(), ["A"])
        tpl = self.panel.get_template()
        self.assertEqual([f.target for f in tpl.output_tables[0].fields if f.is_key], ["A"])


class FieldSelectedSignalTest(unittest.TestCase):
    """字段表当前行变化 → field_selected 信号（供预览区定位）。"""

    def setUp(self):
        self.panel = ConfigPanel()
        self.panel.set_form_fields(self.panel_fields())
        self.got = []
        self.panel.field_selected.connect(self.got.append)

    def tearDown(self):
        self.panel.deleteLater()

    @staticmethod
    def panel_fields():
        return [FieldMapping(target=n, source="kv", key=n) for n in ("A", "B")]

    def test_selecting_row_emits_field(self):
        self.panel.fields_table.setCurrentCell(1, 1)
        self.assertEqual([f.target for f in self.got], ["B"])

    def test_rebuild_does_not_emit(self):
        self.got.clear()
        self.panel.set_form_fields(self.panel_fields())
        self.assertEqual(self.got, [])


class FilenameFieldTest(unittest.TestCase):
    """「添加文件名」按钮：添加 filename 字段，值预览来自当前文件路径。"""

    def setUp(self):
        self.panel = ConfigPanel()
        self.panel.set_form_fields(_fields("A"))
        self.panel.set_current_file("C:/data/国能混凝土107-1.xlsx")

    def tearDown(self):
        self.panel.deleteLater()

    def test_button_label(self):
        self.assertEqual(self.panel.btn_add_filename.text(), "添加文件名")

    def test_adds_filename_row(self):
        self.panel._add_filename_field()
        f = self.panel._form_fields[-1]
        self.assertEqual(f.source, "filename")
        self.assertEqual(f.target, "文件名")
        self.assertIsNone(f.value_row)
        self.assertIsNone(f.value_col)
        self.assertEqual(self.panel.fields_table.rowCount(), 2)
        self.assertEqual(self.panel.fields_table.item(1, 4).text(), "国能混凝土")

    def test_position_cells_not_editable(self):
        self.panel._add_filename_field()
        r = len(self.panel._form_fields) - 1
        for col in (2, 3):
            flags = self.panel.fields_table.item(r, col).flags()
            self.assertFalse(flags & Qt.ItemFlag.ItemIsEditable)

    def test_no_duplicate_filename_field(self):
        self.panel._add_filename_field()
        self.panel._add_filename_field()
        count = sum(1 for f in self.panel._form_fields if f.source == "filename")
        self.assertEqual(count, 1)

    def test_preview_falls_back_to_folder(self):
        self.panel.set_current_file("C:/data/采购部/107-1.xlsx")
        self.panel._add_filename_field()
        f = self.panel._form_fields[-1]
        self.assertEqual(self.panel._preview_text(f), "采购部")

    def test_filename_field_reaches_template(self):
        self.panel._add_filename_field()
        fields = self.panel.get_template().output_tables[0].fields
        self.assertEqual([f.source for f in fields], ["kv", "filename"])


if __name__ == "__main__":
    unittest.main()

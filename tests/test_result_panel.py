"""ResultPanel / ResultTableWidget 单元测试（离屏）。

覆盖：结果填充、复制粘贴 TSV、撤销/重做、插入/删除行并重排序号、
清除内容、编辑后按原始类型读回。
"""
import sys
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QTableWidget,
                               QTableWidgetSelectionRange)

from app.core.models import ResultTable
from app.ui.result_panel import ResultPanel

# 必须在构造任何 QWidget 之前创建 QApplication。
_app = QApplication.instance() or QApplication(sys.argv)


def make_result():
    return ResultTable(
        name="汇总", columns=["序号", "姓名", "年龄"],
        rows=[[1, "张三", 34], [2, "李四", 25]],
    )


class ResultPanelTest(unittest.TestCase):
    def setUp(self):
        self.panel = ResultPanel()
        self.panel.show_results({"汇总": make_result()})
        self.w = self.panel.widget(0)
        self.assertIsInstance(self.w, QTableWidget)

    def tearDown(self):
        self.panel.deleteLater()

    def select(self, top, left, bottom, right):
        self.w.clearSelection()
        self.w.setRangeSelected(
            QTableWidgetSelectionRange(top, left, bottom, right), True)

    # ------------------------------------------------------------------
    # 填充 / 读回
    # ------------------------------------------------------------------
    def test_show_results_populates(self):
        self.assertEqual(self.w.rowCount(), 2)
        self.assertEqual(self.w.columnCount(), 3)
        self.assertEqual(self.w.horizontalHeaderItem(1).text(), "姓名")
        self.assertEqual(self.w.item(0, 1).text(), "张三")

    def test_cells_and_row_header_centered(self):
        self.assertEqual(self.w.verticalHeader().defaultAlignment(),
                         Qt.AlignmentFlag.AlignCenter)
        for r in range(self.w.rowCount()):
            for c in range(self.w.columnCount()):
                item = self.w.item(r, c)
                self.assertTrue(
                    item.textAlignment() & Qt.AlignmentFlag.AlignHCenter,
                    f"结果单元格 ({r}, {c}) 未水平居中")

    def test_pasted_cells_centered(self):
        QApplication.clipboard().setText("甲\t乙")
        self.w.setCurrentCell(0, 2)
        self.w.paste()
        self.assertIsNotNone(self.w.item(0, 3))  # 粘贴自动扩展出的新单元格
        self.assertTrue(
            self.w.item(0, 3).textAlignment() & Qt.AlignmentFlag.AlignHCenter)

    def test_read_results_coerces_edited_number_back_to_number(self):
        self.w.item(0, 2).setText("36")
        tables = self.panel.read_results()
        self.assertEqual(tables["汇总"].rows[0][2], 36)
        self.assertIsInstance(tables["汇总"].rows[0][2], int)

    def test_read_results_keeps_text_as_text(self):
        self.w.item(0, 1).setText("王五")
        tables = self.panel.read_results()
        self.assertEqual(tables["汇总"].rows[0][1], "王五")

    def test_read_results_empty_cell_is_none(self):
        self.w.item(0, 1).setText("")
        tables = self.panel.read_results()
        self.assertIsNone(tables["汇总"].rows[0][1])

    # ------------------------------------------------------------------
    # 复制 / 粘贴
    # ------------------------------------------------------------------
    def test_copy_selection_as_tsv(self):
        self.select(0, 0, 1, 1)
        self.w.copy_selection()
        text = QApplication.clipboard().text()
        self.assertEqual(text, "1\t张三\n2\t李四")

    def test_paste_tsv(self):
        self.w.setCurrentCell(0, 0)
        QApplication.clipboard().setText("9\t王五\n8\t赵六")
        self.w.paste()
        self.assertEqual(self.w.item(0, 0).text(), "9")
        self.assertEqual(self.w.item(0, 1).text(), "王五")
        self.assertEqual(self.w.item(1, 0).text(), "8")
        self.assertEqual(self.w.item(1, 1).text(), "赵六")

    def test_paste_expands_rows_and_columns(self):
        self.w.setCurrentCell(1, 2)
        QApplication.clipboard().setText("a\tb\nc\td")
        self.w.paste()
        self.assertEqual(self.w.rowCount(), 3)
        self.assertEqual(self.w.columnCount(), 4)
        self.assertEqual(self.w.item(2, 3).text(), "d")

    # ------------------------------------------------------------------
    # 撤销 / 重做
    # ------------------------------------------------------------------
    def test_undo_redo_edit(self):
        self.w.item(0, 1).setText("王五")
        self.assertEqual(self.w.item(0, 1).text(), "王五")
        self.w.undo()
        self.assertEqual(self.w.item(0, 1).text(), "张三")
        self.w.redo()
        self.assertEqual(self.w.item(0, 1).text(), "王五")

    def test_undo_paste(self):
        self.w.setCurrentCell(0, 0)
        QApplication.clipboard().setText("x\ty")
        self.w.paste()
        self.w.undo()
        self.assertEqual(self.w.item(0, 0).text(), "1")
        self.assertEqual(self.w.item(0, 1).text(), "张三")

    # ------------------------------------------------------------------
    # 行操作 / 清除
    # ------------------------------------------------------------------
    def test_insert_row_above_renumbers_seq(self):
        self.w.setCurrentCell(1, 0)
        self.w.insert_row_above()
        self.assertEqual(self.w.rowCount(), 3)
        self.assertEqual([self.w.item(r, 0).text() for r in range(3)],
                         ["1", "2", "3"])

    def test_delete_selected_rows_renumbers_seq(self):
        self.w.selectRow(0)
        self.w.delete_selected_rows()
        self.assertEqual(self.w.rowCount(), 1)
        self.assertEqual(self.w.item(0, 0).text(), "1")
        self.assertEqual(self.w.item(0, 1).text(), "李四")

    def test_clear_selected_cells(self):
        self.select(0, 1, 1, 2)
        self.w.clear_selected_cells()
        for r in (0, 1):
            for c in (1, 2):
                self.assertEqual(self.w.item(r, c).text(), "")
        # 未选中的序号列不受影响
        self.assertEqual(self.w.item(0, 0).text(), "1")

    def test_undo_insert_row(self):
        self.w.setCurrentCell(1, 0)
        self.w.insert_row_above()
        self.w.undo()
        self.assertEqual(self.w.rowCount(), 2)


if __name__ == "__main__":
    unittest.main()

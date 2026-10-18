"""PreviewPanel 字段定位测试（离屏）。"""
import sys
import unittest

from PySide6.QtWidgets import QApplication

from app.core.models import FieldMapping, SheetData
from app.ui.preview_panel import PreviewPanel

# 必须在构造任何 QWidget 之前创建 QApplication。
_app = QApplication.instance() or QApplication(sys.argv)


def make_sheet():
    grid = [["姓名", "张三", "备注"],
            ["性别", "男", None]]
    return SheetData(name="表1", grid=grid, merged=[],
                     max_row=2, max_col=3)


class HighlightFieldTest(unittest.TestCase):
    def setUp(self):
        self.panel = PreviewPanel()
        self.panel.set_sheets([make_sheet()])

    def tearDown(self):
        self.panel.deleteLater()

    def _selected(self):
        return {(i.row(), i.column())
                for i in self.panel.table.selectedIndexes()}

    def test_highlights_label_and_value(self):
        field = FieldMapping(target="姓名", key="姓名",
                             label_row=1, label_col=1,
                             value_row=1, value_col=2)
        self.panel.highlight_field(field)
        self.assertEqual(self._selected(), {(0, 0), (0, 1)})
        self.assertEqual(self.panel.table.currentRow(), 0)
        self.assertEqual(self.panel.table.currentColumn(), 1)

    def test_falls_back_to_label_text_when_no_positions(self):
        field = FieldMapping(target="性别", key="性别")
        self.panel.highlight_field(field)
        self.assertEqual(self._selected(), {(1, 0)})

    def test_unknown_text_selects_nothing(self):
        field = FieldMapping(target="不存在", key="不存在")
        self.panel.highlight_field(field)
        self.assertEqual(self._selected(), set())

    def test_out_of_range_ignored(self):
        field = FieldMapping(target="越界", key="越界",
                             label_row=99, label_col=99)
        self.panel.highlight_field(field)
        self.assertEqual(self._selected(), set())


if __name__ == "__main__":
    unittest.main()

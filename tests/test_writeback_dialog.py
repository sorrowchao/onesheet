"""WriteBackDialog 匹配字段默认勾选测试（离屏）。"""
import sys
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.core.models import FieldMapping, OutputTable, ResultTable, SheetConfig
from app.main_window import WriteBackDialog

# 必须在构造任何 QWidget 之前创建 QApplication。
_app = QApplication.instance() or QApplication(sys.argv)

COLS = ["序号", "单位详细名称", "项目经费", "姓名"]


def _table(rows):
    return ResultTable(name="t", columns=list(COLS), rows=rows)


def _output_table(key: bool):
    return OutputTable(
        name="t",
        sheet=SheetConfig(),
        fields=[
            FieldMapping(target="单位详细名称", is_key=key, value_row=5, value_col=2),
            FieldMapping(target="项目经费", value_row=7, value_col=13),
            FieldMapping(target="姓名", value_row=2, value_col=2),
        ],
    )


class WriteBackDefaultTest(unittest.TestCase):
    def _dialog(self, ot, edited, original):
        return WriteBackDialog({"t": edited}, [ot], {"t": original})

    def _checked(self, dlg):
        return [dlg.key_list.item(i).text() for i in range(dlg.key_list.count())
                if dlg.key_list.item(i).checkState() == Qt.Checked]

    def test_key_checked_others_not(self):
        rt = _table([[1, "A厂", 10, "张三"]])
        dlg = self._dialog(_output_table(key=True), rt, rt)
        self.assertEqual(self._checked(dlg), ["单位详细名称"])
        self.assertEqual(dlg.key_cols(), [1])  # COLS 中「单位详细名称」的下标

    def test_no_key_all_unchanged_checked(self):
        rt = _table([[1, "A厂", 10, "张三"]])
        dlg = self._dialog(_output_table(key=False), rt, rt)
        self.assertEqual(self._checked(dlg), ["单位详细名称", "项目经费", "姓名"])

    def test_no_key_changed_column_unchecked(self):
        original = _table([[1, "A厂", 10, "张三"]])
        edited = _table([[1, "A厂", 99, "张三"]])  # 改动了「项目经费」
        dlg = self._dialog(_output_table(key=False), edited, original)
        self.assertEqual(self._checked(dlg), ["单位详细名称", "姓名"])

    def test_key_overrides_changed_logic(self):
        # 主键字段本身被改动过，仍然默认勾选（因为它才是匹配依据）
        original = _table([[1, "A厂", 10, "张三"]])
        edited = _table([[1, "B厂", 10, "张三"]])
        dlg = self._dialog(_output_table(key=True), edited, original)
        self.assertEqual(self._checked(dlg), ["单位详细名称"])


if __name__ == "__main__":
    unittest.main()

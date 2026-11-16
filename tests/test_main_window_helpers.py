"""MainWindow 辅助逻辑测试（不显示窗口）。"""
import unittest

from app.core.models import ExtractTemplate, OutputTable, ResultTable
from app.main_window import MainWindow


class BaseResultTablesTest(unittest.TestCase):
    """反向写入前只保留模板基础表，剔除生成的分组/统计表。"""

    def test_filters_generated_tables(self):
        tpl = ExtractTemplate(output_tables=[OutputTable(name="汇总")])
        edited = {
            "汇总": ResultTable(name="汇总"),
            "汇总（分组汇总）": ResultTable(name="汇总（分组汇总）"),
            "汇总（描述统计）2": ResultTable(name="汇总（描述统计）2"),
            "其它": ResultTable(name="其它"),
        }
        got = MainWindow._base_result_tables(edited, tpl)
        self.assertEqual(list(got), ["汇总"])

    def test_keeps_multiple_base_tables(self):
        tpl = ExtractTemplate(output_tables=[
            OutputTable(name="A"), OutputTable(name="B")])
        edited = {"A": ResultTable(name="A"), "B": ResultTable(name="B"),
                  "A（分组汇总）": ResultTable(name="A（分组汇总）")}
        self.assertEqual(list(MainWindow._base_result_tables(edited, tpl)),
                         ["A", "B"])


class IntSizesTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(MainWindow._int_sizes([1, 2, 3], 3), [1, 2, 3])

    def test_wrong_length(self):
        self.assertIsNone(MainWindow._int_sizes([1, 2], 3))

    def test_invalid_values(self):
        self.assertIsNone(MainWindow._int_sizes([1, "x", 3], 3))
        self.assertIsNone(MainWindow._int_sizes("bad", 3))


if __name__ == "__main__":
    unittest.main()

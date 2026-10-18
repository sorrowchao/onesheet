"""aggregator 单元测试。"""
import unittest

from app.core.aggregator import aggregate
from app.core.models import ResultTable


class TestAggregate(unittest.TestCase):
    def test_merge_and_sort(self):
        files = [
            {"企业汇总": ResultTable(name="企业汇总",
                                    columns=["企业名称", "年份", "指标"],
                                    rows=[["B公司", 2024, 2], ["A公司", 2024, 1]])},
            {"企业汇总": ResultTable(name="企业汇总",
                                    columns=["企业名称", "年份", "指标"],
                                    rows=[["C公司", 2024, 3]])},
        ]
        out = aggregate(files)
        rt = out["企业汇总"]
        self.assertEqual(rt.columns, ["序号", "企业名称", "年份", "指标"])
        # 默认按第一列（企业名称）排序，序号列为 1..N
        self.assertEqual([r[1] for r in rt.rows], ["A公司", "B公司", "C公司"])
        self.assertEqual([r[0] for r in rt.rows], [1, 2, 3])

    def test_union_columns(self):
        files = [
            {"t": ResultTable(name="t", columns=["a", "b"], rows=[[1, 2]])},
            {"t": ResultTable(name="t", columns=["a", "c"], rows=[[3, 4]])},
        ]
        rt = aggregate(files)["t"]
        self.assertEqual(rt.columns, ["序号", "a", "b", "c"])
        self.assertEqual(rt.rows, [[1, 1, 2, None], [2, 3, None, 4]])

    def test_trim_and_drop_empty(self):
        files = [
            {"t": ResultTable(name="t", columns=["a", "b"],
                             rows=[["  x  ", None], [None, None], ["", ""]])},
        ]
        rt = aggregate(files)["t"]
        self.assertEqual(rt.rows, [[1, "x", None]])


if __name__ == "__main__":
    unittest.main()

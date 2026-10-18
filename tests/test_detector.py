"""detector 单元测试。"""
import unittest

from app.core.detector import detect, detect_form_pairs, detect_form_pairs_pos
from app.core.models import SheetData, Region


def make_sheet(grid, name="s"):
    return SheetData(name=name, grid=grid, merged=[], max_row=len(grid),
                     max_col=max((len(r) for r in grid), default=0))


class TestDetect(unittest.TestCase):
    def test_title_then_blank_then_header(self):
        # 元数据行 → 空行 → 表头 → 数据
        grid = [
            ["单位详细名称", None, "测试企业", 2024],
            [None, None, None, None],
            ["甲", None, None, None],
            [1, None, "项目A", 123.5],
        ]
        h, d = detect(make_sheet(grid))
        self.assertEqual(h, Region(3, 1, 3, 1))
        self.assertEqual(d, Region(4, 1, -1, 1))

    def test_kv_table(self):
        # 107-2 式：单行即表头 + 数据
        grid = [
            ["研究开发人员合计", None, 1, None, 10],
            ["研究开发费用合计", None, 7, None, 500],
        ]
        h, d = detect(make_sheet(grid))
        self.assertEqual(h, Region(1, 1, 1, 5))
        self.assertEqual(d, Region(2, 1, -1, 5))

    def test_data_ends_at_three_empty_rows(self):
        grid = [
            ["甲", "乙", "丙"],
            [1, 2, 3],
            [4, 5, 6],
            [None, None, None],
            [None, None, None],
            [None, None, None],
            [9, 9, 9],  # 3 行空行之后的内容，应被截断
        ]
        h, d = detect(make_sheet(grid))
        self.assertEqual(h, Region(1, 1, 1, 3))
        self.assertEqual(d, Region(2, 1, 3, 3))

    def test_empty_sheet(self):
        h, d = detect(make_sheet([]))
        self.assertEqual(h, Region(1, 1, 1, 1))
        self.assertEqual(d, Region(2, 1, -1, 1))


class TestDetectFormPairs(unittest.TestCase):
    def test_form_pairs(self):
        # 张三式表单：两列「标签:值」并排 + 标题行，标签带冒号
        grid = [
            ["工资表", None, None, None],
            ["姓名：", "张三", "性别：", "男"],
            ["年龄：", 34, "部门：", "采购部"],
            ["基本工资：", 4300, "绩效", 1800],
        ]
        pairs = detect_form_pairs(make_sheet(grid))
        self.assertEqual(pairs, [
            ("姓名", "张三"), ("性别", "男"),
            ("年龄", 34), ("部门", "采购部"),
            ("基本工资", 4300), ("绩效", 1800),
        ])

    def test_empty(self):
        self.assertEqual(detect_form_pairs(make_sheet([])), [])

    def test_form_pairs_pos(self):
        # 带位置：标签(2,1)值(2,2)、标签(2,3)值(2,4)，均为 1-based
        grid = [
            ["工资表", None, None, None],
            ["姓名：", "张三", "性别：", "男"],
            ["年龄：", 34, "部门：", "采购部"],
        ]
        pos = detect_form_pairs_pos(make_sheet(grid))
        self.assertEqual(pos, [
            ("姓名", 2, 1, 2, 2), ("性别", 2, 3, 2, 4),
            ("年龄", 3, 1, 3, 2), ("部门", 3, 3, 3, 4),
        ])


if __name__ == "__main__":
    unittest.main()

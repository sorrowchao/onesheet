"""ai_scan.py 单元测试（纯逻辑，不联网）。"""
import unittest

from app.core.ai_scan import (AiScanError, build_messages, build_sheet_text,
                              parse_pairs, recommend_fields)
from app.core.models import FieldMapping, SheetData


def make_sheet():
    grid = [
        ["姓名", "张三", None],
        ["年龄", 34, None],
        ["金额", 1234.0, None],
    ]
    return SheetData(name="表单", grid=grid, merged=[], max_row=3, max_col=2)


class BuildSheetTextTest(unittest.TestCase):
    def test_contains_row_and_col_numbers(self):
        text = build_sheet_text(make_sheet())
        lines = text.splitlines()
        # 每格显式给出列号，只列出非空格
        self.assertEqual(lines[0], "行1: 1=姓名 | 2=张三")
        self.assertEqual(lines[1], "行2: 1=年龄 | 2=34")
        self.assertEqual(lines[2], "行3: 1=金额 | 2=1234.0")

    def test_truncation_note(self):
        sheet = SheetData(name="s", grid=[["a"] * 5 for _ in range(4)],
                          merged=[], max_row=4, max_col=5)
        text = build_sheet_text(sheet, max_rows=2, max_cols=3)
        # 2 行数据 + 1 行附注
        self.assertIn("仅显示前 2 行、前 3 列", text)
        self.assertEqual(len(text.splitlines()), 3)

    def test_no_note_when_small(self):
        text = build_sheet_text(make_sheet())
        self.assertNotIn("仅显示", text)


class ParsePairsTest(unittest.TestCase):
    def setUp(self):
        self.sheet = make_sheet()

    def test_normal_json(self):
        content = ('{"pairs":[{"label":"姓名","label_row":1,"label_col":1,'
                   '"value_row":1,"value_col":2}]}')
        fields = parse_pairs(content, self.sheet)
        self.assertEqual(len(fields), 1)
        f = fields[0]
        self.assertIsInstance(f, FieldMapping)
        self.assertEqual(f.target, "姓名")
        self.assertEqual(f.key, "姓名")
        self.assertEqual(f.source, "kv")
        self.assertEqual((f.label_row, f.label_col, f.value_row, f.value_col),
                         (1, 1, 1, 2))

    def test_code_fence_stripped(self):
        content = ('```json\n{"pairs":[{"label":"姓名","label_row":1,"label_col":1,'
                   '"value_row":1,"value_col":2}]}\n```')
        fields = parse_pairs(content, self.sheet)
        self.assertEqual([f.target for f in fields], ["姓名"])

    def test_bare_array_accepted(self):
        content = '[{"label":"年龄","value_row":2,"value_col":2}]'
        fields = parse_pairs(content, self.sheet)
        self.assertEqual([f.target for f in fields], ["年龄"])

    def test_label_colon_stripped(self):
        content = '{"pairs":[{"label":"姓名：","value_row":1,"value_col":2}]}'
        fields = parse_pairs(content, self.sheet)
        self.assertEqual([f.target for f in fields], ["姓名"])

    def test_out_of_range_value_dropped(self):
        content = '{"pairs":[{"label":"X","value_row":99,"value_col":1}]}'
        self.assertEqual(parse_pairs(content, self.sheet), [])

    def test_missing_value_coords_dropped(self):
        content = '{"pairs":[{"label":"X","label_row":1,"label_col":1}]}'
        self.assertEqual(parse_pairs(content, self.sheet), [])

    def test_empty_value_cell_dropped(self):
        # 有标签但取值格为空 → 丢弃（第 3 列全为空）
        content = ('{"pairs":[{"label":"空列","value_row":1,"value_col":3},'
                   '{"label":"姓名","value_row":1,"value_col":2}]}')
        fields = parse_pairs(content, self.sheet)
        self.assertEqual([f.target for f in fields], ["姓名"])

    def test_whitespace_value_cell_dropped(self):
        sheet = SheetData(name="s", grid=[["标签", "   "]], merged=[],
                          max_row=1, max_col=2)
        content = '{"pairs":[{"label":"标签","value_row":1,"value_col":2}]}'
        self.assertEqual(parse_pairs(content, sheet), [])

    def test_empty_label_dropped(self):
        content = '{"pairs":[{"label":"  ","value_row":1,"value_col":1}]}'
        self.assertEqual(parse_pairs(content, self.sheet), [])

    def test_label_out_of_range_set_none(self):
        content = '{"pairs":[{"label":"Y","label_row":99,"label_col":99,' \
                  '"value_row":1,"value_col":2}]}'
        fields = parse_pairs(content, self.sheet)
        self.assertEqual(len(fields), 1)
        self.assertIsNone(fields[0].label_row)
        self.assertIsNone(fields[0].label_col)

    def test_bad_json_raises(self):
        with self.assertRaises(AiScanError):
            parse_pairs("not json at all", self.sheet)

    def test_wrong_structure_raises(self):
        with self.assertRaises(AiScanError):
            parse_pairs('{"foo": 1}', self.sheet)


class TableFormPromptTest(unittest.TestCase):
    """表格型版式（表头行 + 数据行）的支持。"""

    def test_newline_cells_do_not_break_rows(self):
        # 单元格内的换行必须被压平，否则「一行一记录」会错位、行号对不上。
        grid = [["项目名称", "项目研究开发人员\n（人）"], ["甲", "5"]]
        sheet = SheetData(name="s", grid=grid, merged=[], max_row=2, max_col=2)
        lines = build_sheet_text(sheet).splitlines()
        self.assertEqual(len(lines), 2)  # 一行一记录
        self.assertIn("2=项目研究开发人员 （人）", lines[0])

    def test_prompt_describes_three_layouts(self):
        user = build_messages("x")[1]["content"]
        self.assertIn("横向表格", user)
        self.assertIn("纵向指标表", user)          # 指标名称/计量单位/代码/数量 版式
        self.assertIn("序号加在标签名末尾", user)  # 多数据行 → 编号规则
        self.assertIn("模板自身", user)            # 明确忽略表单管理信息

    def test_ideal_table_form_mapping(self):
        # 模拟 107-1 表：表头「项目名称」在 (6,3)，三个数据行在 12/13/14 行第 3 列。
        grid = [[None] * 3 for _ in range(14)]
        grid[5][2] = "项目名称"   # (6,3)
        grid[11][2] = "项目甲"     # (12,3)
        grid[12][2] = "项目乙"     # (13,3)
        grid[13][2] = "项目丙"     # (14,3)
        sheet = SheetData(name="s", grid=grid, merged=[], max_row=14, max_col=3)
        content = ('{"pairs":['
                   '{"label":"项目名称1","label_row":6,"label_col":3,'
                   '"value_row":12,"value_col":3},'
                   '{"label":"项目名称2","label_row":6,"label_col":3,'
                   '"value_row":13,"value_col":3},'
                   '{"label":"项目名称3","label_row":6,"label_col":3,'
                   '"value_row":14,"value_col":3}]}')
        fields = parse_pairs(content, sheet)
        self.assertEqual([f.target for f in fields],
                         ["项目名称1", "项目名称2", "项目名称3"])
        self.assertEqual([(f.value_row, f.value_col) for f in fields],
                         [(12, 3), (13, 3), (14, 3)])
        # 表格型：label 位置共用表头格
        self.assertTrue(all((f.label_row, f.label_col) == (6, 3) for f in fields))


class RecommendFieldsTest(unittest.TestCase):
    def test_injected_caller(self):
        content = ('{"pairs":[{"label":"姓名","label_row":1,"label_col":1,'
                   '"value_row":1,"value_col":2},'
                   '{"label":"年龄","value_row":2,"value_col":2}]}')
        captured = {}

        def fake_caller(messages, api_key, timeout=30.0):
            captured["api_key"] = api_key
            captured["messages"] = messages
            return content

        fields = recommend_fields(make_sheet(), "sk-test", caller=fake_caller)
        self.assertEqual([f.target for f in fields], ["姓名", "年龄"])
        self.assertEqual([(f.value_row, f.value_col) for f in fields],
                         [(1, 2), (2, 2)])
        self.assertEqual(captured["api_key"], "sk-test")
        # system + user 两条消息
        self.assertEqual([m["role"] for m in captured["messages"]],
                         ["system", "user"])

    def test_empty_key_raises(self):
        with self.assertRaises(AiScanError):
            recommend_fields(make_sheet(), "", caller=lambda *a, **k: "{}")


if __name__ == "__main__":
    unittest.main()

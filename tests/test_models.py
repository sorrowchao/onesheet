"""models 辅助函数单元测试。"""
import unittest

from app.core.models import (FieldMapping, OutputTable, SheetConfig,
                             duplicate_value_positions)


def make_table(fields):
    return OutputTable(name="汇总", sheet=SheetConfig(), fields=fields)


class TestDuplicateValuePositions(unittest.TestCase):
    def test_no_duplicates(self):
        tables = [make_table([
            FieldMapping(target="姓名", value_row=1, value_col=2),
            FieldMapping(target="性别", value_row=2, value_col=2),
        ])]
        self.assertEqual(duplicate_value_positions(tables), [])

    def test_same_position_reported(self):
        tables = [make_table([
            FieldMapping(target="金额", value_row=3, value_col=4),
            FieldMapping(target="金额2", value_row=3, value_col=4),
        ])]
        warnings = duplicate_value_positions(tables)
        self.assertEqual(len(warnings), 1)
        self.assertIn("金额", warnings[0])
        self.assertIn("金额2", warnings[0])
        self.assertIn("第 3 行第 4 列", warnings[0])

    def test_fields_without_position_ignored(self):
        """无固定取值位置的字段（走标签匹配）不参与重复判断。"""
        tables = [make_table([
            FieldMapping(target="甲", key="甲"),
            FieldMapping(target="乙", key="乙"),
        ])]
        self.assertEqual(duplicate_value_positions(tables), [])

    def test_reports_across_tables(self):
        tables = [
            make_table([FieldMapping(target="A", value_row=1, value_col=1),
                        FieldMapping(target="B", value_row=1, value_col=1)]),
            make_table([FieldMapping(target="C", value_row=2, value_col=2),
                        FieldMapping(target="D", value_row=2, value_col=2)]),
        ]
        warnings = duplicate_value_positions(tables)
        self.assertEqual(len(warnings), 2)
        self.assertIn("汇总", warnings[0])

    def test_unnamed_field_uses_key_or_placeholder(self):
        tables = [make_table([
            FieldMapping(target="", key="标签", value_row=1, value_col=1),
            FieldMapping(target="", key="", value_row=1, value_col=1),
        ])]
        warnings = duplicate_value_positions(tables)
        self.assertEqual(len(warnings), 1)
        self.assertIn("标签", warnings[0])
        self.assertIn("未命名", warnings[0])


if __name__ == "__main__":
    unittest.main()

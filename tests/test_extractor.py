"""extractor 单元测试（表单模式）。"""
import unittest

from app.core.extractor import extract_file
from app.core.models import (ExtractTemplate, FieldMapping, OutputTable,
                             SheetConfig, SheetData)


def sheet(grid, name="s"):
    return SheetData(name=name, grid=grid, merged=[], max_row=len(grid),
                     max_col=max((len(r) for r in grid), default=0))


FORM_SHEET = sheet([
    ["工资表", None, None, None],
    ["姓名：", "张三", "性别：", "男"],
    ["年龄：", 34, "部门：", "采购部"],
])


def make_template(fields=None):
    return ExtractTemplate(
        name="t",
        output_tables=[OutputTable(name="汇总", sheet=SheetConfig(sheet_keyword=""),
                                    fields=fields or [])],
    )


class TestFormScan(unittest.TestCase):
    def test_no_fields_full(self):
        # 无字段：输出全部自动识别的标签:值
        rt = extract_file([FORM_SHEET], make_template())["汇总"]
        self.assertEqual(rt.columns, ["姓名", "性别", "年龄", "部门"])
        self.assertEqual(rt.rows, [["张三", "男", 34, "采购部"]])

    def test_scan_selected_fields(self):
        # 扫描字段：按标签文本匹配取值
        tpl = make_template([FieldMapping(target="姓名", source="kv", key="姓名"),
                             FieldMapping(target="年龄", source="kv", key="年龄")])
        rt = extract_file([FORM_SHEET], tpl)["汇总"]
        self.assertEqual(rt.columns, ["姓名", "年龄"])
        self.assertEqual(rt.rows, [["张三", 34]])


class TestFormManualPair(unittest.TestCase):
    def test_pair_by_position(self):
        # 手动配对：按值位置直接读取（标签(2,1)，值(2,2)）
        f = FieldMapping(target="姓名", source="kv", key="姓名",
                         label_row=2, label_col=1, value_row=2, value_col=2)
        rt = extract_file([FORM_SHEET], make_template([f]))["汇总"]
        self.assertEqual(rt.columns, ["姓名"])
        self.assertEqual(rt.rows, [["张三"]])

    def test_pair_number_type(self):
        # 手动配对 + number 类型转换
        tpl = make_template([
            FieldMapping(target="年龄", source="kv", key="年龄",
                         value_row=3, value_col=2, value_type="number"),
        ])
        rt = extract_file([FORM_SHEET], tpl)["汇总"]
        self.assertEqual(rt.columns, ["年龄"])
        self.assertEqual(rt.rows, [[34]])


if __name__ == "__main__":
    unittest.main()

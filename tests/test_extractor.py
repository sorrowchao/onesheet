"""extractor 单元测试（表单模式）。"""
import unittest

from app.core.extractor import extract_file, object_name_from_path
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


TABLE_SHEET = sheet([
    ["项目表", None, None],          # 1
    [None, "项目名称", "项目来源"],   # 2 表头
    [None, "项目甲", "自选"],         # 3
    [None, "项目乙", "自选"],         # 4
    [None, "项目丙", "自选"],         # 5
    [None, "项目丁", "自选"],         # 6 超出模板的第 4 行
    [None, None, None],              # 7 空行 → 停止
    [None, "项目戊", "自选"],         # 8 不应被读到
])


class TestSameTypeRows(unittest.TestCase):
    def _fields(self):
        return [
            FieldMapping(target="项目名称1", key="项目名称", label_row=2, label_col=2,
                         value_row=3, value_col=2),
            FieldMapping(target="项目名称2", key="项目名称", label_row=2, label_col=2,
                         value_row=4, value_col=2),
            FieldMapping(target="项目名称3", key="项目名称", label_row=2, label_col=2,
                         value_row=5, value_col=2),
        ]

    def test_overflow_stacked_into_last_column(self):
        # 模板覆盖 3 行，第 4 行（项目丁）换行堆叠到最后一列并编号
        rt = extract_file([TABLE_SHEET], make_template(self._fields()))["汇总"]
        self.assertEqual(rt.rows, [[
            "项目甲", "项目乙", "项目丙\n4. 项目丁",
        ]])

    def test_overflow_stops_at_empty_cell(self):
        # 第 7 行为空 → 停止；第 8 行的「项目戊」不会混进来
        rt = extract_file([TABLE_SHEET], make_template(self._fields()))["汇总"]
        self.assertNotIn("项目戊", rt.rows[0][-1])

    def test_no_overflow_leaves_value_unchanged(self):
        grid = [row[:] for row in TABLE_SHEET.grid]
        grid[5] = [None, None, None]  # 第 6 行置空
        rt = extract_file([sheet(grid)], make_template(self._fields()))["汇总"]
        self.assertEqual(rt.rows[0][2], "项目丙")

    def test_single_field_group_not_expanded(self):
        # 只有 1 个映射的普通字段不向下扩展（防止把后续无关内容拼进来）
        f = FieldMapping(target="项目名称", key="项目名称", label_row=2, label_col=2,
                         value_row=3, value_col=2)
        rt = extract_file([TABLE_SHEET], make_template([f]))["汇总"]
        self.assertEqual(rt.rows, [["项目甲"]])

    def test_groups_are_independent(self):
        # 项目来源只映射了 1 行，不参与堆叠；项目名称组照常堆叠
        fields = self._fields() + [
            FieldMapping(target="项目来源1", key="项目来源", label_row=2, label_col=3,
                         value_row=3, value_col=3),
        ]
        rt = extract_file([TABLE_SHEET], make_template(fields))["汇总"]
        self.assertEqual(rt.columns, ["项目名称1", "项目名称2", "项目名称3", "项目来源1"])
        self.assertEqual(rt.rows[0][3], "自选")


class TestFilenameField(unittest.TestCase):
    """source="filename"：从文件名/文件夹名取汉字对象名。"""

    def test_object_name_keeps_only_chinese(self):
        self.assertEqual(
            object_name_from_path("C:/data/X企业2024.xlsx"), "企业")
        self.assertEqual(
            object_name_from_path("C:/data/ABC-采购部-2024v2.xlsx"), "采购部")

    def test_object_name_falls_back_to_folder(self):
        self.assertEqual(
            object_name_from_path("C:/data/采购部/2024.xlsx"), "采购部")

    def test_object_name_empty_when_no_chinese(self):
        self.assertEqual(object_name_from_path("C:/data/reports/2024-01.xlsx"), "")

    def test_extract_filename_field(self):
        f = FieldMapping(target="文件名", source="filename")
        rt = extract_file([FORM_SHEET], make_template([f]),
                          "C:/data/X企业2024.xlsx")["汇总"]
        self.assertEqual(rt.columns, ["文件名"])
        self.assertEqual(rt.rows, [["企业"]])

    def test_extract_filename_with_kv_field(self):
        fields = [FieldMapping(target="文件名", source="filename"),
                  FieldMapping(target="姓名", source="kv", key="姓名")]
        rt = extract_file([FORM_SHEET], make_template(fields),
                          "C:/data/采购部/2024.xlsx")["汇总"]
        self.assertEqual(rt.rows, [["采购部", "张三"]])

    def test_extract_without_path_yields_empty(self):
        f = FieldMapping(target="文件名", source="filename")
        rt = extract_file([FORM_SHEET], make_template([f]))["汇总"]
        self.assertEqual(rt.rows, [[""]])


if __name__ == "__main__":
    unittest.main()

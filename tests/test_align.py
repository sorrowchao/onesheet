"""align.py 偏移检测测试（纯逻辑，无需 QApplication）。"""
import unittest

from app.core.align import (Alignment, align_sheet, label_variants,
                            normalize_label)
from app.core.models import FieldMapping, SheetData


def _sheet(grid):
    width = max((len(row) for row in grid), default=0)
    return SheetData(name="s", grid=grid, merged=[],
                     max_row=len(grid), max_col=width)


def _field(key, label_row=None, label_col=None, value_row=None, value_col=None,
           source="kv"):
    return FieldMapping(target=key, source=source, key=key,
                        label_row=label_row, label_col=label_col,
                        value_row=value_row, value_col=value_col)


class NormalizeTest(unittest.TestCase):
    def test_colon_whitespace_and_width(self):
        self.assertEqual(normalize_label("项目研究开发人员\n（人）："),
                         "项目研究开发人员(人)")
        self.assertEqual(normalize_label("　项目１　"), "项目1")

    def test_variants(self):
        self.assertEqual(label_variants("项目名称1"), ("项目名称1", "项目名称"))
        self.assertEqual(label_variants("项目名称"), ("项目名称",))
        self.assertEqual(label_variants("甲"), ())
        self.assertEqual(label_variants(None), ())


class AlignSheetTest(unittest.TestCase):
    def test_aligned_returns_zero(self):
        grid = [["单位名称：", "X企业"], ["姓名：", "张三"]]
        fields = [_field("单位名称", 1, 1, 1, 2),
                  _field("姓名", 2, 1, 2, 2)]
        al = align_sheet(_sheet(grid), fields)
        self.assertEqual((al.row_delta, al.col_delta), (0, 0))
        self.assertEqual(al.votes, 2)
        self.assertFalse(al.shifted)

    def test_deleted_top_rows(self):
        # 模板里标签在第 3 行，实际文件删了顶部 2 行
        grid = [["单位名称：", "X企业"], ["姓名：", "张三"]]
        fields = [_field("单位名称", 3, 1, 3, 2),
                  _field("姓名", 4, 1, 4, 2)]
        al = align_sheet(_sheet(grid), fields)
        self.assertEqual((al.row_delta, al.col_delta), (-2, 0))
        self.assertEqual(al.votes, 2)
        self.assertTrue(al.reliable)
        self.assertEqual(al.offset, (-2, 0))

    def test_weak_nonzero_shift_keeps_origin(self):
        # 4 个锚点只有 2 个在别处命中（不过半）：不整表平移
        grid = [["单位名称：", "X企业"], ["姓名：", "张三"]]
        fields = [_field("单位名称", 3, 1, 3, 2),
                  _field("姓名", 4, 1, 4, 2),
                  _field("性别", 3, 3, 3, 4),
                  _field("年龄", 4, 3, 4, 4)]
        al = align_sheet(_sheet(grid), fields)
        self.assertEqual((al.row_delta, al.col_delta), (-2, 0))
        self.assertFalse(al.reliable)
        self.assertTrue(al.conflict)
        self.assertEqual(al.offset, (0, 0))

    def test_weak_zero_shift_is_fine(self):
        # 零偏移不要求过半：普通文件里个别标签被改名，仍按原位置读取
        grid = [["单位名称：", "X企业"], ["别的"]]
        fields = [_field("单位名称", 1, 1, 1, 2),
                  _field("姓名", 2, 1, 2, 2)]
        al = align_sheet(_sheet(grid), fields)
        self.assertEqual(al.offset, (0, 0))
        self.assertTrue(al.reliable)

    def test_column_shift(self):
        grid = [["", "单位名称：", "X企业"]]
        fields = [_field("单位名称", 1, 1, 1, 2)]
        al = align_sheet(_sheet(grid), fields)
        self.assertEqual((al.row_delta, al.col_delta), (0, 1))

    def test_suffixed_keys_share_one_anchor(self):
        # 三列横向表格字段共用同一个表头格，只能算一个锚点
        grid = [["单位名称：", "X企业"], ["", "", ""],
                ["", "", ""], ["", "", ""],
                ["序号", "项目名称", "数量"],
                ["1", "项目甲", 10]]
        fields = [_field("项目名称1", 5, 2, 6, 2),
                  _field("项目名称2", 5, 2, 7, 2),
                  _field("项目名称3", 5, 2, 8, 2),
                  _field("单位名称", 1, 1, 1, 2)]
        al = align_sheet(_sheet(grid), fields)
        self.assertEqual(al.anchor_count, 2)
        self.assertEqual((al.row_delta, al.col_delta), (0, 0))

    def test_numeric_suffix_matches_plain_header(self):
        grid = [["项目名称"], ["项目甲"]]
        fields = [_field("项目名称1", 3, 1, 4, 1)]
        al = align_sheet(_sheet(grid), fields)
        self.assertEqual((al.row_delta, al.col_delta), (-2, 0))

    def test_no_anchor_text_found(self):
        grid = [["完全无关"]]
        al = align_sheet(_sheet(grid), [_field("单位名称", 1, 1, 1, 2)])
        self.assertEqual((al.row_delta, al.col_delta), (0, 0))
        self.assertEqual(al.anchor_count, 1)
        self.assertFalse(al.reliable)

    def test_conflicting_anchors_prefer_no_shift(self):
        # 一个标签在模板位置、另一个整体下移 2 行：平票时取位移最小者
        grid = [["单位名称：", "X企业"],
                ["", ""], ["", ""],
                ["姓名：", "张三"]]
        fields = [_field("单位名称", 1, 1, 1, 2),
                  _field("姓名", 2, 1, 2, 2)]
        al = align_sheet(_sheet(grid), fields)
        self.assertEqual((al.row_delta, al.col_delta), (0, 0))
        self.assertTrue(al.conflict)
        self.assertFalse(al.reliable)

    def test_filename_field_ignored(self):
        grid = [["X企业"]]
        fields = [_field("X企业", 1, 1, 1, 1, source="filename")]
        al = align_sheet(_sheet(grid), fields)
        self.assertEqual(al.anchor_count, 0)
        self.assertEqual((al.row_delta, al.col_delta), (0, 0))

    def test_merged_region_shape(self):
        # 合并单元格：只有左上角有文本，其余为 None
        grid = [["单位名称：", None],
                [None, "X企业"]]
        fields = [_field("单位名称", 2, 1, 2, 2)]
        al = align_sheet(_sheet(grid), fields)
        self.assertEqual((al.row_delta, al.col_delta), (-1, 0))

    def test_min_votes(self):
        grid = [["单位名称：", "X企业"]]
        fields = [_field("单位名称", 2, 1, 2, 2)]
        al = align_sheet(_sheet(grid), fields, min_votes=2)
        self.assertEqual((al.row_delta, al.col_delta), (0, 0))
        self.assertTrue(al.conflict)

    def test_empty_sheet(self):
        self.assertEqual(align_sheet(None, []), Alignment())
        self.assertEqual(align_sheet(_sheet([]), [_field("单位名称", 1, 1, 1, 2)]),
                         Alignment())


if __name__ == "__main__":
    unittest.main()

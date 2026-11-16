"""分析准备引擎单元测试（纯逻辑）。"""
import unittest
from unittest import mock

from app.core.analysis import (AGG_LABELS, GROUP_SUFFIX, STATS_SUFFIX,
                               _unique_table_name, apply_analysis,
                               apply_cleanup, apply_derived_columns,
                               build_group_by, build_stats, clone_cleanup)
from app.core.models import (AggregateSpec, CleanupSpec, DerivedColumn,
                             ExtractTemplate, GroupBySpec, OutputTable,
                             ResultTable, RowFilter, StatsSpec)


def _table():
    return ResultTable(name="汇总", columns=["序号", "姓名", "部门", "工资", "绩效"],
                       rows=[
                           [1, " 张三 ", "A", "1000", "100"],
                           [2, "李四", "B", " 2000 ", ""],
                           [3, "张三", "A", "1500", "150"],
                           [4, "王五", "B", "abc", "50"],
                       ])


def _dedupe_table():
    return ResultTable(name="t", columns=["序号", "姓名", "工资"], rows=[
        [1, "张三", 100],
        [2, "张三", 100],
        [3, "李四", 200],
    ])


class CleanupTrimTest(unittest.TestCase):
    def test_trim(self):
        out = apply_cleanup(_table(), CleanupSpec(trim=True))
        self.assertEqual(out.rows[0][1], "张三")
        self.assertEqual(out.rows[1][3], "2000")
        self.assertEqual(out.rows[1][1], "李四")


class CleanupFilterTest(unittest.TestCase):
    def _filter(self, column, op, value=""):
        return apply_cleanup(_table(), CleanupSpec(
            filters=[RowFilter(column=column, op=op, value=value)]))

    def test_not_empty(self):
        out = self._filter("绩效", "not_empty")
        self.assertEqual([r[1] for r in out.rows], [" 张三 ", "张三", "王五"])

    def test_empty(self):
        out = self._filter("绩效", "empty")
        self.assertEqual([r[1] for r in out.rows], ["李四"])
        self.assertEqual(out.rows[0][0], 1)   # 序号重排

    def test_eq(self):
        out = self._filter("部门", "eq", "A")
        self.assertEqual([r[1] for r in out.rows], [" 张三 ", "张三"])

    def test_ne(self):
        out = self._filter("部门", "ne", "A")
        self.assertEqual([r[1] for r in out.rows], ["李四", "王五"])

    def test_gt_skips_non_numeric(self):
        out = self._filter("工资", "gt", "1200")
        self.assertEqual([r[1] for r in out.rows], ["李四", "张三"])

    def test_ge(self):
        out = self._filter("工资", "ge", "1500")
        self.assertEqual([r[1] for r in out.rows], ["李四", "张三"])

    def test_lt(self):
        out = self._filter("工资", "lt", "1500")
        self.assertEqual([r[1] for r in out.rows], [" 张三 "])

    def test_le(self):
        out = self._filter("工资", "le", "1500")
        self.assertEqual([r[1] for r in out.rows], [" 张三 ", "张三"])

    def test_contains(self):
        out = self._filter("姓名", "contains", "张")
        self.assertEqual([r[1] for r in out.rows], [" 张三 ", "张三"])

    def test_not_contains(self):
        out = self._filter("姓名", "not_contains", "张")
        self.assertEqual([r[1] for r in out.rows], ["李四", "王五"])

    def test_unknown_column_ignored(self):
        out = self._filter("不存在", "eq", "A")
        self.assertEqual(len(out.rows), 4)


class CleanupDedupeTest(unittest.TestCase):
    def test_dedupe_all_columns_ignoring_seq(self):
        out = apply_cleanup(_dedupe_table(), CleanupSpec(dedupe=True))
        self.assertEqual([r[1] for r in out.rows], ["张三", "李四"])
        self.assertEqual([r[0] for r in out.rows], [1, 2])   # 序号重排

    def test_dedupe_specified_column(self):
        out = apply_cleanup(_table(), CleanupSpec(
            dedupe=True, dedupe_columns=["姓名"]))
        self.assertEqual([r[1] for r in out.rows],
                         [" 张三 ", "李四", "王五"])

    def test_dedupe_keeps_first(self):
        t = ResultTable(name="t", columns=["序号", "A", "B"],
                        rows=[[1, "x", "old"], [2, "x", "new"]])
        out = apply_cleanup(t, CleanupSpec(dedupe=True, dedupe_columns=["A"]))
        self.assertEqual(out.rows, [[1, "x", "old"]])


class DerivedColumnTest(unittest.TestCase):
    def test_append_new_column(self):
        out, notes = apply_derived_columns(
            _table(), [DerivedColumn(target="合计", formula="[工资] + [绩效]")])
        self.assertIn("合计", out.columns)
        self.assertEqual(out.rows[0][-1], 1100)
        self.assertEqual(notes, [])

    def test_in_place_recompute(self):
        t = ResultTable(name="t", columns=["a", "合计"],
                        rows=[[2, 999], [3, 999]])
        out, _ = apply_derived_columns(
            t, [DerivedColumn(target="合计", formula="[a] * 2")])
        self.assertEqual(out.columns, ["a", "合计"])
        self.assertEqual([r[1] for r in out.rows], [4, 6])

    def test_chained_formulas(self):
        out, _ = apply_derived_columns(
            _table(),
            [DerivedColumn(target="合计", formula="[工资] + [绩效]"),
             DerivedColumn(target="双倍", formula="[合计] * 2")])
        self.assertEqual(out.rows[0][-1], 2200)

    def test_invalid_formula_warns_and_skips(self):
        out, notes = apply_derived_columns(
            _table(), [DerivedColumn(target="坏", formula="[不存在的列] + 1")])
        self.assertNotIn("坏", out.columns)
        self.assertEqual(len(notes), 1)
        self.assertIn("坏", notes[0])

    def test_empty_target_warns(self):
        out, notes = apply_derived_columns(
            _table(), [DerivedColumn(target="", formula="[工资]")])
        self.assertEqual(len(notes), 1)
        self.assertNotIn("", out.columns)

    def test_non_numeric_row_leaves_empty(self):
        out, _ = apply_derived_columns(
            _table(), [DerivedColumn(target="合计", formula="[工资] + [绩效]")])
        self.assertIsNone(out.rows[3][-1])   # 工资为 abc


class GroupByTest(unittest.TestCase):
    def _spec(self, aggs, groups=("部门",)):
        return GroupBySpec(enabled=True, group_columns=list(groups),
                           aggregations=aggs)

    def test_not_enabled_returns_none(self):
        self.assertIsNone(build_group_by(_table(), GroupBySpec()))

    def test_no_group_columns_returns_none(self):
        self.assertIsNone(build_group_by(_table(), GroupBySpec(enabled=True)))

    def test_aggregates(self):
        spec = self._spec([
            AggregateSpec(column="工资", func="sum"),
            AggregateSpec(column="姓名", func="count"),
            AggregateSpec(column="绩效", func="avg"),
        ])
        out = build_group_by(_table(), spec)
        self.assertEqual(out.name, "汇总" + GROUP_SUFFIX)
        self.assertEqual(out.columns, ["部门", "合计(工资)", "计数(姓名)",
                                       "平均(绩效)"])
        # A 组：工资 1000+1500=2500，2 人，绩效均值 125
        self.assertEqual(out.rows[0], ["A", 2500, 2, 125])
        # B 组：工资 2000（abc 忽略）=2000，2 人，绩效 50
        self.assertAlmostEqual(out.rows[1][1], 2000)
        self.assertEqual(out.rows[1][2], 2)
        # 顺序按首次出现：A 在前
        self.assertEqual([r[0] for r in out.rows], ["A", "B"])

    def test_min_max(self):
        spec = self._spec([
            AggregateSpec(column="工资", func="min"),
            AggregateSpec(column="工资", func="max"),
        ])
        out = build_group_by(_table(), spec)
        self.assertEqual(out.rows[0], ["A", 1000, 1500])

    def test_custom_target_and_dedupe_name(self):
        spec = self._spec([
            AggregateSpec(column="工资", func="sum", target="工资合计"),
            AggregateSpec(column="绩效", func="sum", target="工资合计"),
        ])
        out = build_group_by(_table(), spec)
        self.assertEqual(out.columns[1:], ["工资合计", "工资合计2"])

    def test_multiple_group_columns(self):
        spec = self._spec(
            [AggregateSpec(column="工资", func="count")], groups=("部门", "姓名"))
        out = build_group_by(_table(), spec)
        self.assertEqual(out.columns[0:2], ["部门", "姓名"])
        # (A, 张三) 两行合为一组、(B, 李四)、(B, 王五) → 3 组
        self.assertEqual(len(out.rows), 3)

    def test_count_non_empty(self):
        spec = self._spec([AggregateSpec(column="绩效", func="count")])
        out = build_group_by(_table(), spec)
        # A: 2 个非空；B: 李四空、王五 50 → 1
        self.assertEqual([r[1] for r in out.rows], [2, 1])


class StatsTest(unittest.TestCase):
    def test_not_enabled(self):
        self.assertIsNone(build_stats(_table(), StatsSpec()))

    def test_default_all_numeric_columns(self):
        out = build_stats(_table(), StatsSpec(enabled=True))
        self.assertEqual(out.name, "汇总" + STATS_SUFFIX)
        self.assertEqual(out.columns,
                         ["列名", "计数", "合计", "平均", "中位数",
                          "最小值", "最大值", "标准差"])
        names = [r[0] for r in out.rows]
        self.assertIn("工资", names)
        self.assertIn("绩效", names)
        self.assertNotIn("序号", names)
        self.assertNotIn("姓名", names)   # 非数值

    def test_values(self):
        out = build_stats(_table(), StatsSpec(enabled=True))
        row = next(r for r in out.rows if r[0] == "绩效")
        # 数值：100, 150, 50（李四为空被跳过）
        self.assertEqual(row[1], 3)          # 计数
        self.assertEqual(row[2], 300)        # 合计
        self.assertEqual(row[3], 100)        # 平均
        self.assertEqual(row[4], 100)        # 中位数
        self.assertEqual(row[5], 50)         # 最小值
        self.assertEqual(row[6], 150)        # 最大值

    def test_std_single_value_is_zero(self):
        t = ResultTable(name="t", columns=["x"], rows=[[5]])
        out = build_stats(t, StatsSpec(enabled=True))
        self.assertEqual(out.rows[0][-1], 0)

    def test_limited_columns_and_metrics(self):
        out = build_stats(_table(), StatsSpec(
            enabled=True, columns=["工资"], metrics=["avg"]))
        self.assertEqual(out.columns, ["列名", "平均"])
        self.assertEqual([r[0] for r in out.rows], ["工资"])
        self.assertEqual(out.rows[0][1], 1500)


class ApplyAnalysisTest(unittest.TestCase):
    def _tpl(self, **kwargs):
        return ExtractTemplate(output_tables=[OutputTable(name="汇总", **kwargs)])

    def test_no_config_returns_unchanged(self):
        tables = {"汇总": _table()}
        out, notes = apply_analysis(tables, self._tpl())
        self.assertEqual(notes, [])
        self.assertEqual(list(out), ["汇总"])
        self.assertEqual(out["汇总"], tables["汇总"])

    def test_cleanup_and_derived(self):
        tpl = self._tpl(
            cleanup=CleanupSpec(dedupe=True, dedupe_columns=["姓名"]),
            derived_columns=[DerivedColumn(target="合计",
                                           formula="[工资] + [绩效]")])
        out, _ = apply_analysis({"汇总": _table()}, tpl)
        t = out["汇总"]
        self.assertIn("合计", t.columns)
        self.assertEqual(len(t.rows), 3)   # 张三去重

    def test_generated_tables_appended(self):
        tpl = self._tpl(
            group_by=GroupBySpec(enabled=True, group_columns=["部门"],
                                 aggregations=[AggregateSpec(column="绩效")]),
            stats=StatsSpec(enabled=True))
        out, notes = apply_analysis({"汇总": _table()}, tpl)
        self.assertEqual(list(out),
                         ["汇总", "汇总" + GROUP_SUFFIX, "汇总" + STATS_SUFFIX])
        self.assertEqual(len(notes), 2)

    def test_repeat_does_not_stack(self):
        tpl = self._tpl(
            group_by=GroupBySpec(enabled=True, group_columns=["部门"],
                                 aggregations=[AggregateSpec(column="绩效")]))
        first, _ = apply_analysis({"汇总": _table()}, tpl)
        second, _ = apply_analysis(first, tpl)
        self.assertEqual(list(first), list(second))
        self.assertEqual(len(second), 2)

    def test_exception_becomes_note(self):
        tpl = self._tpl(
            group_by=GroupBySpec(enabled=True, group_columns=["部门"],
                                 aggregations=[AggregateSpec(column="绩效")]))
        with mock.patch("app.core.analysis.build_group_by",
                        side_effect=RuntimeError("boom")):
            out, notes = apply_analysis({"汇总": _table()}, tpl)
        self.assertEqual(list(out), ["汇总"])
        self.assertTrue(any("失败" in n for n in notes))

    def test_generated_name_suffix(self):
        t = ResultTable(name="X" + GROUP_SUFFIX)
        _unique_table_name(t, {"X" + GROUP_SUFFIX})
        self.assertEqual(t.name, "X" + GROUP_SUFFIX + "2")


class CloneCleanupTest(unittest.TestCase):
    def test_deep_copy(self):
        src = CleanupSpec(trim=True, dedupe_columns=["A"],
                          filters=[RowFilter(column="A", op="eq", value="1")])
        dst = clone_cleanup(src)
        dst.dedupe_columns.append("B")
        dst.filters[0].value = "2"
        self.assertEqual(src.dedupe_columns, ["A"])
        self.assertEqual(src.filters[0].value, "1")


if __name__ == "__main__":
    unittest.main()

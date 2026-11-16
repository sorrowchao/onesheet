"""core/validator 单元测试（纯逻辑，无 Qt）。"""
import unittest

from app.core.models import (ExtractTemplate, OutputTable, ResultTable,
                             ValidationRule)
from app.core.validator import describe_rule, validate_results, validate_table


def table(columns, rows, name="汇总"):
    return ResultTable(name=name, columns=columns, rows=rows)


class RequiredTest(unittest.TestCase):
    def test_empty_and_whitespace_flagged(self):
        t = table(["序号", "姓名"], [[1, "张三"], [2, None], [3, "  "]])
        issues = validate_table(t, [ValidationRule(type="required", columns=["姓名"])])
        self.assertEqual([i.row for i in issues], [1, 2])
        self.assertEqual(issues[0].column, "姓名")
        self.assertEqual(issues[0].message, "必填项为空")

    def test_all_present_passes(self):
        t = table(["姓名"], [["张三"], ["李四"]])
        self.assertEqual(
            validate_table(t, [ValidationRule(type="required", columns=["姓名"])]), [])


class NumberTest(unittest.TestCase):
    def test_invalid_and_out_of_range(self):
        t = table(["金额"], [["1,234"], ["abc"], [""], [50]])
        rule = ValidationRule(type="number", columns=["金额"], min=100, max=200)
        issues = validate_table(t, [rule])
        self.assertEqual([i.row for i in issues], [0, 1, 3])
        self.assertIn("大于最大值", issues[0].message)
        self.assertIn("不是有效数字", issues[1].message)
        self.assertIn("小于最小值", issues[2].message)

    def test_bounds_inclusive(self):
        t = table(["金额"], [[100], [200], [99.9]])
        rule = ValidationRule(type="number", columns=["金额"], min=100, max=200)
        issues = validate_table(t, [rule])
        self.assertEqual([i.row for i in issues], [2])

    def test_empty_is_skipped(self):
        t = table(["金额"], [[None], ["   "]])
        self.assertEqual(
            validate_table(t, [ValidationRule(type="number", columns=["金额"])]), [])


class UniqueTest(unittest.TestCase):
    def test_duplicates_mark_all_rows(self):
        t = table(["工号"], [["001"], ["002"], ["001"]])
        issues = validate_table(t, [ValidationRule(type="unique", columns=["工号"])])
        self.assertEqual(sorted(i.row for i in issues), [0, 2])
        self.assertIn("第 3 行", issues[0].message)
        self.assertIn("第 1 行", issues[1].message)

    def test_leading_zero_and_comma_normalization(self):
        t = table(["工号"], [["007"], ["7"], ["1,234"], [1234]])
        issues = validate_table(t, [ValidationRule(type="unique", columns=["工号"])])
        # "007" 与 "7" 不同；"1,234" 与 1234 视为相同 → 只剩后两行重复
        self.assertEqual(sorted(i.row for i in issues), [2, 3])

    def test_empty_keys_ignored(self):
        t = table(["工号"], [[None], [""], ["  "]])
        self.assertEqual(
            validate_table(t, [ValidationRule(type="unique", columns=["工号"])]), [])

    def test_composite_key(self):
        t = table(["姓名", "日期"],
                  [["张三", "2024"], ["张三", "2025"], ["张三", "2024"]])
        issues = validate_table(
            t, [ValidationRule(type="unique", columns=["姓名", "日期"])])
        self.assertEqual(sorted(i.row for i in issues), [0, 2])


class SumTest(unittest.TestCase):
    def test_match_and_mismatch(self):
        t = table(["基本工资", "绩效", "应发总计"],
                  [[1000, 200, 1200],
                   [1000, 300, 1400],
                   [1000, None, 1000],
                   [1000, 200, None]])
        issues = validate_table(t, [ValidationRule(
            type="sum", target="应发总计", columns=["基本工资", "绩效"])])
        self.assertEqual([i.row for i in issues], [1, 3])
        self.assertIn("差 100", issues[0].message)
        self.assertEqual(issues[1].message, "合计为空")

    def test_tolerance(self):
        t = table(["a", "b", "total"], [[1, 2, 3.4]])
        rule = ValidationRule(type="sum", target="total", columns=["a", "b"],
                              tolerance=0.5)
        self.assertEqual(validate_table(t, [rule]), [])
        rule.tolerance = 0.1
        self.assertEqual(len(validate_table(t, [rule])), 1)

    def test_non_numeric_addend(self):
        t = table(["a", "b", "total"], [[1, "x", 3]])
        issues = validate_table(t, [ValidationRule(
            type="sum", target="total", columns=["a", "b"])])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].column, "b")
        self.assertIn("分项不是有效数字", issues[0].message)


class RuleReferenceTest(unittest.TestCase):
    def test_missing_column_is_table_level(self):
        t = table(["姓名"], [["张三"]])
        issues = validate_table(
            t, [ValidationRule(type="required", columns=["不存在"])])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].row, -1)
        self.assertIn("列不存在", issues[0].message)

    def test_unknown_type(self):
        t = table(["姓名"], [["张三"]])
        issues = validate_table(t, [ValidationRule(type="bad", columns=["姓名"])])
        self.assertEqual(issues[0].row, -1)
        self.assertIn("未知的校验类型", issues[0].message)


class ValidateResultsTest(unittest.TestCase):
    def test_only_tables_with_rules(self):
        tpl = ExtractTemplate(output_tables=[
            OutputTable(name="有规则", validations=[
                ValidationRule(type="required", columns=["姓名"])]),
            OutputTable(name="无规则"),
            OutputTable(name="没有结果", validations=[
                ValidationRule(type="required", columns=["姓名"])]),
        ])
        results = {
            "有规则": table(["姓名"], [[None]], name="有规则"),
            "无规则": table(["姓名"], [[None]], name="无规则"),
        }
        issues = validate_results(results, tpl)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].table, "有规则")


class DescribeRuleTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(
            describe_rule(ValidationRule(type="required", columns=["姓名"])),
            "必填：姓名")
        self.assertIn("100 ~ 200", describe_rule(
            ValidationRule(type="number", columns=["金额"], min=100, max=200)))
        self.assertEqual(
            describe_rule(ValidationRule(type="unique", columns=["工号"])),
            "唯一：工号")
        self.assertIn("总计 = a + b", describe_rule(ValidationRule(
            type="sum", target="总计", columns=["a", "b"])))


if __name__ == "__main__":
    unittest.main()

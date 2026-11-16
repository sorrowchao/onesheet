"""template schema / store 单元测试。"""
import tempfile
import unittest
from pathlib import Path

from app.core.models import (AggregateSpec, CleanupSpec, DerivedColumn,
                             ExtractTemplate, FieldMapping, GroupBySpec,
                             OutputTable, RowFilter, SheetConfig, StatsSpec,
                             ValidationRule, dedupe_targets)
from app.template.schema import from_dict, to_dict, validate
from app.template.store import delete, duplicate, load, rename, save, save_path


def make_template():
    return ExtractTemplate(
        name="研发报表汇总",
        output_tables=[
            OutputTable(
                name="项目汇总",
                sheet=SheetConfig(sheet_keyword="项目表"),
                fields=[FieldMapping(target="企业名称", source="kv", key="单位名称"),
                        FieldMapping(target="项目经费", source="kv", key="项目经费",
                                     value_row=4, value_col=13, value_type="number")],
            ),
        ],
    )


class TestSchema(unittest.TestCase):
    def test_round_trip(self):
        tpl = make_template()
        tpl2 = from_dict(to_dict(tpl))
        self.assertEqual(tpl, tpl2)

    def test_validate_ok(self):
        self.assertEqual(validate(to_dict(make_template())), [])

    def test_filename_source_valid(self):
        data = to_dict(make_template())
        data["output_tables"][0]["fields"].append(
            {"target": "文件名", "source": "filename"})
        self.assertEqual(validate(data), [])
        tpl = from_dict(data)
        self.assertEqual(tpl.output_tables[0].fields[-1].source, "filename")

    def test_validate_errors(self):
        self.assertTrue(validate({"name": ""}))
        self.assertTrue(validate({"name": "x", "output_tables": []}))
        self.assertTrue(validate({
            "name": "x",
            "output_tables": [{"name": "t", "fields": [{"source": "bad"}]}],
        }))

    # --- 校验规则 -------------------------------------------------------
    def test_validations_round_trip(self):
        tpl = make_template()
        tpl.output_tables[0].validations = [
            ValidationRule(type="sum", target="项目经费",
                           columns=["企业名称"], tolerance=0.5),
        ]
        data = to_dict(tpl)
        self.assertIn("validations", data["output_tables"][0])
        self.assertEqual(from_dict(data), tpl)
        self.assertEqual(validate(data), [])

    def test_legacy_json_without_validations(self):
        data = to_dict(make_template())
        data["output_tables"][0].pop("validations", None)
        tpl = from_dict(data)
        self.assertEqual(tpl.output_tables[0].validations, [])
        self.assertEqual(validate(data), [])

    def test_invalid_validation_rejected(self):
        data = to_dict(make_template())
        data["output_tables"][0]["validations"] = [
            {"type": "bad", "columns": ["x"]}]
        self.assertTrue(validate(data))

    def test_sum_validation_requires_target_and_columns(self):
        data = to_dict(make_template())
        data["output_tables"][0]["validations"] = [
            {"type": "sum", "columns": []}]
        self.assertTrue(validate(data))
        data["output_tables"][0]["validations"] = [
            {"type": "sum", "target": "项目经费", "columns": ["企业名称"]}]
        self.assertEqual(validate(data), [])

    def test_number_validation_min_max(self):
        data = to_dict(make_template())
        data["output_tables"][0]["validations"] = [
            {"type": "number", "columns": ["项目经费"], "min": 5, "max": 1}]
        self.assertTrue(validate(data))


class TestAnalysisSchema(unittest.TestCase):
    """分析准备配置的 JSON 互转与校验。"""

    def _template(self):
        tpl = make_template()
        ot = tpl.output_tables[0]
        ot.derived_columns = [DerivedColumn(target="经费双倍",
                                            formula="[项目经费] * 2")]
        ot.cleanup = CleanupSpec(
            trim=True, dedupe=True, dedupe_columns=["企业名称"],
            filters=[RowFilter(column="项目经费", op="gt", value="0")])
        ot.group_by = GroupBySpec(
            enabled=True, group_columns=["企业名称"],
            aggregations=[AggregateSpec(column="项目经费", func="sum")])
        ot.stats = StatsSpec(enabled=True, columns=["项目经费"],
                             metrics=["avg", "median"])
        return tpl

    def test_round_trip(self):
        tpl = self._template()
        self.assertEqual(from_dict(to_dict(tpl)), tpl)

    def test_to_dict_has_keys(self):
        data = to_dict(self._template())
        ot = data["output_tables"][0]
        for key in ("derived_columns", "cleanup", "group_by", "stats"):
            self.assertIn(key, ot)

    def test_validate_ok(self):
        self.assertEqual(validate(to_dict(self._template())), [])

    def test_legacy_json_defaults(self):
        data = to_dict(make_template())
        for key in ("derived_columns", "cleanup", "group_by", "stats"):
            data["output_tables"][0].pop(key, None)
        ot = from_dict(data).output_tables[0]
        self.assertEqual(ot.derived_columns, [])
        self.assertFalse(ot.cleanup.trim)
        self.assertFalse(ot.group_by.enabled)
        self.assertFalse(ot.stats.enabled)
        self.assertEqual(validate(data), [])

    def test_derived_requires_target(self):
        data = to_dict(self._template())
        data["output_tables"][0]["derived_columns"] = [
            {"target": "", "formula": "[项目经费] + 1"}]
        self.assertTrue(validate(data))

    def test_derived_invalid_formula(self):
        data = to_dict(self._template())
        data["output_tables"][0]["derived_columns"] = [
            {"target": "x", "formula": "__import__('os')"}]
        self.assertTrue(validate(data))

    def test_derived_unknown_column(self):
        data = to_dict(self._template())
        data["output_tables"][0]["derived_columns"] = [
            {"target": "x", "formula": "[不存在] + 1"}]
        self.assertTrue(validate(data))

    def test_derived_can_reference_earlier_derived(self):
        data = to_dict(self._template())
        data["output_tables"][0]["derived_columns"] = [
            {"target": "x", "formula": "[项目经费] + 1"},
            {"target": "y", "formula": "[x] * 2"}]
        self.assertEqual(validate(data), [])

    def test_stats_unknown_metric(self):
        data = to_dict(self._template())
        data["output_tables"][0]["stats"] = {
            "enabled": True, "metrics": ["bogus"]}
        self.assertTrue(validate(data))

    def test_cleanup_bad_op(self):
        data = to_dict(self._template())
        data["output_tables"][0]["cleanup"] = {
            "filters": [{"column": "x", "op": "bad"}]}
        self.assertTrue(validate(data))

    def test_group_by_bad_func(self):
        data = to_dict(self._template())
        data["output_tables"][0]["group_by"] = {
            "enabled": True,
            "aggregations": [{"column": "x", "func": "bad"}]}
        self.assertTrue(validate(data))


class TestDedupeTargets(unittest.TestCase):
    def test_duplicate_gets_numbered(self):
        fields = [FieldMapping(target="金额"), FieldMapping(target="金额"),
                  FieldMapping(target="金额")]
        dedupe_targets(fields)
        self.assertEqual([f.target for f in fields], ["金额", "金额2", "金额3"])

    def test_keeps_key_unchanged(self):
        fields = [FieldMapping(target="金额", key="金额"), FieldMapping(target="金额", key="金额")]
        dedupe_targets(fields)
        self.assertEqual([f.target for f in fields], ["金额", "金额2"])
        self.assertEqual([f.key for f in fields], ["金额", "金额"])

    def test_unique_and_empty_untouched(self):
        fields = [FieldMapping(target="姓名"), FieldMapping(target=""),
                  FieldMapping(target="年龄")]
        dedupe_targets(fields)
        self.assertEqual([f.target for f in fields], ["姓名", "", "年龄"])

    def test_skips_already_used_name(self):
        # 后续重名自动跳过已被占用的名字
        fields = [FieldMapping(target="金额"), FieldMapping(target="金额2"),
                  FieldMapping(target="金额")]
        dedupe_targets(fields)
        self.assertEqual([f.target for f in fields], ["金额", "金额2", "金额3"])

    def test_bare_name_continues_existing_family(self):
        # 已有 XX1/XX2 时，新加的裸名 XX 继续编号为 XX3
        fields = [FieldMapping(target="项目名称1"),
                  FieldMapping(target="项目名称2"),
                  FieldMapping(target="项目名称")]
        dedupe_targets(fields)
        self.assertEqual([f.target for f in fields],
                         ["项目名称1", "项目名称2", "项目名称3"])

    def test_duplicate_numbered_continues_family(self):
        # 再次出现 XX1 时不能拼成 XX12，应接着家族编号为 XX3
        fields = [FieldMapping(target="项目名称1"),
                  FieldMapping(target="项目名称2"),
                  FieldMapping(target="项目名称1")]
        dedupe_targets(fields)
        self.assertEqual([f.target for f in fields],
                         ["项目名称1", "项目名称2", "项目名称3"])

    def test_explicit_number_kept_when_free(self):
        # 用户显式写的编号名即使跳号也保留，不替用户重排
        fields = [FieldMapping(target="项目名称1"),
                  FieldMapping(target="项目名称3")]
        dedupe_targets(fields)
        self.assertEqual([f.target for f in fields],
                         ["项目名称1", "项目名称3"])

    def test_any_stem_family(self):
        # 规则与具体名称无关：任意「名称+数字」都按同一家族编号
        fields = [FieldMapping(target="股东1"), FieldMapping(target="股东2"),
                  FieldMapping(target="股东")]
        dedupe_targets(fields)
        self.assertEqual([f.target for f in fields],
                         ["股东1", "股东2", "股东3"])

    def test_zero_padding_preserved(self):
        fields = [FieldMapping(target="股东01"), FieldMapping(target="股东02"),
                  FieldMapping(target="股东")]
        dedupe_targets(fields)
        self.assertEqual([f.target for f in fields],
                         ["股东01", "股东02", "股东03"])

    def test_fullwidth_number_preserved(self):
        fields = [FieldMapping(target="费用１"), FieldMapping(target="费用２"),
                  FieldMapping(target="费用")]
        dedupe_targets(fields)
        self.assertEqual([f.target for f in fields],
                         ["费用１", "费用２", "费用３"])


class TestStore(unittest.TestCase):
    def test_save_load(self):
        tpl = make_template()
        with tempfile.TemporaryDirectory() as tmp:
            path = save(tpl, Path(tmp))
            self.assertTrue(Path(path).exists())
            tpl2 = load(path)
            self.assertEqual(tpl, tpl2)

    def test_save_path_uses_given_path(self):
        """显式路径必须被采用（不能回退到模板目录），父目录自动创建。"""
        tpl = make_template()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sub" / "自定义名.json"
            saved = save_path(tpl, target)
            self.assertEqual(Path(saved), target)
            self.assertTrue(target.exists())
            self.assertEqual(load(saved), tpl)

    def test_load_invalid_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text('{"name": ""}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load(str(p))


class TestManageTemplates(unittest.TestCase):
    """模板管理器的 store 层操作：复制 / 重命名 / 删除。"""

    @staticmethod
    def _write(tmp, name):
        tpl = make_template()
        tpl.name = name
        return save_path(tpl, Path(tmp) / f"{name}.json")

    def test_duplicate_keeps_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._write(tmp, "A")
            dst = duplicate(src, "B")
            self.assertEqual(Path(dst).name, "B.json")
            self.assertTrue(Path(src).exists())
            self.assertEqual(load(dst).name, "B")

    def test_duplicate_existing_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._write(tmp, "A")
            self._write(tmp, "B")
            with self.assertRaises(FileExistsError):
                duplicate(src, "B")

    def test_rename_moves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._write(tmp, "A")
            dst = rename(src, "B")
            self.assertFalse(Path(src).exists())
            self.assertTrue(Path(dst).exists())
            self.assertEqual(load(dst).name, "B")

    def test_rename_to_existing_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._write(tmp, "A")
            other = self._write(tmp, "C")
            with self.assertRaises(FileExistsError):
                rename(src, "C")
            self.assertTrue(Path(src).exists())
            self.assertTrue(Path(other).exists())

    def test_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "A")
            delete(path)
            self.assertFalse(Path(path).exists())
            delete(path)  # 再次删除不抛异常


if __name__ == "__main__":
    unittest.main()

"""template schema / store 单元测试。"""
import tempfile
import unittest
from pathlib import Path

from app.core.models import (ExtractTemplate, FieldMapping, OutputTable,
                             SheetConfig, dedupe_targets)
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

"""paths.py 数据目录解析测试。"""
import sys
import tempfile
import unittest
from pathlib import Path

from app import paths


class FrozenBaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_templates(self, rel: str, names=("a.json",)):
        d = self.root / rel
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / n).write_text("{}", encoding="utf-8")

    def _exe(self, rel_dir: str) -> Path:
        d = self.root / rel_dir
        d.mkdir(parents=True, exist_ok=True)
        return d / "onesheet.exe"

    def test_prefers_exe_dir_when_it_has_templates(self):
        self._make_templates("app/data/templates")
        self.assertEqual(paths.frozen_base(self._exe("app")),
                         (self.root / "app").resolve())

    def test_falls_back_to_parent_for_dist_layout(self):
        # dist/data/templates 存在但为空；项目根 data/templates 有模板
        self._make_templates("dist/data/templates", names=())
        self._make_templates("data/templates")
        self.assertEqual(paths.frozen_base(self._exe("dist")),
                         self.root.resolve())

    def test_no_templates_anywhere_uses_exe_dir(self):
        self.assertEqual(paths.frozen_base(self._exe("standalone")),
                         (self.root / "standalone").resolve())

    def test_source_mode_uses_project_data(self):
        self.assertFalse(getattr(sys, "frozen", False))
        self.assertEqual(paths.data_dir(),
                         Path(__file__).resolve().parent.parent / "data")


if __name__ == "__main__":
    unittest.main()

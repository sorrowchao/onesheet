"""模板管理器对话框测试（离屏：列表、时间列、排序、按钮状态）。"""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication

from app.ui import template_manager
from app.ui.template_manager import TemplateManagerDialog, format_mtime

# 必须在构造任何 QWidget 之前创建 QApplication。
_app = QApplication.instance() or QApplication(sys.argv)


class TemplateManagerListTest(unittest.TestCase):
    def _make(self, entries):
        with mock.patch.object(template_manager.store, "list_templates",
                               return_value=entries):
            return TemplateManagerDialog()

    def test_lists_templates(self):
        dlg = self._make([{"path": "C:/t/a.json", "name": "A"},
                          {"path": "C:/t/b.json", "name": "B"}])
        try:
            self.assertEqual(dlg.table.rowCount(), 2)
            self.assertEqual(dlg.table.item(0, 0).text(), "A")
            self.assertEqual(dlg.table.item(1, 2).text(), "b.json")
        finally:
            dlg.deleteLater()

    def test_empty_shows_hint_and_disables_buttons(self):
        dlg = self._make([])
        try:
            self.assertEqual(dlg.table.rowCount(), 0)
            self.assertFalse(dlg.empty_label.isHidden())
            self.assertFalse(dlg.btn_open.isEnabled())
            self.assertFalse(dlg.btn_rename.isEnabled())
        finally:
            dlg.deleteLater()

    def test_buttons_follow_selection(self):
        dlg = self._make([{"path": "C:/t/a.json", "name": "A"}])
        try:
            # 默认选中第一行，打开/重命名等直接可用
            self.assertTrue(dlg.btn_open.isEnabled())
            self.assertTrue(dlg.btn_rename.isEnabled())
            dlg.table.clearSelection()
            self.assertFalse(dlg.btn_open.isEnabled())
            dlg.table.selectRow(0)
            self.assertTrue(dlg.btn_open.isEnabled())
        finally:
            dlg.deleteLater()

    def test_sorted_by_mtime_desc_and_time_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "old.json"
            new = Path(tmp) / "new.json"
            old.write_text("{}", encoding="utf-8")
            new.write_text("{}", encoding="utf-8")
            os.utime(old, (1000000000, 1000000000))
            os.utime(new, (1700000000, 1700000000))
            dlg = self._make([{"path": str(old), "name": "旧模板"},
                              {"path": str(new), "name": "新模板"}])
            try:
                self.assertEqual(dlg.table.item(0, 0).text(), "新模板")
                self.assertEqual(dlg.table.item(1, 0).text(), "旧模板")
                expected = datetime.fromtimestamp(1700000000).strftime(
                    "%Y-%m-%d %H:%M")
                self.assertEqual(dlg.table.item(0, 1).text(), expected)
            finally:
                dlg.deleteLater()


class FormatMtimeTest(unittest.TestCase):
    def test_invalid_values(self):
        self.assertEqual(format_mtime(0), "—")
        self.assertEqual(format_mtime(-1), "—")
        self.assertEqual(format_mtime(None), "—")

    def test_valid_value(self):
        self.assertRegex(format_mtime(1700000000),
                         r"^\d{4}-\d\d-\d\d \d\d:\d\d$")


if __name__ == "__main__":
    unittest.main()

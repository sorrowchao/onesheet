"""ImportFolderDialog 单元测试（离屏）。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from app.core.folder_scan import SORT_NAME_ASC
from app.ui.import_folder_dialog import ImportFolderDialog

# 必须在构造任何 QWidget 之前创建 QApplication。
_app = QApplication.instance() or QApplication(sys.argv)

MB = 1024 * 1024


def _make(root: Path, rel: str, size: int = 1, mtime: float | None = None) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


class ImportFolderDialogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _make(self.root, "a.xlsx", 10, 100)
        _make(self.root, "b.xls", 20, 200)
        _make(self.root, "note.txt", 5, 50)
        _make(self.root, "s1/d.xlsx", 30, 300)
        _make(self.root, "s1/e.xlsx", 40, 400)
        _make(self.root, "s2/big.xlsx", 2 * MB, 500)
        _make(self.root, "s2/X企业2024.xlsx", 60, 600)
        self.dlg = ImportFolderDialog(str(self.root))
        self.dlg._refresh_preview()

    def tearDown(self):
        self.dlg.deleteLater()
        self._tmp.cleanup()

    def _names(self) -> list[str]:
        return [self.dlg.preview_list.item(i).text()
                for i in range(self.dlg.preview_list.count())]

    # ------------------------------------------------------------------
    def test_title_and_folder_label(self):
        self.assertEqual(self.dlg.windowTitle(), "导入文件夹")
        self.assertEqual(self.dlg.folder_label.text(), str(self.root))

    def test_default_preview_newest_first(self):
        self.assertEqual(self._names(), [
            "b.xls", "a.xlsx",
            "s1/e.xlsx", "s1/d.xlsx",
            "s2/X企业2024.xlsx", "s2/big.xlsx",
        ])
        self.assertEqual(
            self.dlg.summary_label.text(), "将导入 6 个文件（来自 3 个文件夹）")
        self.assertEqual(len(self.dlg.selected_files()), 6)
        self.assertTrue(
            self.dlg.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())

    def test_preview_items_keep_full_path_in_tooltip(self):
        item = self.dlg.preview_list.item(0)
        self.assertTrue(item.toolTip().endswith("b.xls"))

    def test_non_recursive_only_top_level(self):
        self.dlg.recursive_box.setChecked(False)
        self.dlg._refresh_preview()
        self.assertEqual(self._names(), ["b.xls", "a.xlsx"])

    def test_per_folder_limit(self):
        self.dlg.limit_spin.setValue(1)
        self.dlg._refresh_preview()
        self.assertEqual(self._names(), [
            "b.xls", "s1/e.xlsx", "s2/X企业2024.xlsx"])

    def test_sort_choice_changes_order(self):
        idx = self.dlg.sort_combo.findData(SORT_NAME_ASC)
        self.dlg.sort_combo.setCurrentIndex(idx)
        self.dlg._refresh_preview()
        self.assertEqual(self._names(), [
            "a.xlsx", "b.xls",
            "s1/d.xlsx", "s1/e.xlsx",
            "s2/big.xlsx", "s2/X企业2024.xlsx",
        ])

    def test_min_size_filter(self):
        self.dlg.min_size_spin.setValue(2)
        self.dlg._refresh_preview()
        self.assertEqual(self._names(), ["s2/big.xlsx"])

    def test_max_size_filter(self):
        self.dlg.max_size_spin.setValue(0.5)
        self.dlg._refresh_preview()
        self.assertEqual(self._names(), [
            "b.xls", "a.xlsx",
            "s1/e.xlsx", "s1/d.xlsx",
            "s2/X企业2024.xlsx",
        ])

    def test_name_pattern_filters_file_name_only(self):
        self.dlg.pattern_edit.setText("2024")
        self.dlg._refresh_preview()
        self.assertEqual(self._names(), ["s2/X企业2024.xlsx"])

    def test_invalid_regex_disables_ok(self):
        self.dlg.pattern_edit.setText("[")
        self.dlg._refresh_preview()
        ok = self.dlg.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.assertFalse(ok.isEnabled())
        self.assertFalse(self.dlg.error_label.isHidden())
        self.assertIn("正则", self.dlg.error_label.text())
        self.assertEqual(self.dlg.selected_files(), [])
        self.assertEqual(self.dlg.summary_label.text(), "无法预览")

    def test_recovering_from_invalid_regex(self):
        self.dlg.pattern_edit.setText("[")
        self.dlg._refresh_preview()
        self.dlg.pattern_edit.setText("a")
        self.dlg._refresh_preview()
        ok = self.dlg.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.assertTrue(ok.isEnabled())
        self.assertTrue(self.dlg.error_label.isHidden())

    def test_min_greater_than_max_shows_error(self):
        self.dlg.min_size_spin.setValue(2)
        self.dlg.max_size_spin.setValue(0.5)
        self.dlg._refresh_preview()
        ok = self.dlg.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.assertFalse(ok.isEnabled())
        self.assertIn("不能大于", self.dlg.error_label.text())

    def test_zero_matches_disables_ok(self):
        self.dlg.pattern_edit.setText("zzz")
        self.dlg._refresh_preview()
        ok = self.dlg.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.assertFalse(ok.isEnabled())
        self.assertEqual(self.dlg.summary_label.text(), "没有匹配的文件")
        self.assertEqual(self.dlg.preview_list.count(), 0)

    def test_preview_truncation_keeps_selected_files_complete(self):
        with mock.patch("app.ui.import_folder_dialog.PREVIEW_LIMIT", 2):
            self.dlg._refresh_preview()
        self.assertEqual(self.dlg.preview_list.count(), 3)
        self.assertEqual(
            self.dlg.preview_list.item(2).text(), "…还有 4 个未显示")
        self.assertEqual(len(self.dlg.selected_files()), 6)

    def test_options_returns_bytes(self):
        self.dlg.min_size_spin.setValue(1.5)
        self.dlg.max_size_spin.setValue(0.25)
        opts = self.dlg.options()
        self.assertEqual(opts["min_size"], int(1.5 * MB))
        self.assertEqual(opts["max_size"], int(0.25 * MB))
        self.assertEqual(opts["sort_by"], self.dlg.sort_combo.currentData())

    def test_initial_options_populate_widgets_and_preview(self):
        dlg = ImportFolderDialog(str(self.root), initial={
            "recursive": False,
            "per_folder_limit": 1,
            "sort_by": SORT_NAME_ASC,
            "min_size": 0,
            "max_size": 0,
            "name_pattern": "",
        })
        try:
            self.assertFalse(dlg.recursive_box.isChecked())
            self.assertEqual(dlg.limit_spin.value(), 1)
            self.assertEqual(dlg.sort_combo.currentData(), SORT_NAME_ASC)
            self.assertEqual(dlg.preview_list.count(), 1)
            self.assertEqual(dlg.preview_list.item(0).text(), "a.xlsx")
        finally:
            dlg.deleteLater()

    def test_initial_size_bytes_converted_to_mb(self):
        dlg = ImportFolderDialog(str(self.root), initial={
            "min_size": int(1.5 * MB), "max_size": 0})
        try:
            self.assertAlmostEqual(dlg.min_size_spin.value(), 1.5)
            self.assertEqual(dlg.max_size_spin.value(), 0)
        finally:
            dlg.deleteLater()

    def test_accept_with_files_sets_accepted(self):
        self.dlg._on_accept()
        self.assertEqual(self.dlg.result(), QDialog.DialogCode.Accepted)

    def test_accept_without_files_does_not_accept(self):
        self.dlg.pattern_edit.setText("zzz")
        self.dlg._on_accept()
        self.assertNotEqual(self.dlg.result(), QDialog.DialogCode.Accepted)


if __name__ == "__main__":
    unittest.main()

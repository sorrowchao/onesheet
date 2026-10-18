"""FilePanel 单元测试（勾选 / 全选 / 移除，离屏）。"""
import sys
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.ui.file_panel import FilePanel

# 必须在构造任何 QWidget 之前创建 QApplication。
_app = QApplication.instance() or QApplication(sys.argv)


class FilePanelTest(unittest.TestCase):
    def setUp(self):
        self.panel = FilePanel()

    def tearDown(self):
        self.panel.deleteLater()

    def test_add_files_default_checked(self):
        self.panel.add_files(["a.xlsx", "b.xlsx"])
        self.assertEqual(self.panel.files(), ["a.xlsx", "b.xlsx"])
        self.assertEqual(self.panel.checked_files(), ["a.xlsx", "b.xlsx"])

    def test_uncheck_one(self):
        self.panel.add_files(["a.xlsx", "b.xlsx"])
        self.panel.list.item(0).setCheckState(Qt.Unchecked)
        self.assertEqual(self.panel.checked_files(), ["b.xlsx"])

    def test_select_all_deselect_all(self):
        self.panel.add_files(["a.xlsx", "b.xlsx"])
        self.panel._deselect_all()
        self.assertEqual(self.panel.checked_files(), [])
        self.panel._select_all()
        self.assertEqual(self.panel.checked_files(), ["a.xlsx", "b.xlsx"])

    def test_invert_checks_without_filter(self):
        self.panel.add_files(["a.xlsx", "b.xlsx", "c.xlsx"])
        self.panel.list.item(1).setCheckState(Qt.Unchecked)
        self.panel._invert_checks()
        self.assertEqual(self.panel.checked_files(), ["b.xlsx"])

    def test_invert_checks_with_filter_only_affects_visible(self):
        self.panel.add_files(["国能1.xlsx", "国能2.xlsx", "祥瑞1.xlsx"])
        self.panel.search.setText("国能")
        self.panel._invert_checks()   # 两个匹配项取消勾选，隐藏项保持
        self.assertEqual(self.panel.checked_files(), ["祥瑞1.xlsx"])

    def test_remove_checked_only_removes_checked(self):
        self.panel.add_files(["a.xlsx", "b.xlsx", "c.xlsx"])
        self.panel.list.item(1).setCheckState(Qt.Unchecked)  # b 不勾
        self.panel.remove_checked()
        self.assertEqual(self.panel.files(), ["b.xlsx"])
        self.assertEqual(self.panel.checked_files(), [])

    def test_remove_checked_keeps_files_sync(self):
        self.panel.add_files(["a.xlsx", "b.xlsx"])
        self.panel.remove_checked()  # 全勾 -> 全移除
        self.assertEqual(self.panel.files(), [])
        self.assertEqual(self.panel.list.count(), 0)

    def test_clear(self):
        self.panel.add_files(["a.xlsx", "b.xlsx"])
        self.panel.clear()
        self.assertEqual(self.panel.files(), [])
        self.assertEqual(self.panel.checked_files(), [])
        self.assertEqual(self.panel.list.count(), 0)

    def test_add_files_dedup(self):
        self.panel.add_files(["a.xlsx"])
        self.panel.add_files(["a.xlsx", "b.xlsx"])
        self.assertEqual(self.panel.files(), ["a.xlsx", "b.xlsx"])

    def test_filter_hides_non_matching(self):
        self.panel.add_files(["国能1.xlsx", "国能2.xlsx", "祥瑞1.xlsx"])
        self.panel.search.setText("国能")
        visible = [i.text() for i in self.panel._visible_items()]
        self.assertEqual(visible, ["国能1.xlsx", "国能2.xlsx"])
        # files() 仍返回全部（过滤只影响显示）
        self.assertEqual(len(self.panel.files()), 3)

    def test_filter_case_insensitive(self):
        self.panel.add_files(["Alpha.xlsx", "beta.xlsx"])
        self.panel.search.setText("alpha")
        self.assertEqual([i.text() for i in self.panel._visible_items()], ["Alpha.xlsx"])

    def test_filter_empty_shows_all(self):
        self.panel.add_files(["a.xlsx", "b.xlsx"])
        self.panel.search.setText("a")
        self.panel.search.clear()
        self.assertEqual(len(self.panel._visible_items()), 2)

    def test_select_all_with_filter_only_selects_matches(self):
        self.panel.add_files(["国能1.xlsx", "国能2.xlsx", "祥瑞1.xlsx"])
        self.panel.search.setText("国能")
        self.panel._select_all()
        self.assertEqual(self.panel.checked_files(), ["国能1.xlsx", "国能2.xlsx"])

    def test_select_all_without_filter_selects_everything(self):
        self.panel.add_files(["a.xlsx", "b.xlsx"])
        self.panel._deselect_all()
        self.panel._select_all()
        self.assertEqual(self.panel.checked_files(), ["a.xlsx", "b.xlsx"])

    def test_deselect_all_with_filter_only_unchecks_matches(self):
        self.panel.add_files(["国能1.xlsx", "祥瑞1.xlsx"])
        self.panel.search.setText("国能")
        self.panel._deselect_all()
        self.assertEqual(self.panel.checked_files(), ["祥瑞1.xlsx"])

    def test_add_files_respects_active_filter(self):
        self.panel.search.setText("国能")
        self.panel.add_files(["国能1.xlsx", "祥瑞1.xlsx"])
        visible = [i.text() for i in self.panel._visible_items()]
        self.assertEqual(visible, ["国能1.xlsx"])

    def test_clear_resets_filter(self):
        self.panel.add_files(["国能1.xlsx"])
        self.panel.search.setText("国能")
        self.panel.clear()
        self.assertEqual(self.panel.search.text(), "")
        self.assertEqual(self.panel.files(), [])

    def test_display_name_only_keeps_full_path(self):
        full = "dir/sub/国能1.xlsx"
        self.panel.add_files([full])
        # 列表只显示文件名
        self.assertEqual(self.panel.list.item(0).text(), "国能1.xlsx")
        # 但底层仍是完整路径
        self.assertEqual(self.panel.files(), [full])
        self.assertEqual(self.panel.checked_files(), [full])

    def test_filter_matches_display_name(self):
        self.panel.add_files(["dir1/国能1.xlsx", "dir2/祥瑞1.xlsx"])
        self.panel.search.setText("国能")
        self.assertEqual([i.text() for i in self.panel._visible_items()], ["国能1.xlsx"])
        self.panel._select_all()
        self.assertEqual(self.panel.checked_files(), ["dir1/国能1.xlsx"])

    def test_import_buttons_emit_signals(self):
        files_fired, folder_fired = [], []
        self.panel.import_files_requested.connect(lambda: files_fired.append(True))
        self.panel.import_folder_requested.connect(lambda: folder_fired.append(True))
        self.panel.btn_import_files.click()
        self.panel.btn_import_folder.click()
        self.assertEqual(files_fired, [True])
        self.assertEqual(folder_fired, [True])


if __name__ == "__main__":
    unittest.main()

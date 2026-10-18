"""theme.py 单元测试（纯 QSS 生成，不需要 Qt）。"""
import unittest

from app.ui import theme


class ThemeTest(unittest.TestCase):
    def test_stylesheet_non_empty_and_placeholders_filled(self):
        for name in theme.ALL:
            qss = theme.stylesheet(name)
            self.assertTrue(qss.strip())
            self.assertNotIn("$", qss)  # 占位符应全部被替换

    def test_dark_and_light_differ(self):
        self.assertNotEqual(theme.stylesheet(theme.DARK),
                            theme.stylesheet(theme.LIGHT))

    def test_normalize_unknown_falls_back(self):
        self.assertEqual(theme.normalize("bogus"), theme.DEFAULT)
        self.assertEqual(theme.normalize(None), theme.DEFAULT)
        self.assertEqual(theme.normalize(theme.LIGHT), theme.LIGHT)

    def test_unknown_name_matches_default(self):
        self.assertEqual(theme.stylesheet("bogus"),
                         theme.stylesheet(theme.DEFAULT))

    def test_checked_indicator_points_to_check_icon(self):
        icon = theme.check_icon_path()
        self.assertTrue(icon.exists(), f"勾图标不存在：{icon}")
        for name in theme.ALL:
            qss = theme.stylesheet(name)
            self.assertIn("image: url(", qss)
            self.assertIn(icon.as_posix(), qss)

    def test_check_icon_is_svg(self):
        self.assertEqual(theme.check_icon_path().suffix.lower(), ".svg")

    def test_combo_popup_selected_item_has_readable_colors(self):
        """下拉当前项必须同时有选中背景和文字色（否则白字白底看不清）。"""
        for name in theme.ALL:
            qss = theme.stylesheet(name)
            marker = "QComboBox QAbstractItemView::item:selected"
            self.assertIn(marker, qss)
            block = qss.split(marker, 1)[1].split("}", 1)[0]
            self.assertIn("background-color:", block)
            self.assertIn("color:", block)

    def test_base_font_size_readable(self):
        for name in theme.ALL:
            self.assertIn("font-size: 13px", theme.stylesheet(name))

    def test_log_uses_monospace_font(self):
        for name in theme.ALL:
            qss = theme.stylesheet(name)
            self.assertIn("QPlainTextEdit#logView", qss)
            self.assertIn("font-family: Consolas", qss)

    def test_fields_table_checkbox_centered(self):
        """字段映射表首列勾选框靠 QSS margin 居中（列宽 44、勾选框 17）。"""
        for name in theme.ALL:
            qss = theme.stylesheet(name)
            self.assertIn("QTableWidget#fieldsTable::indicator", qss)
            block = qss.split("QTableWidget#fieldsTable::indicator", 1)[1]
            self.assertIn("margin-left: 13px", block.split("}", 1)[0])


if __name__ == "__main__":
    unittest.main()

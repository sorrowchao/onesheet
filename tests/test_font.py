"""font.py 单元测试（离屏；字体族探测可注入，不依赖本机安装）。"""
import sys
import unittest

from PySide6.QtWidgets import QApplication

from app.ui import font as ui_font

# QFontDatabase 需要 QGuiApplication。
_app = QApplication.instance() or QApplication(sys.argv)


class FontTest(unittest.TestCase):
    def test_resolve_keeps_preference_order(self):
        available = ["Segoe UI", "Microsoft YaHei UI", "Arial"]
        self.assertEqual(
            ui_font.resolve_families(("Microsoft YaHei UI", "Segoe UI",
                                      "Arial"), available),
            ["Microsoft YaHei UI", "Segoe UI", "Arial"],
        )

    def test_resolve_skips_missing(self):
        available = ["Arial"]
        self.assertEqual(
            ui_font.resolve_families(("Microsoft YaHei UI", "Arial"),
                                     available),
            ["Arial"],
        )

    def test_resolve_is_case_insensitive(self):
        self.assertEqual(
            ui_font.resolve_families(("Microsoft YaHei UI",),
                                     ["microsoft yahei ui"]),
            ["Microsoft YaHei UI"],
        )

    def test_resolve_none_available(self):
        self.assertEqual(ui_font.resolve_families(("Arial",), []), [])

    def test_ui_font_sets_families_and_size(self):
        f = ui_font.ui_font(("Microsoft YaHei UI", "Arial"),
                            ["Arial", "Microsoft YaHei UI"],
                            point_size=10)
        self.assertEqual(f.families(), ["Microsoft YaHei UI", "Arial"])
        self.assertAlmostEqual(f.pointSizeF(), 10.0)

    def test_ui_font_without_any_preferred_still_has_size(self):
        f = ui_font.ui_font(("Missing Font",), [], point_size=9.75)
        self.assertAlmostEqual(f.pointSizeF(), 9.75)
        self.assertNotIn("Missing Font", f.families())

    def test_apply_app_font_sets_application_font(self):
        old = _app.font()
        try:
            applied = ui_font.apply_app_font(_app)
            self.assertAlmostEqual(applied.pointSizeF(),
                                   ui_font.BASE_POINT_SIZE)
            self.assertAlmostEqual(_app.font().pointSizeF(),
                                   ui_font.BASE_POINT_SIZE)
        finally:
            _app.setFont(old)


if __name__ == "__main__":
    unittest.main()

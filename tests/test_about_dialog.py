"""AboutDialog 内容测试（离屏）。"""
import sys
import unittest

from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel

from app import __version__
from app.ui.about_dialog import (CONTACT_EMAIL, ICON_SOURCE_URL, AboutDialog,
                                 APP_NAME)

# 必须在构造任何 QWidget 之前创建 QApplication。
_app = QApplication.instance() or QApplication(sys.argv)


class AboutDialogTest(unittest.TestCase):
    def setUp(self):
        self.dialog = AboutDialog()
        self.texts = [lbl.text() for lbl in self.dialog.findChildren(QLabel)]

    def tearDown(self):
        self.dialog.deleteLater()

    def test_app_name_and_description(self):
        self.assertIn(APP_NAME, "\n".join(self.texts))
        joined = "\n".join(self.texts)
        self.assertIn("Excel / Word / PDF / CSV", joined)

    def test_version(self):
        self.assertEqual(__version__, "2.0")
        self.assertIn("版本 2.0", "\n".join(self.texts))

    def test_code_attribution(self):
        self.assertIn("忧凉 & DeepSeek-V4.1-Flash-1017", "\n".join(self.texts))

    def test_icon_source_link(self):
        joined = "\n".join(self.texts)
        self.assertIn("阿里巴巴矢量图标库", joined)
        self.assertIn(f'href="{ICON_SOURCE_URL}"', joined)

    def test_email_link(self):
        joined = "\n".join(self.texts)
        self.assertIn(CONTACT_EMAIL, joined)
        self.assertIn(f'href="mailto:{CONTACT_EMAIL}"', joined)

    def test_infringement_notice(self):
        self.assertIn("如有侵权，联系删除。", "\n".join(self.texts))

    def test_links_open_externally(self):
        links = [lbl for lbl in self.dialog.findChildren(QLabel)
                 if "<a href=" in lbl.text()]
        self.assertEqual(len(links), 2)
        for lbl in links:
            self.assertTrue(lbl.openExternalLinks())

    def test_close_button(self):
        close = self.dialog.buttons.button(
            QDialogButtonBox.StandardButton.Close)
        self.assertEqual(close.text(), "关闭")


if __name__ == "__main__":
    unittest.main()

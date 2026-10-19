"""ApiKeyDialog 单元测试（离屏）。"""
import sys
import unittest

from PySide6.QtWidgets import QApplication, QLineEdit

from app.main_window import ApiKeyDialog

# 必须在构造任何 QWidget 之前创建 QApplication。
_app = QApplication.instance() or QApplication(sys.argv)


class ApiKeyDialogTest(unittest.TestCase):
    def test_prefilled_key_is_masked(self):
        dlg = ApiKeyDialog("sk-abc123")
        self.assertEqual(dlg.key(), "sk-abc123")
        self.assertEqual(dlg.key_edit.echoMode(), QLineEdit.EchoMode.Password)
        self.assertFalse(dlg.show_box.isChecked())

    def test_toggle_show_plaintext(self):
        dlg = ApiKeyDialog("sk-abc123")
        dlg.show_box.setChecked(True)
        self.assertEqual(dlg.key_edit.echoMode(), QLineEdit.EchoMode.Normal)
        dlg.show_box.setChecked(False)
        self.assertEqual(dlg.key_edit.echoMode(), QLineEdit.EchoMode.Password)

    def test_empty_key_returns_empty(self):
        dlg = ApiKeyDialog("sk-abc123")
        dlg.key_edit.clear()
        self.assertEqual(dlg.key(), "")

    def test_api_url_and_model_prefilled(self):
        dlg = ApiKeyDialog("sk-abc123", api_url="https://api.openai.com/v1",
                           model="gpt-4o-mini")
        self.assertEqual(dlg.api_url(), "https://api.openai.com/v1")
        self.assertEqual(dlg.model(), "gpt-4o-mini")

    def test_api_url_and_model_default_empty(self):
        dlg = ApiKeyDialog("sk-abc123")
        self.assertEqual(dlg.api_url(), "")
        self.assertEqual(dlg.model(), "")

    def test_vision_model_prefilled_and_empty_by_default(self):
        dlg = ApiKeyDialog("sk-abc123", vision_model="qwen-vl-max")
        self.assertEqual(dlg.vision_model(), "qwen-vl-max")
        dlg2 = ApiKeyDialog("sk-abc123")
        self.assertEqual(dlg2.vision_model(), "")

    def test_vision_model_reads_edited_text(self):
        dlg = ApiKeyDialog("sk-abc123")
        dlg.vision_edit.setText("  gpt-4o  ")
        self.assertEqual(dlg.vision_model(), "gpt-4o")


if __name__ == "__main__":
    unittest.main()

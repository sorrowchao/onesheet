"""settings.py 单元测试（key 存取）。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.service import settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        # 环境变量会覆盖文件，测试期间先清掉以保证可预期
        self._env = mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_missing_file_returns_empty(self):
        self.assertEqual(settings.load_settings(self.dir), {})
        self.assertEqual(settings.get_api_key(self.dir), "")

    def test_set_get_round_trip(self):
        settings.set_api_key("sk-abcd1234", self.dir)
        self.assertEqual(settings.get_api_key(self.dir), "sk-abcd1234")

    def test_set_preserves_other_keys(self):
        settings.save_settings({"other": 1}, self.dir)
        settings.set_api_key("k", self.dir)
        self.assertEqual(settings.load_settings(self.dir), {"other": 1,
                                                           "deepseek_api_key": "k"})

    def test_bad_json_returns_empty(self):
        settings.settings_path(self.dir).write_text("{ not json", encoding="utf-8")
        self.assertEqual(settings.load_settings(self.dir), {})

    def test_env_overrides_file(self):
        settings.set_api_key("file-key", self.dir)
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            self.assertEqual(settings.get_api_key(self.dir), "env-key")

    def test_stored_key_ignores_env(self):
        settings.set_api_key("file-key", self.dir)
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            self.assertEqual(settings.get_stored_api_key(self.dir), "file-key")

    def test_set_empty_key_clears(self):
        settings.set_api_key("file-key", self.dir)
        settings.set_api_key("   ", self.dir)
        self.assertEqual(settings.get_stored_api_key(self.dir), "")
        self.assertNotIn("deepseek_api_key", settings.load_settings(self.dir))

    def test_theme_default_is_dark(self):
        self.assertEqual(settings.get_theme(self.dir), "dark")

    def test_theme_round_trip(self):
        settings.set_theme("light", self.dir)
        self.assertEqual(settings.get_theme(self.dir), "light")

    def test_theme_invalid_ignored(self):
        settings.set_theme("light", self.dir)
        settings.set_theme("bogus", self.dir)
        self.assertEqual(settings.get_theme(self.dir), "light")

    def test_theme_preserves_api_key(self):
        settings.set_api_key("k", self.dir)
        settings.set_theme("light", self.dir)
        self.assertEqual(settings.get_api_key(self.dir), "k")

    # --- 窗口状态 / 上次导入目录 ---
    def test_window_state_default_empty(self):
        self.assertEqual(settings.get_window_state(self.dir), {})

    def test_window_state_round_trip(self):
        state = {"width": 1000, "height": 700, "maximized": False,
                 "main_splitter": [200, 400, 500],
                 "v_splitter": [400, 300]}
        settings.set_window_state(state, self.dir)
        self.assertEqual(settings.get_window_state(self.dir), state)

    def test_window_state_preserves_api_key(self):
        settings.set_api_key("k", self.dir)
        settings.set_window_state({"width": 900}, self.dir)
        self.assertEqual(settings.get_api_key(self.dir), "k")

    def test_last_import_dir_round_trip(self):
        settings.set_last_import_dir("C:/data", self.dir)
        self.assertEqual(settings.get_last_import_dir(self.dir), "C:/data")

    def test_last_import_dir_empty_clears(self):
        settings.set_last_import_dir("C:/data", self.dir)
        settings.set_last_import_dir("   ", self.dir)
        self.assertEqual(settings.get_last_import_dir(self.dir), "")

    # --- 应用图标 ---
    def _make_icons(self, *names):
        d = settings.icons_dir(self.dir)
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / f"{n}.png").write_bytes(b"")

    def test_icon_defaults_to_1(self):
        self._make_icons("1", "2", "3")
        self.assertEqual(settings.get_icon(self.dir), "1")
        self.assertEqual(settings.icon_path(None, self.dir),
                         settings.icons_dir(self.dir) / "1.png")

    def test_icon_falls_back_to_first_when_default_missing(self):
        self._make_icons("3", "2")
        self.assertEqual(settings.get_icon(self.dir), "2")

    def test_icon_set_round_trip(self):
        self._make_icons("1", "2")
        settings.set_icon("2", self.dir)
        self.assertEqual(settings.get_icon(self.dir), "2")

    def test_icon_invalid_name_ignored(self):
        self._make_icons("1", "2")
        settings.set_icon("1", self.dir)
        settings.set_icon("bogus", self.dir)
        self.assertEqual(settings.get_icon(self.dir), "1")

    def test_icons_sorted_numerically(self):
        self._make_icons("10", "2", "1")
        names = [p.stem for p in settings.available_icons(self.dir)]
        self.assertEqual(names, ["1", "2", "10"])

    def test_no_icons_returns_empty(self):
        self.assertEqual(settings.get_icon(self.dir), "")
        self.assertIsNone(settings.icon_path(None, self.dir))


if __name__ == "__main__":
    unittest.main()

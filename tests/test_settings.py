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
        self._env = mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "", "OPENAI_API_KEY": "",
            "OPENAI_BASE_URL": "", "OPENAI_MODEL": "",
            "OPENAI_VISION_MODEL": "",
        })
        self._env.start()
        # 图标测试只看临时目录：把内置 app/icons 指向一个不存在的目录。
        self._bundled = self.dir / "app_icons_missing"
        self._bundled_patch = mock.patch.object(
            settings, "bundled_icons_dir", return_value=self._bundled)
        self._bundled_patch.start()

    def tearDown(self):
        self._bundled_patch.stop()
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

    def test_openai_env_key_fallback(self):
        settings.set_api_key("file-key", self.dir)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "env-openai"}):
            self.assertEqual(settings.get_api_key(self.dir), "env-openai")

    def test_deepseek_env_key_wins_over_openai(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-deepseek",
                                          "OPENAI_API_KEY": "env-openai"}):
            self.assertEqual(settings.get_api_key(self.dir), "env-deepseek")

    # --- OpenAI 兼容接口配置（地址 / 模型）---
    def test_ai_api_url_round_trip(self):
        settings.set_ai_api_url("https://api.openai.com/v1", self.dir)
        self.assertEqual(settings.get_ai_api_url(self.dir),
                         "https://api.openai.com/v1")

    def test_ai_api_url_empty_clears(self):
        settings.set_ai_api_url("https://api.openai.com/v1", self.dir)
        settings.set_ai_api_url("  ", self.dir)
        self.assertEqual(settings.get_ai_api_url(self.dir), "")
        self.assertNotIn("ai_api_url", settings.load_settings(self.dir))

    def test_ai_api_url_env_overrides(self):
        settings.set_ai_api_url("file-url", self.dir)
        with mock.patch.dict(os.environ, {"OPENAI_BASE_URL": "env-url"}):
            self.assertEqual(settings.get_ai_api_url(self.dir), "env-url")
            self.assertEqual(settings.get_stored_ai_api_url(self.dir), "file-url")

    def test_ai_model_round_trip(self):
        settings.set_ai_model("gpt-4o-mini", self.dir)
        self.assertEqual(settings.get_ai_model(self.dir), "gpt-4o-mini")

    def test_ai_model_empty_clears(self):
        settings.set_ai_model("gpt-4o-mini", self.dir)
        settings.set_ai_model("", self.dir)
        self.assertEqual(settings.get_ai_model(self.dir), "")

    def test_ai_model_env_overrides(self):
        settings.set_ai_model("file-model", self.dir)
        with mock.patch.dict(os.environ, {"OPENAI_MODEL": "env-model"}):
            self.assertEqual(settings.get_ai_model(self.dir), "env-model")
            self.assertEqual(settings.get_stored_ai_model(self.dir), "file-model")

    # --- 视觉模型（PDF 扫描件）---
    def test_ai_vision_model_round_trip(self):
        settings.set_ai_vision_model("qwen-vl-max", self.dir)
        self.assertEqual(settings.get_ai_vision_model(self.dir), "qwen-vl-max")

    def test_ai_vision_model_falls_back_to_model(self):
        settings.set_ai_model("gpt-4o-mini", self.dir)
        self.assertEqual(settings.get_ai_vision_model(self.dir), "gpt-4o-mini")

    def test_ai_vision_model_env_precedence(self):
        settings.set_ai_vision_model("file-vision", self.dir)
        settings.set_ai_model("file-model", self.dir)
        with mock.patch.dict(os.environ, {"OPENAI_VISION_MODEL": "env-vision"}):
            self.assertEqual(settings.get_ai_vision_model(self.dir), "env-vision")
            self.assertEqual(
                settings.get_stored_ai_vision_model(self.dir), "file-vision")

    def test_ai_vision_model_empty_clears(self):
        settings.set_ai_vision_model("qwen-vl-max", self.dir)
        settings.set_ai_vision_model("  ", self.dir)
        self.assertEqual(settings.get_stored_ai_vision_model(self.dir), "")
        self.assertNotIn("ai_vision_model", settings.load_settings(self.dir))

    def test_ai_config_preserves_api_key(self):
        settings.set_api_key("k", self.dir)
        settings.set_ai_api_url("https://api.openai.com/v1", self.dir)
        settings.set_ai_model("gpt-4o-mini", self.dir)
        self.assertEqual(settings.get_api_key(self.dir), "k")

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

    # --- 导入文件夹选项 ---
    def test_folder_import_options_default_empty(self):
        self.assertEqual(settings.get_folder_import_options(self.dir), {})

    def test_folder_import_options_round_trip(self):
        opts = {"recursive": False, "per_folder_limit": 2,
                "sort_by": "size_smallest", "min_size": 10,
                "max_size": 20, "name_pattern": "107"}
        settings.set_folder_import_options(opts, self.dir)
        self.assertEqual(settings.get_folder_import_options(self.dir), opts)

    def test_folder_import_options_empty_clears(self):
        settings.set_folder_import_options({"per_folder_limit": 1}, self.dir)
        settings.set_folder_import_options({}, self.dir)
        self.assertEqual(settings.get_folder_import_options(self.dir), {})

    def test_folder_import_options_preserves_other_keys(self):
        settings.set_api_key("k", self.dir)
        settings.set_folder_import_options({"per_folder_limit": 1}, self.dir)
        self.assertEqual(settings.get_api_key(self.dir), "k")

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

    # --- 内置图标 app/icons（打包进 exe）---
    def _make_bundled(self, *names):
        d = self._bundled
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / f"{n}.png").write_bytes(b"")

    def test_bundled_icons_available_without_user_dir(self):
        self._make_bundled("1", "2")
        names = [p.stem for p in settings.available_icons(self.dir)]
        self.assertEqual(names, ["1", "2"])
        self.assertEqual(settings.icon_path(None, self.dir), self._bundled / "1.png")

    def test_user_icon_overrides_bundled_same_name(self):
        self._make_bundled("1")
        self._make_icons("1")
        self.assertEqual(settings.icon_path(None, self.dir),
                         settings.icons_dir(self.dir) / "1.png")

    def test_bundled_and_user_icons_merged(self):
        self._make_bundled("1", "2")
        self._make_icons("3")
        names = [p.stem for p in settings.available_icons(self.dir)]
        self.assertEqual(names, ["1", "2", "3"])


if __name__ == "__main__":
    unittest.main()

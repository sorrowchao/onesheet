"""title_bar_win 单元测试（不真正修改系统窗口，只验证调用逻辑）。"""
import unittest
from unittest import mock

from app.ui import title_bar_win


class _FakeWindow:
    def winId(self):
        return 123


class _FakeWidget:
    def window(self):
        return _FakeWindow()


def _windll_returning(result_for):
    """构造按属性号返回 HRESULT 的假 dwmapi，并记录标题栏重绘调用。"""
    seen = []

    def set_attribute(_hwnd, attribute, _value, _size):
        seen.append(attribute)
        return result_for(attribute)

    fake_dwm = mock.Mock()
    fake_dwm.DwmSetWindowAttribute.side_effect = set_attribute
    fake_user32 = mock.Mock()
    return fake_dwm, fake_user32, seen


class DarkTitleBarTest(unittest.TestCase):
    def test_non_windows_returns_false(self):
        with mock.patch.object(title_bar_win.sys, "platform", "linux"):
            self.assertFalse(title_bar_win.apply_dark_title_bar(_FakeWidget(), True))

    def test_uses_20h1_attribute_first(self):
        fake_dwm, fake_user32, seen = _windll_returning(lambda attr: 0)
        with mock.patch.object(title_bar_win.sys, "platform", "win32"), \
                mock.patch.object(title_bar_win.ctypes, "windll",
                                  mock.Mock(dwmapi=fake_dwm, user32=fake_user32),
                                  create=True):
            self.assertTrue(title_bar_win.apply_dark_title_bar(_FakeWidget(), True))
        self.assertEqual(seen, [20])
        # 成功后发一对 WM_NCACTIVATE，立即重绘标题栏，
        # 无需用户手动最大化/还原窗口。
        calls = fake_user32.SendMessageW.call_args_list
        self.assertEqual([(c.args[1], c.args[2]) for c in calls],
                         [(0x0086, 0), (0x0086, 1)])

    def test_falls_back_to_legacy_attribute(self):
        fake_dwm, fake_user32, seen = _windll_returning(
            lambda attr: 0 if attr == 19 else 1)
        with mock.patch.object(title_bar_win.sys, "platform", "win32"), \
                mock.patch.object(title_bar_win.ctypes, "windll",
                                  mock.Mock(dwmapi=fake_dwm, user32=fake_user32),
                                  create=True):
            self.assertTrue(title_bar_win.apply_dark_title_bar(_FakeWidget(), False))
        self.assertEqual(seen, [20, 19])
        self.assertEqual(fake_user32.SendMessageW.call_count, 2)

    def test_all_attributes_failing_returns_false(self):
        fake_dwm, fake_user32, seen = _windll_returning(lambda attr: 1)
        with mock.patch.object(title_bar_win.sys, "platform", "win32"), \
                mock.patch.object(title_bar_win.ctypes, "windll",
                                  mock.Mock(dwmapi=fake_dwm, user32=fake_user32),
                                  create=True):
            self.assertFalse(title_bar_win.apply_dark_title_bar(_FakeWidget(), True))
        self.assertEqual(seen, [20, 19])
        fake_user32.SendMessageW.assert_not_called()

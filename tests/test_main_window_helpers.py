"""MainWindow 辅助逻辑测试（不显示窗口）。"""
import unittest

from app.main_window import MainWindow


class IntSizesTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(MainWindow._int_sizes([1, 2, 3], 3), [1, 2, 3])

    def test_wrong_length(self):
        self.assertIsNone(MainWindow._int_sizes([1, 2], 3))

    def test_invalid_values(self):
        self.assertIsNone(MainWindow._int_sizes([1, "x", 3], 3))
        self.assertIsNone(MainWindow._int_sizes("bad", 3))


if __name__ == "__main__":
    unittest.main()

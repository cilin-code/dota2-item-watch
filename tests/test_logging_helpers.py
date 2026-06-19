import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from main import _display_width, _pad_display, _price_label, _short_name


class LoggingHelperTests(unittest.TestCase):
    def test_price_label_formats_missing_and_numeric_values(self):
        self.assertEqual(_price_label(None), "未获取")
        self.assertEqual(_price_label(1.234), "¥1.23")

    def test_short_name_truncates_long_values(self):
        self.assertEqual(_short_name("短名"), "短名")
        self.assertEqual(_short_name("abcdef", limit=4), "a...")

    def test_pad_display_accounts_for_chinese_width(self):
        self.assertEqual(_display_width("单刷"), 4)
        self.assertEqual(_pad_display("单刷", 4), "单刷")
        mixed = _pad_display("高达 SP", 10)
        self.assertEqual(_display_width(mixed), 10)


if __name__ == "__main__":
    unittest.main()

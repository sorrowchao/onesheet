"""folder_scan 单元测试（纯逻辑，无需 QApplication）。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core.folder_scan import (DEFAULTS, DOCUMENT_EXTS, EXCEL_EXTS,
                                  FolderScanError, INPUT_EXTS,
                                  SORT_MTIME_OLDEST, SORT_NAME_ASC, SORT_PATH,
                                  SORT_SIZE_LARGEST, SORT_SIZE_SMALLEST,
                                  normalize_options, scan_folder)


def _make(root: Path, rel: str, size: int = 1, mtime: float | None = None) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


class FolderScanTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _make(self.root, "a.xlsx", 10, 100)
        _make(self.root, "b.xls", 20, 200)
        _make(self.root, "c.txt", 5, 900)
        _make(self.root, "s1/d.xlsx", 30, 300)
        _make(self.root, "s1/e.xlsx", 40, 400)
        _make(self.root, "s1/deep/f.xlsx", 50, 500)
        _make(self.root, "s2/g.xlsm", 60, 600)

    def tearDown(self):
        self._tmp.cleanup()

    def _scan(self, **kw):
        return self._names(scan_folder(self.root, **kw))

    def _names(self, files):
        return [Path(f).relative_to(self.root).as_posix() for f in files]

    # ------------------------------------------------------------------
    def test_top_level_only(self):
        self.assertEqual(self._scan(recursive=False), ["b.xls", "a.xlsx"])

    def test_recursive_default_newest_first(self):
        self.assertEqual(self._scan(), [
            "b.xls", "a.xlsx",
            "s1/e.xlsx", "s1/d.xlsx",
            "s1/deep/f.xlsx",
            "s2/g.xlsm",
        ])

    def test_per_folder_limit(self):
        self.assertEqual(self._scan(per_folder_limit=1), [
            "b.xls", "s1/e.xlsx", "s1/deep/f.xlsx", "s2/g.xlsm",
        ])

    def test_negative_limit_means_unlimited(self):
        self.assertEqual(len(self._scan(per_folder_limit=-3)), 6)

    def test_sort_oldest(self):
        self.assertEqual(self._scan(sort_by=SORT_MTIME_OLDEST)[:4], [
            "a.xlsx", "b.xls", "s1/d.xlsx", "s1/e.xlsx",
        ])

    def test_sort_name(self):
        self.assertEqual(self._scan(sort_by=SORT_NAME_ASC)[:4], [
            "a.xlsx", "b.xls", "s1/d.xlsx", "s1/e.xlsx",
        ])

    def test_sort_size_largest(self):
        self.assertEqual(self._scan(sort_by=SORT_SIZE_LARGEST)[:2], ["b.xls", "a.xlsx"])

    def test_sort_size_smallest(self):
        self.assertEqual(self._scan(sort_by=SORT_SIZE_SMALLEST)[:2], ["a.xlsx", "b.xls"])

    def test_min_size_inclusive(self):
        self.assertEqual(self._scan(min_size=30), [
            "s1/e.xlsx", "s1/d.xlsx", "s1/deep/f.xlsx", "s2/g.xlsm",
        ])

    def test_max_size_inclusive(self):
        self.assertEqual(self._scan(max_size=40), [
            "b.xls", "a.xlsx", "s1/e.xlsx", "s1/d.xlsx",
        ])

    def test_zero_byte_included_when_no_min(self):
        _make(self.root, "zero/z.xlsx", 0, 50)
        self.assertIn("zero/z.xlsx", self._scan())

    def test_regex_matches_file_name_only(self):
        _make(self.root, "prefix_dir/plain.xlsx", 5, 50)
        self.assertEqual(self._scan(name_pattern="prefix_dir"), [])

    def test_regex_inline_flags(self):
        _make(self.root, "REPORT.xlsx", 5, 50)
        self.assertEqual(self._scan(name_pattern="(?i)report"), ["REPORT.xlsx"])

    def test_tiebreak_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make(root, "t2.xlsx", 1, 100)
            _make(root, "t1.xlsx", 1, 100)
            names = [Path(f).name for f in scan_folder(root)]
            self.assertEqual(names, ["t1.xlsx", "t2.xlsx"])

    def test_legacy_path_order(self):
        self.assertEqual(self._scan(sort_by=SORT_PATH), [
            "a.xlsx", "b.xls",
            "s1/d.xlsx", "s1/deep/f.xlsx", "s1/e.xlsx",
            "s2/g.xlsm",
        ])

    # ------------------------------------------------------------------
    def test_invalid_regex(self):
        with self.assertRaises(FolderScanError):
            scan_folder(self.root, name_pattern="[")

    def test_min_greater_than_max(self):
        with self.assertRaises(FolderScanError):
            scan_folder(self.root, min_size=100, max_size=10)

    def test_negative_sizes(self):
        with self.assertRaises(FolderScanError):
            scan_folder(self.root, min_size=-1)

    def test_missing_root(self):
        with self.assertRaises(FolderScanError):
            scan_folder(self.root / "nope")

    def test_file_as_root(self):
        with self.assertRaises(FolderScanError):
            scan_folder(self.root / "a.xlsx")

    def test_unknown_sort(self):
        with self.assertRaises(FolderScanError):
            scan_folder(self.root, sort_by="bogus")

    def test_stat_failure_skips_file(self):
        with mock.patch("app.core.folder_scan._safe_stat", return_value=None):
            self.assertEqual(scan_folder(self.root), [])


class InputExtensionsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _make(self.root, "a.xlsx", 1, 100)
        _make(self.root, "b.docx", 1, 200)
        _make(self.root, "c.pdf", 1, 300)
        _make(self.root, "d.csv", 1, 400)
        _make(self.root, "e.txt", 1, 500)
        _make(self.root, "f.doc", 1, 600)

    def tearDown(self):
        self._tmp.cleanup()

    def test_input_exts_include_documents(self):
        self.assertEqual(INPUT_EXTS, EXCEL_EXTS | DOCUMENT_EXTS)

    def test_scan_includes_documents_excludes_txt_and_old_doc(self):
        names = [Path(f).name for f in scan_folder(self.root)]
        self.assertEqual(sorted(names), ["a.xlsx", "b.docx", "c.pdf", "d.csv"])


class NormalizeOptionsTest(unittest.TestCase):
    def test_none_returns_defaults(self):
        self.assertEqual(normalize_options(None), DEFAULTS)

    def test_invalid_values_fall_back(self):
        opts = normalize_options({
            "recursive": "yes",
            "per_folder_limit": -5,
            "sort_by": SORT_PATH,          # 设置文件里不应出现内部排序
            "min_size": True,
            "max_size": "big",
            "name_pattern": 123,
            "extra": "ignored",
        })
        self.assertEqual(opts, DEFAULTS)

    def test_valid_values_and_idempotent(self):
        raw = {
            "recursive": False,
            "per_folder_limit": 2,
            "sort_by": SORT_SIZE_SMALLEST,
            "min_size": 10,
            "max_size": 20,
            "name_pattern": "107",
        }
        opts = normalize_options(raw)
        self.assertEqual(opts, raw)
        self.assertEqual(normalize_options(opts), raw)

    def test_non_dict_returns_defaults(self):
        self.assertEqual(normalize_options(["x"]), DEFAULTS)


if __name__ == "__main__":
    unittest.main()

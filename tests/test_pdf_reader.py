"""pdf_reader 单元测试：注入假 PDF / 假视觉模型 caller，无需真实文件与网络。"""
import json
import unittest

from app.core.ai_scan import AiScanError
from app.core.pdf_reader import PdfScanError, VisionConfig, read_pdf

LONG_TEXT = "单位名称 X企业有限公司 项目名称 测试项目 数量 1000 单位 个 备注 无"


class FakeOriginal:
    mode = "RGB"

    def __init__(self, payload: bytes = b"JPEGDATA"):
        self.payload = payload

    def save(self, buf, format=None, **kwargs):
        buf.write(self.payload)


class FakeImage:
    def __init__(self, payload: bytes = b"JPEGDATA"):
        self.original = FakeOriginal(payload)


class FakePage:
    def __init__(self, text="", tables=None, words=None, payload=b"JPEGDATA"):
        self.text = text
        self.tables = tables if tables is not None else []
        self.words = words if words is not None else []
        self.payload = payload
        self.image_calls = 0

    def extract_text(self):
        return self.text

    def extract_tables(self):
        return self.tables

    def extract_words(self):
        return self.words

    def to_image(self, resolution=150):
        self.image_calls += 1
        self.resolution = resolution
        return FakeImage(self.payload)


class FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _opener(*pages):
    return lambda _path: FakePdf(list(pages))


class PDFPasswordIncorrect(Exception):
    pass


class TextPageTest(unittest.TestCase):
    def test_extracts_tables_first(self):
        page = FakePage(
            text=LONG_TEXT,
            tables=[[["单位名称", "X企业"], ["项目名称", "测试项目"]]],
            words=[{"text": "不应被使用", "x0": 0, "x1": 10, "top": 0}],
        )
        sheets = read_pdf("x.pdf", pdf_open=_opener(page))
        self.assertEqual([s.name for s in sheets], ["表1"])
        self.assertEqual(sheets[0].grid, [["单位名称", "X企业"],
                                          ["项目名称", "测试项目"]])

    def test_layout_when_no_tables(self):
        page = FakePage(text=LONG_TEXT, words=[
            {"text": "单位名称", "x0": 0, "x1": 48, "top": 10},
            {"text": "X企业", "x0": 80, "x1": 140, "top": 10},
            {"text": "项目名称", "x0": 0, "x1": 40, "top": 30},
            {"text": "测试项目", "x0": 80, "x1": 120, "top": 30},
        ])
        sheets = read_pdf("x.pdf", pdf_open=_opener(page))
        self.assertEqual(sheets[0].name, "正文")
        self.assertEqual(sheets[0].grid, [["单位名称", "X企业"],
                                          ["项目名称", "测试项目"]])

    def test_single_cell_row_with_colon_splits(self):
        page = FakePage(text=LONG_TEXT, words=[
            {"text": "姓名：张三", "x0": 0, "x1": 60, "top": 10},
            {"text": "备注：无", "x0": 0, "x1": 60, "top": 30},
        ])
        sheet = read_pdf("x.pdf", pdf_open=_opener(page))[0]
        self.assertEqual(sheet.grid, [["姓名", "张三"], ["备注", "无"]])

    def test_pages_merged_into_one_sheet(self):
        pages = [FakePage(text=LONG_TEXT, tables=[[["a", "b"]]]),
                 FakePage(text=LONG_TEXT, tables=[[["c", "d"]]])]
        sheets = read_pdf("x.pdf", pdf_open=_opener(*pages))
        self.assertEqual([s.name for s in sheets], ["表1"])
        self.assertEqual(sheets[0].grid, [["a", "b"], ["c", "d"]])


class PageMergeTest(unittest.TestCase):
    """跨页的同一张表按页序拼成一个 sheet，列数取各页最大值。"""

    def test_pages_padded_to_widest(self):
        pages = [
            FakePage(text=LONG_TEXT, tables=[[["表头1", "表头2", "表头3", "表头4", "表头5"],
                                              ["a", "b", "c", "d", "e"]]]),
            FakePage(text=LONG_TEXT, tables=[[["f", "g", "h", "i"]]]),
        ]
        sheets = read_pdf("x.pdf", pdf_open=_opener(*pages))
        self.assertEqual([s.name for s in sheets], ["表1"])
        self.assertEqual(sheets[0].max_col, 5)
        self.assertEqual(sheets[0].grid[2], ["f", "g", "h", "i", None])

    def test_widest_page_wins_without_truncation(self):
        pages = [
            FakePage(text=LONG_TEXT, tables=[[["a", "b"]]]),
            FakePage(text=LONG_TEXT, tables=[[["c", "d", "e", "f"]]]),
        ]
        sheets = read_pdf("x.pdf", pdf_open=_opener(*pages))
        self.assertEqual(sheets[0].max_col, 4)
        self.assertEqual(sheets[0].grid, [["a", "b", None, None],
                                          ["c", "d", "e", "f"]])

    def test_different_table_kinds_stay_separate(self):
        # 同一页上的表1、表2 是两张表，不互相拼接
        page = FakePage(text=LONG_TEXT, tables=[
            [["a", "b", "c", "d", "e"]],
            [["f", "g", "h", "i"]],
        ])
        sheets = read_pdf("x.pdf", pdf_open=_opener(page))
        self.assertEqual([s.name for s in sheets], ["表1", "表2"])
        self.assertEqual([s.max_col for s in sheets], [5, 4])

    def test_kinds_merged_independently_by_page_order(self):
        pages = [
            FakePage(text=LONG_TEXT, tables=[
                [["hdr", "v1"]], [["x", "y"]]]),
            FakePage(text=LONG_TEXT, tables=[
                [["hdr2", "v2"]], [["z", "w"]]]),
        ]
        sheets = read_pdf("x.pdf", pdf_open=_opener(*pages))
        self.assertEqual([s.name for s in sheets], ["表1", "表2"])
        self.assertEqual(sheets[0].grid, [["hdr", "v1"], ["hdr2", "v2"]])
        self.assertEqual(sheets[1].grid, [["x", "y"], ["z", "w"]])


class ScanPageTest(unittest.TestCase):
    def _caller(self, reply, captured=None):
        def caller(messages, api_key, timeout=30, **kwargs):
            if captured is not None:
                captured.update(messages=messages, api_key=api_key,
                                timeout=timeout, **kwargs)
            return reply
        return caller

    def test_scanned_page_uses_vision_and_data_url(self):
        captured = {}
        page = FakePage(text="")   # 没有文字层 → 扫描页
        reply = json.dumps({"rows": [
            ["单位名称", "X企业"],
            ["项目名称", "测试"],
            [""],
        ]}, ensure_ascii=False)
        sheets = read_pdf(
            "x.pdf", pdf_open=_opener(page),
            vision=VisionConfig(api_key="k", model="gpt-4o"),
            caller=self._caller(reply, captured))

        self.assertEqual(sheets[0].name, "扫描")
        self.assertEqual(sheets[0].grid, [["单位名称", "X企业"],
                                          ["项目名称", "测试"]])
        self.assertEqual(captured["api_key"], "k")
        self.assertEqual(captured["model"], "gpt-4o")
        dumped = json.dumps(captured["messages"], ensure_ascii=False)
        self.assertIn("data:image/jpeg;base64,", dumped)
        self.assertEqual(page.image_calls, 1)
        self.assertEqual(page.resolution, 150)

    def test_scanned_pages_merged_across_pages(self):
        replies = iter([
            json.dumps({"rows": [["a", "b"]]}, ensure_ascii=False),
            json.dumps({"rows": [["c", "d", "e"]]}, ensure_ascii=False),
        ])

        def caller(messages, api_key, timeout=30, **kwargs):
            return next(replies)

        pages = [FakePage(text=""), FakePage(text="")]
        sheets = read_pdf("x.pdf", pdf_open=_opener(*pages),
                          vision=VisionConfig(api_key="k"), caller=caller)
        self.assertEqual([s.name for s in sheets], ["扫描"])
        self.assertEqual(sheets[0].grid, [["a", "b", None],
                                          ["c", "d", "e"]])

    def test_scanned_page_without_key_raises_friendly_error(self):
        page = FakePage(text="")
        with self.assertRaises(PdfScanError) as ctx:
            read_pdf("x.pdf", pdf_open=_opener(page), vision=None)
        self.assertIn("视觉模型", str(ctx.exception))

    def test_scanned_page_with_empty_key_raises(self):
        page = FakePage(text="")
        with self.assertRaises(PdfScanError):
            read_pdf("x.pdf", pdf_open=_opener(page),
                     vision=VisionConfig(api_key=""),
                     caller=self._caller('{"rows": []}'))

    def test_ai_error_wrapped(self):
        def caller(messages, api_key, timeout=30, **kwargs):
            raise AiScanError("模型不支持图片输入")
        page = FakePage(text="")
        with self.assertRaises(PdfScanError) as ctx:
            read_pdf("x.pdf", pdf_open=_opener(page),
                     vision=VisionConfig(api_key="k"), caller=caller)
        self.assertIn("模型不支持图片输入", str(ctx.exception))

    def test_unparseable_reply_raises(self):
        page = FakePage(text="")
        with self.assertRaises(PdfScanError):
            read_pdf("x.pdf", pdf_open=_opener(page),
                     vision=VisionConfig(api_key="k"),
                     caller=self._caller("not json"))


class ErrorAndCancelTest(unittest.TestCase):
    def test_encrypted_pdf_friendly_error(self):
        def opener(_path):
            raise PDFPasswordIncorrect("password required")
        with self.assertRaises(PdfScanError) as ctx:
            read_pdf("x.pdf", pdf_open=opener)
        self.assertIn("加密", str(ctx.exception))

    def test_corrupt_pdf_friendly_error(self):
        def opener(_path):
            raise ValueError("bad pdf")
        with self.assertRaises(PdfScanError) as ctx:
            read_pdf("x.pdf", pdf_open=opener)
        self.assertIn("无法读取 PDF", str(ctx.exception))

    def test_cancel_returns_parsed_sheets(self):
        pages = [FakePage(text=LONG_TEXT, tables=[[["a", "b"]]]),
                 FakePage(text=LONG_TEXT, tables=[[["c", "d"]]])]
        calls = {"n": 0}

        def cancel():
            calls["n"] += 1
            return calls["n"] > 1

        sheets = read_pdf("x.pdf", pdf_open=_opener(*pages), cancel_cb=cancel)
        self.assertEqual([s.name for s in sheets], ["表1"])

    def test_progress_callback(self):
        pages = [FakePage(text=LONG_TEXT, tables=[[["a"]]]),
                 FakePage(text=LONG_TEXT, tables=[[["b"]]])]
        seen = []
        read_pdf("x.pdf", pdf_open=_opener(*pages),
                 progress_cb=lambda d, t: seen.append((d, t)))
        self.assertEqual(seen, [(1, 2), (2, 2)])


if __name__ == "__main__":
    unittest.main()

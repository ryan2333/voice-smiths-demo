import unittest

from backend.text import decode_novel_bytes


class TextDecodingTests(unittest.TestCase):
    def test_auto_detects_unicode_and_chinese_encodings(self) -> None:
        for encoding in ("utf-8", "utf-8-sig", "utf-16", "gbk", "gb18030"):
            with self.subTest(encoding=encoding):
                self.assertEqual(decode_novel_bytes("第一章\n中文对白".encode(encoding))[0], "第一章\n中文对白")

    def test_manual_encoding_corrects_ambiguous_bytes(self) -> None:
        self.assertEqual(decode_novel_bytes("漏".encode("gbk"), "gb18030")[0], "漏")
        self.assertEqual(decode_novel_bytes("第一章".encode("big5"), "big5")[0], "第一章")
        for encoding in ("utf-16le", "utf-16be"):
            self.assertEqual(decode_novel_bytes("第一章".encode(encoding), encoding)[0], "第一章")

    def test_truncated_bytes_and_unsupported_encodings_raise_errors(self) -> None:
        for data, encoding in ((b"\xb5", "auto"), (b"\xff\xfe\x2c", "auto"), (b"\xb5", "utf-8"),
                               ("中文".encode("utf-32"), "auto"), (b"test", "unknown")):
            with self.subTest(encoding=encoding):
                with self.assertRaises(ValueError):
                    decode_novel_bytes(data, encoding)

    def test_empty_file_and_explicit_replacement_character(self) -> None:
        self.assertEqual(decode_novel_bytes(b"")[0], "")
        self.assertEqual(decode_novel_bytes("原文中的�".encode("utf-8"))[0], "原文中的�")

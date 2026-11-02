from __future__ import annotations


ENCODINGS = {"utf-8", "gb18030", "gbk", "gb2312", "big5", "utf-16le", "utf-16be"}


def decode_novel_bytes(data: bytes, encoding: str = "auto") -> tuple[str, str]:
    if encoding != "auto":
        if encoding not in ENCODINGS:
            raise ValueError("不支持的文件编码")
        try:
            return data.decode(encoding).lstrip("\ufeff"), encoding
        except UnicodeDecodeError as exc:
            raise ValueError("文件无法按所选编码读取，请更换编码后重试") from exc
    if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        raise ValueError("暂不支持 UTF-32，请另存为 UTF-8 后导入")
    for signature, codec, label in (
        (b"\xef\xbb\xbf", "utf-8-sig", "utf-8"),
        (b"\xff\xfe", "utf-16", "utf-16le"),
        (b"\xfe\xff", "utf-16", "utf-16be"),
    ):
        if data.startswith(signature):
            try:
                return data.decode(codec), label
            except UnicodeDecodeError as exc:
                raise ValueError("文件内容与编码标记不符，请检查文件是否完整") from exc
    for candidate in ("utf-8", "gb18030"):
        try:
            return data.decode(candidate), candidate
        except UnicodeDecodeError:
            continue
    raise ValueError("无法自动识别文件编码，请手动选择编码后重试")

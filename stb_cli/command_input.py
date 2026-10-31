"""Strict UTF-8 Base64 input; decoded commands use the same text validation."""
import base64
import binascii

MAX_COMMAND_BYTES = 65536
MAX_BASE64_CHARS = 4 * ((MAX_COMMAND_BYTES + 2) // 3)


def decode_command(payload):
    if not payload or len(payload) > MAX_BASE64_CHARS:
        raise RuntimeError("Base64 输入为空或超过命令长度限制")
    try:
        raw = base64.b64decode(payload, validate=True)
        # Reject noncanonical padding/unused bits as well as whitespace.
        if base64.b64encode(raw).decode("ascii") != payload:
            raise ValueError("noncanonical Base64")
        text = raw.decode("utf-8")
    except (ValueError, binascii.Error, UnicodeError) as error:
        raise RuntimeError("需要无折行的标准 Base64，解码内容必须是 UTF-8") from error
    return validate_command(text)


def validate_command(text):
    if not text.strip() or len(text.encode("utf-8")) > MAX_COMMAND_BYTES:
        raise RuntimeError("输入须非空，且最多 65536 UTF-8 字节")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise RuntimeError("仅支持无控制字符的单行文本，不添加首尾换行")
    return text

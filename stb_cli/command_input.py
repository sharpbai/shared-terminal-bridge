"""Strict UTF-8 Base64 input; decoded commands use the same text validation."""
import base64
import binascii
import hashlib
import hmac
import re

MAX_COMMAND_BYTES = 65536
MAX_BASE64_CHARS = 4 * ((MAX_COMMAND_BYTES + 2) // 3)


def _decode_base64(payload):
    if not payload or len(payload) > MAX_BASE64_CHARS:
        raise RuntimeError("Base64 输入为空或超过命令长度限制")
    try:
        raw = base64.b64decode(payload, validate=True)
        # Reject noncanonical padding/unused bits as well as whitespace.
        if base64.b64encode(raw).decode("ascii") != payload:
            raise ValueError("noncanonical Base64")
        return raw
    except (ValueError, binascii.Error, UnicodeError) as error:
        raise RuntimeError("需要无折行的标准 Base64，编码须规范") from error

def _decode_text(raw):
    try:
        return validate_command(raw.decode("utf-8"))
    except UnicodeError as error:
        raise RuntimeError("Base64 解码内容必须是 UTF-8") from error


def decode_command(payload):
    return _decode_text(_decode_base64(payload))


def decode_chunks(values):
    *chunks, digest = values
    if not chunks or not re.fullmatch(r"[0-9a-f]{16}", digest):
        raise RuntimeError("需要 Base64 分段和末尾 16 位小写十六进制摘要")
    if len(chunks) > (MAX_COMMAND_BYTES + 71) // 72:
        raise RuntimeError("Base64 分段超过命令长度限制")
    data = bytearray()
    for index, chunk in enumerate(chunks):
        if len(chunk) > 96:
            raise RuntimeError("Base64 分段最多 96 字符")
        raw = _decode_base64(chunk)
        if index < len(chunks) - 1 and len(raw) != 72:
            raise RuntimeError("除末段外，每个 Base64 分段须解码为 72 字节")
        data.extend(raw)
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest()[:16], digest):
        raise RuntimeError("Base64 分段摘要不匹配，命令未提交")
    return _decode_text(data)


def validate_command(text):
    if not text.strip() or len(text.encode("utf-8")) > MAX_COMMAND_BYTES:
        raise RuntimeError("输入须非空，且最多 65536 UTF-8 字节")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise RuntimeError("仅支持无控制字符的单行文本，不添加首尾换行")
    return text

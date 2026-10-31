"""Text and Base64 preserve UTF-8 bytes and reject malformed input."""
import base64
import unittest
from stb_cli.command_input import decode_command, validate_command

class EncodedCommandInputTest(unittest.TestCase):
    def test_syntax_and_boundaries_are_preserved(self):
        for text in ["  printf '%s\\n' \"$HOME\" '中文'  ", "x" * 65536, "中" * 21845]:
            payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
            self.assertEqual(decode_command(payload), text)
            self.assertEqual(validate_command(text), text)

    def test_invalid_base64_and_decoded_content_fail(self):
        for text in ["", " ", "one\ntwo", "echo\r", "a\t", "\x03", "\x7f", "x" * 65537, "中" * 22000]:
            payload = base64.b64encode(text.encode()).decode()
            with self.subTest(text=text[:20]), self.assertRaises(RuntimeError):
                decode_command(payload)
        for payload in ["!!!!", "YQ", "YQ==\n", "YQ===", "YR==", "_w==", "/w==", "中文"]:
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                decode_command(payload)

import base64
import hashlib
import unittest

from stb_cli.command_input import decode_chunks, decode_command

class SegmentedBase64Test(unittest.TestCase):
    def test_valid_and_corrupted_chunks(self):
        raw = ("echo " + "x" * 66 + "中文").encode()
        parts = [base64.b64encode(raw[i:i+72]).decode() for i in range(0, len(raw), 72)]
        digest = hashlib.sha256(raw).hexdigest()[:16]
        self.assertEqual(decode_chunks([*parts, digest]), raw.decode())
        self.assertEqual(decode_command(base64.b64encode(raw).decode()), raw.decode())
        for values in ([parts[0], digest], [*parts, "0" * 16],
                       [parts[0], parts[1] + " ", digest], [digest]):
            with self.subTest(values=values), self.assertRaises(RuntimeError):
                decode_chunks(values)

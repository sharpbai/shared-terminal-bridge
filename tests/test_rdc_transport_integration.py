"""Optional sibling contract: raw CLI -> real Unix socket -> Core; no tmux."""
import base64
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from bridge.common import BridgeError
from tests.context_support import bridge_fixture
from tests.test_command_transport import COMMANDS

ADAPTER = Path(__file__).resolve().parents[2] / "shared-terminal-bridge-rdc"


@unittest.skipUnless((ADAPTER / "stb_rdc").is_dir(), "requires sibling RDC checkout")
class RdcCoreContractTest(unittest.TestCase):
    @contextlib.contextmanager
    def server(self, lose_run_response=False):
        sys.path.insert(0, str(ADAPTER))
        from stb_rdc.client import BridgeClient
        core = bridge_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                listener.bind(str(path))
            except PermissionError:
                listener.close()
                self.skipTest("Unix socket requires host execution")
            listener.listen()
            listener.settimeout(.1)
            stop, errors = threading.Event(), []
            def respond():
                while not stop.is_set():
                    try:
                        connection, _ = listener.accept()
                    except socket.timeout:
                        continue
                    try:
                        with connection, connection.makefile("r", encoding="utf-8") as reader:
                            request = json.loads(reader.readline())
                            method = request["method"]
                            if method == "bridge_info":
                                result = dict(run_auto_request_id=True, input_auto_request_id=True)
                            elif method == "terminal_session_resolve":
                                result = {"name": "test", "pane": "%0"}
                            else:
                                result = core.dispatch(method, request["params"])
                            if not (lose_run_response and method == "terminal_run"):
                                connection.sendall((json.dumps({"ok": True, "result": result}) + "\n").encode())
                    except Exception as error:
                        errors.append(error)
            worker = threading.Thread(target=respond, daemon=True)
            worker.start()
            try:
                yield core, BridgeClient(path)
            finally:
                stop.set()
                worker.join(2)
                listener.close()
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])

    def test_raw_and_direct_preserve_mcp_command_corpus(self):
        sys.path.insert(0, str(ADAPTER))
        from stb_rdc.cli import run
        for text in COMMANDS:
            for mode in ("direct", "base64"):
                with self.subTest(mode=mode, text=text), self.server() as (core, client):
                    options = ["--text", text] if mode == "direct" else ["--base64", base64.b64encode(text.encode()).decode()]
                    with patch("sys.stdin", io.StringIO(text + "\n")):
                        result = run(["run", "test", *options, "--wait-ms", "1"], client)
                    self.assertTrue(result["job_id"])
                    self.assertEqual(core.tmux.typed, [("%0", text)])

    def test_lost_response_never_automatically_replays_run(self):
        with self.server(lose_run_response=True) as (core, client):
            from stb_rdc.cli import run
            from stb_rdc.client import BridgeError as TransportError
            with self.assertRaises(TransportError):
                run(["run", "test", "--text", "echo once", "--wait-ms", "1"], client)
            self.assertEqual(core.tmux.typed, [("%0", "echo once")])
            job_id = next(iter(core.jobs))
            result = client.call("terminal_job_status", {"job_id": job_id})
            self.assertEqual(result["job_id"], job_id)
            self.assertEqual(len(core.jobs), 1)

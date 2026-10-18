"""Optional sibling-repo contract: real JSONL + Unix socket + Core admission.

Standalone Core CI skips this; co-checkout validation runs it explicitly.
No real daemon, RDC service or tmux is used.
"""

import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

from bridge.common import BridgeError
from tests.context_support import bridge_fixture
from tests.test_command_transport import COMMANDS

ADAPTER = Path(__file__).resolve().parents[2] / "shared-terminal-bridge-rdc"


@unittest.skipUnless((ADAPTER / "stb_rdc").is_dir(), "requires sibling RDC checkout")
class RdcCoreContractTest(unittest.TestCase):
    def test_run_response_loss_retries_observation_not_execution(self):
        sys.path.insert(0, str(ADAPTER))
        from stb_rdc.client import BridgeClient
        from stb_rdc.stdio import serve
        core = bridge_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                listener.bind(str(path))
            except PermissionError:
                listener.close()
                self.skipTest("Unix socket requires host execution")
            listener.listen()
            listener.settimeout(5)
            errors = []
            def respond():
                try:
                    for index in range(4):
                        connection, _ = listener.accept()
                        with connection, connection.makefile("r", encoding="utf-8") as reader:
                            request = json.loads(reader.readline())
                            if request["method"] == "bridge_info":
                                result = {"command_request_dedup": "durable-submit-v1",
                                          "model_tasks": "job-authority-v2",
                                          "terminal_run": "receipt-scoped-run-v1"}
                            else:
                                result = core.dispatch(request["method"], request["params"])
                            if index != 1:
                                connection.sendall((json.dumps({"ok": True, "result": result}) + "\n").encode())
                except Exception as error:
                    errors.append(error)
            task = threading.Thread(target=respond, daemon=True)
            task.start()
            output = io.StringIO()
            frame = dict(id="run-loss", op="run", params=dict(
                pane="%0", text=COMMANDS[0], wait_ms=1))
            for _ in range(2):
                serve(io.StringIO(json.dumps(frame) + "\n"), output, BridgeClient(path))
            task.join(6)
            listener.close()
            self.assertFalse(task.is_alive())
            self.assertEqual(errors, [])
            results = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertFalse(results[0]["ok"])
            self.assertTrue(results[1]["ok"], results)
            self.assertEqual(core.tmux.typed, [("%0", COMMANDS[0])])
            self.assertEqual(len(core.jobs), 1)

    def test_fragmented_stdin_real_socket_and_core_match_mcp_corpus(self):
        sys.path.insert(0, str(ADAPTER))
        from stb_rdc.client import BridgeClient
        from stb_rdc.stdio import serve
        for text in COMMANDS + ["echo one\necho two", "\x03"]:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                core = bridge_fixture()
                path = Path(directory) / "control.sock"
                listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    listener.bind(str(path))
                except PermissionError:
                    listener.close()
                    self.skipTest("Unix socket requires host execution")
                listener.listen()
                errors = []

                def respond():
                    try:
                        for index in range(4):  # capability + submit, then identical retry
                            connection, _ = listener.accept()
                            with connection, connection.makefile("r", encoding="utf-8") as reader:
                                request = json.loads(reader.readline())
                                if request["method"] == "bridge_info":
                                    response = {"ok": True, "result": {"command_request_dedup": "durable-submit-v1",
                                        "model_tasks": "job-authority-v2",
                                        "terminal_run": "receipt-scoped-run-v1"}}
                                else:
                                    try:
                                        response = {"ok": True, "result": core.dispatch(
                                            request["method"], request["params"])}
                                    except BridgeError as error:
                                        response = error.response()
                                if index != 1:
                                    # First submit reaches Core but its response is lost.
                                    connection.sendall((json.dumps(response) + "\n").encode())
                    except Exception as error:
                        errors.append(error)

                worker = threading.Thread(target=respond, daemon=True)
                worker.start()
                # Pipe delivers one JSON frame in two writes, as RDC may do.
                import os
                read_fd, write_fd = os.pipe()
                frame = json.dumps(dict(id="rdc-1", op="run", params=dict(
                    pane="%0", wait_ms=1, text=text))) + "\n"
                def feed():
                    with os.fdopen(write_fd, "w") as writer:
                        writer.write(frame[:17])
                        writer.flush()
                        writer.write(frame[17:])
                feeder = threading.Thread(target=feed)
                feeder.start()
                output = io.StringIO()
                with os.fdopen(read_fd, "r") as reader:
                    serve(reader, output, BridgeClient(path))
                feeder.join(2)
                # Retry uses a fresh one-shot receiver, retaining the logical ID.
                serve(io.StringIO(frame), output, BridgeClient(path))
                worker.join(2)
                listener.close()
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                responses = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertFalse(responses[0]["ok"])
                self.assertEqual(responses[0]["error"]["code"], "STB_EMPTY_RESPONSE")
                response = responses[1]
                if "\n" in text or "\x03" in text:
                    self.assertFalse(response["ok"])
                    self.assertEqual(core.tmux.typed, [])
                else:
                    self.assertTrue(response["ok"], response)
                    self.assertEqual(core.tmux.typed, [("%0", text)])

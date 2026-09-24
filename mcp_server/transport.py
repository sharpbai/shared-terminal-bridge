"""Unix-socket transport primitives for the MCP adapter."""

import json
import pathlib
import socket

class MCPError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

class BridgeClient:
    def __init__(self, socket_path):
        self.socket_path = pathlib.Path(socket_path)

    def call(self, method, params):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.connect(str(self.socket_path))
            with client:
                writer = client.makefile("w", encoding="utf-8")
                reader = client.makefile("r", encoding="utf-8")
                writer.write(
                    json.dumps(
                        {"method": method, "params": params},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                writer.flush()
                line = reader.readline()
        except OSError as error:
            return {
                "ok": False,
                "error": {
                    "code": "BRIDGE_UNAVAILABLE",
                    "message": str(error),
                },
            }
        if not line:
            return {
                "ok": False,
                "error": {"code": "BRIDGE_EMPTY_RESPONSE"},
            }
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": {"code": "BRIDGE_INVALID_RESPONSE"},
            }

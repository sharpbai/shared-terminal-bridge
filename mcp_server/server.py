#!/usr/bin/env python3
"""Dependency-free MCP stdio adapter for the local Bridge Unix socket."""

import argparse
import json
import pathlib
import socket
import sys


SERVER_INFO = {
    "name": "shared-terminal-bridge",
    "version": "0.1.0",
    "description": "Local, human-first tmux observation and leased actions",
}
MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"
SUPPORTED_VERSIONS = [MODERN_VERSION, LEGACY_VERSION]
SERVER_INFO_META = "io.modelcontextprotocol/serverInfo"
PROTOCOL_VERSION_META = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities"


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


def object_schema(properties=None, required=None):
    schema = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


PANE = {"type": "string", "pattern": r"^%[0-9]+$"}
GENERATION = {"type": "integer", "minimum": 1}

OBSERVATION_TOOLS = [
    {
        "name": "terminal_list",
        "title": "List tmux panes",
        "description": (
            "List pane identity and authorization metadata. This never returns "
            "terminal contents for unauthorized panes."
        ),
        "inputSchema": object_schema(),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "get_active_pane",
        "title": "Resolve a tmux client's active pane",
        "description": (
            "Resolve the active pane for one explicit tmux client. Unknown "
            "clients fail closed and no global-current-pane fallback is used."
        ),
        "inputSchema": object_schema(
            {"client": {"type": "string", "minLength": 1}},
            ["client"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_read",
        "title": "Read bounded pane history",
        "description": (
            "Read bounded history from an explicitly authorized pane. The "
            "Bridge enforces the pane ACL before capture-pane."
        ),
        "inputSchema": object_schema(
            {
                "pane": PANE,
                "lines": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5000,
                    "default": 100,
                },
            },
            ["pane"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_state",
        "title": "Read pane state",
        "description": (
            "Read bounded tmux state for an explicitly authorized pane, "
            "including cwd and current command."
        ),
        "inputSchema": object_schema({"pane": PANE}, ["pane"]),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]

ACTION_TOOLS = [
    {
        "name": "terminal_type",
        "title": "Type text under an execution lease",
        "description": (
            "Type literal text into an authorized pane. Requires a generation "
            "created out-of-band by explicit authorization; this MCP server "
            "cannot acquire a lease."
        ),
        "inputSchema": object_schema(
            {"pane": PANE, "generation": GENERATION, "text": {"type": "string"}},
            ["pane", "generation", "text"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "terminal_key",
        "title": "Send one key under an execution lease",
        "description": (
            "Send one tmux key name to an authorized pane using a valid "
            "out-of-band execution lease generation."
        ),
        "inputSchema": object_schema(
            {
                "pane": PANE,
                "generation": GENERATION,
                "key": {"type": "string", "minLength": 1},
            },
            ["pane", "generation", "key"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "terminal_interrupt",
        "title": "Send Agent Ctrl+C under an execution lease",
        "description": (
            "Send Agent-originated Ctrl+C to an authorized pane. Requires a "
            "valid generation and does not impersonate a Human Event."
        ),
        "inputSchema": object_schema(
            {"pane": PANE, "generation": GENERATION},
            ["pane", "generation"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": True,
        },
    },
]

SESSION_TOOLS = [
    {
        "name": "terminal_session_list",
        "title": "List managed tmux sessions",
        "description": (
            "List only tmux sessions carrying the Shared Terminal managed "
            "marker. Ordinary user sessions are excluded."
        ),
        "inputSchema": object_schema(),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_session_create",
        "title": "Create a managed interactive tmux session",
        "description": (
            "Create a marked managed tmux session and authorize its initial "
            "pane in the Bridge ACL. Returns the session name and pane ID for "
            "the user-facing stb enter command."
        ),
        "inputSchema": object_schema(
            {
                "name": {
                    "type": "string",
                    "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$",
                },
                "cwd": {"type": "string", "minLength": 1},
            },
            ["name", "cwd"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    },
    {
        "name": "terminal_session_stop",
        "title": "Stop a managed tmux session",
        "description": (
            "Stop only a session carrying the managed marker, remove its pane "
            "from the dynamic ACL, and revoke any active lease."
        ),
        "inputSchema": object_schema(
            {"name": {"type": "string", "minLength": 1}},
            ["name"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": False,
        },
    },
]


class MinimalMCPServer:
    def __init__(
        self,
        bridge,
        enable_actions=False,
        enable_session_management=False,
    ):
        self.bridge = bridge
        self.enable_actions = enable_actions
        self.legacy_initialized = False
        self.tools = list(OBSERVATION_TOOLS)
        if enable_actions:
            self.tools.extend(ACTION_TOOLS)
        if enable_session_management:
            self.tools.extend(SESSION_TOOLS)
        self.tool_by_name = {tool["name"]: tool for tool in self.tools}

    @staticmethod
    def response_meta():
        return {SERVER_INFO_META: SERVER_INFO}

    def validate_modern_request(self, request):
        params = request.get("params") or {}
        meta = params.get("_meta") or {}
        requested = meta.get(PROTOCOL_VERSION_META)
        if requested is None:
            return False
        if requested != MODERN_VERSION:
            raise MCPError(
                -32022,
                "Unsupported protocol version",
                {"supported": SUPPORTED_VERSIONS, "requested": requested},
            )
        if not isinstance(meta.get(CLIENT_CAPABILITIES_META), dict):
            raise MCPError(-32602, "Missing modern client capabilities metadata")
        return True

    def discover(self):
        return {
            "supportedVersions": SUPPORTED_VERSIONS,
            "capabilities": {"tools": {"listChanged": False}},
            "instructions": (
                "Observation tools are pane-ACL constrained. Action tools, "
                "when enabled, require an externally issued execution lease."
            ),
            "ttlMs": 300000,
            "cacheScope": "private",
            "_meta": self.response_meta(),
        }

    def initialize(self, params):
        requested = params.get("protocolVersion")
        if requested not in SUPPORTED_VERSIONS:
            selected = LEGACY_VERSION
        else:
            selected = requested
        if selected == MODERN_VERSION:
            raise MCPError(
                -32022,
                "Modern MCP uses server/discover, not initialize",
                {"supported": SUPPORTED_VERSIONS, "requested": requested},
            )
        self.legacy_initialized = True
        return {
            "protocolVersion": selected,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "Observation is read-only and pane-ACL constrained. Actions "
                "are absent unless explicitly enabled at server startup."
            ),
        }

    def list_tools(self, modern):
        result = {"tools": self.tools}
        if modern:
            result.update(
                {
                    "resultType": "complete",
                    "ttlMs": 300000,
                    "cacheScope": "private",
                    "_meta": self.response_meta(),
                }
            )
        return result

    @staticmethod
    def validate_arguments(tool, arguments):
        if not isinstance(arguments, dict):
            raise MCPError(-32602, "Tool arguments must be an object")
        schema = tool["inputSchema"]
        properties = schema["properties"]
        unknown = sorted(set(arguments) - set(properties))
        missing = sorted(set(schema.get("required", [])) - set(arguments))
        if unknown or missing:
            raise MCPError(
                -32602,
                "Invalid tool arguments",
                {"unknown": unknown, "missing": missing},
            )
        for name, value in arguments.items():
            expected = properties[name].get("type")
            if expected == "string" and not isinstance(value, str):
                raise MCPError(-32602, f"{name} must be a string")
            if expected == "integer" and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                raise MCPError(-32602, f"{name} must be an integer")
        pane = arguments.get("pane")
        if pane is not None and (
            not pane.startswith("%") or not pane[1:].isdigit()
        ):
            raise MCPError(-32602, "pane must be a stable tmux pane ID")
        lines = arguments.get("lines")
        if lines is not None and not 1 <= lines <= 5000:
            raise MCPError(-32602, "lines must be between 1 and 5000")
        generation = arguments.get("generation")
        if generation is not None and generation < 1:
            raise MCPError(-32602, "generation must be positive")
        for name in ("client", "key", "name", "cwd"):
            if name in arguments and not arguments[name]:
                raise MCPError(-32602, f"{name} must not be empty")

    def call_tool(self, params, modern):
        name = params.get("name")
        tool = self.tool_by_name.get(name)
        if tool is None:
            raise MCPError(-32602, f"Unknown or disabled tool: {name}")
        arguments = params.get("arguments") or {}
        self.validate_arguments(tool, arguments)
        bridge_response = self.bridge.call(name, arguments)
        is_error = not bridge_response.get("ok", False)
        result = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(bridge_response, ensure_ascii=False),
                }
            ],
            "structuredContent": bridge_response,
            "isError": is_error,
        }
        if modern:
            result["resultType"] = "complete"
            result["_meta"] = self.response_meta()
        return result

    def dispatch(self, request):
        if request.get("jsonrpc") != "2.0" or not isinstance(
            request.get("method"), str
        ):
            raise MCPError(-32600, "Invalid Request")
        method = request["method"]
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise MCPError(-32602, "params must be an object")
        if method == "server/discover":
            self.validate_modern_request(request)
            return self.discover()
        if method == "initialize":
            return self.initialize(params)
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None
        modern = self.validate_modern_request(request)
        if not modern and not self.legacy_initialized:
            raise MCPError(-32002, "Server is not initialized")
        if method == "ping":
            return {}
        if method == "tools/list":
            return self.list_tools(modern)
        if method == "tools/call":
            return self.call_tool(params, modern)
        raise MCPError(-32601, "Method not found", {"method": method})

    def handle(self, request):
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            result = self.dispatch(request)
            if request_id is None or result is None:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except MCPError as error:
            if request_id is None:
                return None
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": error.code, "message": error.message},
            }
            if error.data is not None:
                payload["error"]["data"] = error.data
            return payload

    def run_stdio(self, input_stream=sys.stdin, output_stream=sys.stdout):
        for line in input_stream:
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("request must be an object")
                response = self.handle(request)
            except (json.JSONDecodeError, ValueError) as error:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": str(error)},
                }
            if response is not None:
                output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
                output_stream.flush()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bridge-socket",
        type=pathlib.Path,
        default=pathlib.Path("/tmp/shared-terminal-bridge.sock"),
    )
    parser.add_argument(
        "--enable-actions",
        action="store_true",
        help="register leased action tools; lease acquisition stays out-of-band",
    )
    parser.add_argument(
        "--enable-session-management",
        action="store_true",
        help="register managed tmux session create/list/stop tools",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    server = MinimalMCPServer(
        BridgeClient(args.bridge_socket),
        enable_actions=args.enable_actions,
        enable_session_management=args.enable_session_management,
    )
    server.run_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

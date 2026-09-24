"""Tool validation, Bridge forwarding, and session authority."""

import json
import uuid

from mcp_server.config import (
    REQUIRES_BRIDGE_V2, REQUIRES_BRIDGE_V3, REQUIRES_BRIDGE_V4,
    REQUIRES_BRIDGE_V5, REQUIRES_BRIDGE_V6, REQUIRES_BRIDGE_V7,
    REQUIRES_BRIDGE_V8, REQUIRES_BRIDGE_V9,
)
from mcp_server.transport import MCPError

class ToolCallService:
    def __init__(self, server):
        self.server = server

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
            if expected == "boolean" and not isinstance(value, bool):
                raise MCPError(-32602, f"{name} must be a boolean")
            if expected == "array" and not isinstance(value, list):
                raise MCPError(-32602, f"{name} must be an array")
        pane = arguments.get("pane")
        if pane is not None and (
            not pane.startswith("%") or not pane[1:].isdigit()
        ):
            raise MCPError(-32602, "pane must be a stable tmux pane ID")
        lines = arguments.get("lines")
        if lines is not None and not 1 <= lines <= 5000:
            raise MCPError(-32602, "lines must be between 1 and 5000")
        max_bytes = arguments.get("max_bytes")
        if max_bytes is not None and not 1 <= max_bytes <= 65536:
            raise MCPError(-32602, "max_bytes must be between 1 and 65536")
        max_lines = arguments.get("max_lines")
        if max_lines is not None and not 1 <= max_lines <= 1000:
            raise MCPError(-32602, "max_lines must be between 1 and 1000")
        commands = arguments.get("commands")
        if commands is not None and (
            not 1 <= len(commands) <= 32
            or any(not isinstance(command, str) or not command for command in commands)
        ):
            raise MCPError(-32602, "commands must contain 1 to 32 non-empty strings")
        steps = arguments.get("steps")
        if steps is not None and (
            not isinstance(steps, list)
            or not 1 <= len(steps) <= 8
            or any(
                not isinstance(step, dict)
                or not isinstance(step.get("text"), str)
                or not step.get("text")
                for step in steps
            )
        ):
            raise MCPError(-32602, "steps must contain 1 to 8 objects with non-empty text")
        generation = arguments.get("generation")
        if generation is not None and generation < 1:
            raise MCPError(-32602, "generation must be positive")
        for name in ("client", "key", "name", "cwd", "cursor", "block_id"):
            if name in arguments and not arguments[name]:
                raise MCPError(-32602, f"{name} must not be empty")

    def call_tool(self, params, modern, request_id=None):
        name = params.get("name")
        compatibility = self.server.refresh_bridge_compatibility()
        tool = self.server.tool_by_name.get(name)
        if tool is None:
            if (
                name in (REQUIRES_BRIDGE_V2 | REQUIRES_BRIDGE_V3 | REQUIRES_BRIDGE_V4 | REQUIRES_BRIDGE_V5 | REQUIRES_BRIDGE_V6 | REQUIRES_BRIDGE_V7 | REQUIRES_BRIDGE_V8 | REQUIRES_BRIDGE_V9)
                and compatibility.get("status") in ("legacy", "restart_required")
            ):
                bridge_response = {
                    "ok": False,
                    "error": {
                        "code": "BRIDGE_RESTART_REQUIRED",
                        "method": name,
                        "message": compatibility.get("message", "Running Bridge API is too old."),
                    },
                }
                return self.server.tool_result(bridge_response, modern)
            raise MCPError(-32602, f"Unknown or disabled tool: {name}")
        arguments = params.get("arguments") or {}
        self.server.validate_arguments(tool, arguments)
        if name == "terminal_session_acquire":
            bridge_response = self.server.acquire_session(arguments["name"])
        elif name == "terminal_wait_job":
            wait_id = f"wait_{uuid.uuid4().hex[:12]}"
            with self.server.request_lock:
                self.server.request_wait_ids[request_id] = wait_id
                cancelled_early = request_id in self.server.cancelled_requests
                self.server.cancelled_requests.discard(request_id)
            if cancelled_early:
                self.server.bridge.call("terminal_cancel_wait", {"wait_id": wait_id})
            try:
                bridge_response = self.server.bridge.call(
                    "terminal_wait_job", {**arguments, "wait_id": wait_id}
                )
            finally:
                with self.server.request_lock:
                    self.server.request_wait_ids.pop(request_id, None)
        else:
            bridge_method = (
                "execution_status"
                if name == "terminal_execution_status"
                else name
            )
            bridge_response = self.server.bridge.call(bridge_method, arguments)
        if (
            name in (REQUIRES_BRIDGE_V2 | REQUIRES_BRIDGE_V3 | REQUIRES_BRIDGE_V4 | REQUIRES_BRIDGE_V5 | REQUIRES_BRIDGE_V6 | REQUIRES_BRIDGE_V7 | REQUIRES_BRIDGE_V8 | REQUIRES_BRIDGE_V9)
            and bridge_response.get("error", {}).get("code") == "METHOD_NOT_FOUND"
        ):
            bridge_response = {
                "ok": False,
                "error": {
                    "code": "BRIDGE_RESTART_REQUIRED",
                    "method": name,
                    "message": "Restart the local daemon: stb daemon stop && stb daemon start",
                },
            }
        return self.server.tool_result(bridge_response, modern)

    def tool_result(self, bridge_response, modern):
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
            interaction = bridge_response.get("result", {}).get("interaction")
            result["resultType"] = (
                "inputRequired" if interaction == "input_required" else "complete"
            )
            result["_meta"] = self.server.response_meta()
        return result

    def acquire_session(self, name):
        turn = self.server.turn_resolver.current()
        if turn is None:
            return {
                "ok": False,
                "error": {
                    "code": "CODEX_TURN_ID_UNAVAILABLE",
                    "message": (
                        "No verified Codex user turn is available; lease was not issued."
                    ),
                },
            }
        compatibility = self.server.refresh_bridge_compatibility()
        if compatibility.get("api_version", 3) >= 3:
            resolved = self.server.bridge.call("terminal_session_resolve", {"name": name})
            if not resolved.get("ok", False):
                return resolved
            session = resolved.get("result", {})
        else:
            sessions_response = self.server.bridge.call("terminal_session_list", {})
            if not sessions_response.get("ok", False):
                return sessions_response
            session = next(
                (
                    item
                    for item in sessions_response.get("result", {}).get("sessions", [])
                    if item.get("name") == name
                ),
                None,
            )
            if session is None:
                return {
                    "ok": False,
                    "error": {"code": "SESSION_NOT_MANAGED", "session": name},
                }
        pane = session.get("pane")
        if pane in self.server.acquired_panes:
            status = self.server.bridge.call("execution_status", {"pane": pane})
            if not status.get("ok", False):
                return status
            lease = status.get("result", {}).get("lease")
            if lease and lease.get("state") == "ACTIVE":
                authorization = lease.get("authorization") or {}
                if authorization.get("turn_id") == turn.get("turn_id"):
                    return {
                        "ok": False,
                        "error": {
                            "code": "EXECUTION_LEASE_ALREADY_ACTIVE",
                            "session": name,
                            "pane": pane,
                            "generation": lease.get("generation"),
                        },
                    }
        response = self.server.bridge.call(
            "acquire_execution",
            {"pane": pane, **turn},
        )
        if response.get("ok", False):
            self.server.acquired_panes[pane] = response.get("result", {}).get(
                "generation"
            )
            response.setdefault("result", {})["session"] = name
        return response

    def cancel_request(self, request_id):
        with self.server.request_lock:
            wait_id = self.server.request_wait_ids.get(request_id)
        if wait_id is None:
            with self.server.request_lock:
                self.server.cancelled_requests.add(request_id)
            return False
        self.server.bridge.call("terminal_cancel_wait", {"wait_id": wait_id})
        return True

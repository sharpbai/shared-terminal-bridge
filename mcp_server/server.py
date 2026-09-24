#!/usr/bin/env python3
"""Dependency-free MCP stdio adapter for the local Bridge Unix socket."""

import argparse
import pathlib
import sys
import threading

if __package__ in (None, ""):  # Direct execution: ./mcp_server/server.py
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


from mcp_server.config import *  # noqa: F403 - compatibility re-exports


try:
    from mcp_server.transport import BridgeClient, MCPError
    from mcp_server.turn_context import CodexTurnResolver
    from mcp_server.runtime.compatibility import CompatibilityService
    from mcp_server.runtime.protocol import ProtocolService
    from mcp_server.runtime.stdio import StdioService
    from mcp_server.runtime.tool_calls import ToolCallService
    from mcp_server.service import ServerMethod
    from mcp_server.tool_catalog import (
        ACTION_TOOLS,
        GENERATION,
        JOB_TOOLS,
        OBSERVATION_TOOLS,
        PANE,
        SESSION_TOOLS,
        object_schema,
    )
except ModuleNotFoundError:  # Direct execution: ./mcp_server/server.py
    from transport import BridgeClient, MCPError
    from turn_context import CodexTurnResolver
    from runtime.compatibility import CompatibilityService
    from runtime.protocol import ProtocolService
    from runtime.stdio import StdioService
    from runtime.tool_calls import ToolCallService
    from service import ServerMethod
    from tool_catalog import (
        ACTION_TOOLS,
        GENERATION,
        JOB_TOOLS,
        OBSERVATION_TOOLS,
        PANE,
        SESSION_TOOLS,
        object_schema,
    )


class MinimalMCPServer:
    _component_types = {
        "compatibility": CompatibilityService,
        "protocol": ProtocolService,
        "tool_calls": ToolCallService,
        "stdio": StdioService,
    }

    def _component(self, name):
        cache = self.__dict__.setdefault("_component_cache", {})
        if name not in cache:
            cache[name] = self._component_types[name](self)
        return cache[name]

    refresh_bridge_compatibility = ServerMethod("compatibility")

    response_meta = ServerMethod("protocol")
    validate_modern_request = ServerMethod("protocol")
    discover = ServerMethod("protocol")
    initialize = ServerMethod("protocol")
    list_tools = ServerMethod("protocol")

    validate_arguments = ServerMethod("tool_calls")
    call_tool = ServerMethod("tool_calls")
    tool_result = ServerMethod("tool_calls")
    acquire_session = ServerMethod("tool_calls")
    cancel_request = ServerMethod("tool_calls")

    dispatch = ServerMethod("stdio")
    handle = ServerMethod("stdio")
    run_stdio = ServerMethod("stdio")

    def __init__(
        self,
        bridge,
        enable_actions=False,
        enable_session_management=False,
        turn_resolver=None,
    ):
        self.bridge = bridge
        self.enable_actions = enable_actions
        self.acquired_panes = {}
        self.turn_resolver = turn_resolver or CodexTurnResolver()
        self.legacy_initialized = False
        self.tools = list(OBSERVATION_TOOLS)
        if enable_actions:
            self.tools.extend(ACTION_TOOLS)
            self.tools.extend(JOB_TOOLS)
        if enable_session_management:
            self.tools.extend(SESSION_TOOLS)
        self.declared_tools = list(self.tools)
        self.declared_tool_by_name = {
            tool["name"]: tool for tool in self.declared_tools
        }
        self.tool_by_name = dict(self.declared_tool_by_name)
        self.bridge_compatibility = None
        self.request_wait_ids = {}
        self.cancelled_requests = set()
        self.request_lock = threading.RLock()


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

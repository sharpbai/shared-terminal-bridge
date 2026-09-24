"""Bridge API feature detection and MCP tool visibility."""

from mcp_server.config import (
    REQUIRES_BRIDGE_V2, REQUIRES_BRIDGE_V3, REQUIRES_BRIDGE_V4,
    REQUIRES_BRIDGE_V5, REQUIRES_BRIDGE_V6, REQUIRES_BRIDGE_V7,
    REQUIRES_BRIDGE_V8, REQUIRES_BRIDGE_V9,
)

class CompatibilityService:
    def __init__(self, server):
        self.server = server

    def refresh_bridge_compatibility(self):
        """Publish only tools supported by the currently running daemon."""
        if self.server.bridge_compatibility is not None:
            return self.server.bridge_compatibility
        response = self.server.bridge.call("bridge_info", {})
        if response.get("ok", False):
            info = response.get("result", {})
            api_version = info.get("api_version")
            if isinstance(api_version, int):
                self.server.bridge_compatibility = {
                    "status": "compatible" if api_version >= 3 else (
                        "upgrade_available" if api_version == 2 else "legacy"
                    ),
                    "api_version": api_version,
                    "version": info.get("version"),
                }
        elif response.get("error", {}).get("code") == "METHOD_NOT_FOUND":
            self.server.bridge_compatibility = {
                "status": "restart_required",
                "api_version": 1,
                "message": (
                    "The running Bridge daemon predates this MCP server. "
                    "Restart it with: stb daemon stop && stb daemon start"
                ),
            }
        if self.server.bridge_compatibility is None:
            # Unknown/fake/unavailable bridges retain discovery compatibility;
            # the actual call will still fail closed.
            self.server.bridge_compatibility = {"status": "unknown"}
        api_version = self.server.bridge_compatibility.get("api_version")
        if isinstance(api_version, int):
            self.server.tools = [
                tool
                for tool in self.server.declared_tools
                if not (
                    (api_version < 2 and tool["name"] in REQUIRES_BRIDGE_V2)
                    or (api_version < 3 and tool["name"] in REQUIRES_BRIDGE_V3)
                    or (api_version < 4 and tool["name"] in REQUIRES_BRIDGE_V4)
                    or (api_version < 5 and tool["name"] in REQUIRES_BRIDGE_V5)
                    or (api_version < 6 and tool["name"] in REQUIRES_BRIDGE_V6)
                    or (api_version < 7 and tool["name"] in REQUIRES_BRIDGE_V7)
                    or (api_version < 8 and tool["name"] in REQUIRES_BRIDGE_V8)
                    or (api_version < 9 and tool["name"] in REQUIRES_BRIDGE_V9)
                )
            ]
        else:
            self.server.tools = list(self.server.declared_tools)
        self.server.tool_by_name = {tool["name"]: tool for tool in self.server.tools}
        return self.server.bridge_compatibility

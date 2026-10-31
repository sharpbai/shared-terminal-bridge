"""Initialization and cheap model discovery for the task-only interface."""
from mcp_server.config import (
    CLIENT_CAPABILITIES_META, LEGACY_VERSION, MODERN_VERSION,
    PROTOCOL_VERSION_META, SERVER_INFO, SERVER_INFO_META, SUPPORTED_VERSIONS,
)
from mcp_server.transport import MCPError

from bridge.agent_instructions import INSTRUCTIONS


class ProtocolService:
    def __init__(self, server):
        self.server = server

    @staticmethod
    def response_meta():
        return {SERVER_INFO_META: SERVER_INFO}

    def validate_modern_request(self, request):
        meta = (request.get("params") or {}).get("_meta") or {}
        requested = meta.get(PROTOCOL_VERSION_META)
        if requested is None:
            return False
        if requested != MODERN_VERSION:
            raise MCPError(-32022, "Unsupported protocol version",
                           {"supported": SUPPORTED_VERSIONS, "requested": requested})
        if not isinstance(meta.get(CLIENT_CAPABILITIES_META), dict):
            raise MCPError(-32602, "Missing modern client capabilities metadata")
        return True

    def discover(self):
        return {"supportedVersions": SUPPORTED_VERSIONS,
                "capabilities": {"tools": {"listChanged": False}},
                "instructions": INSTRUCTIONS, "ttlMs": 300000, "cacheScope": "private",
                "bridgeCompatibility": self.server.refresh_bridge_compatibility(),
                "_meta": self.server.response_meta()}

    def initialize(self, params):
        requested = params.get("protocolVersion")
        selected = requested if requested in SUPPORTED_VERSIONS else LEGACY_VERSION
        if selected == MODERN_VERSION:
            raise MCPError(-32022, "Modern MCP uses server/discover, not initialize",
                           {"supported": SUPPORTED_VERSIONS, "requested": requested})
        self.server.legacy_initialized = True
        return {"protocolVersion": selected, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}

    def list_tools(self, modern):
        compatibility = self.server.refresh_bridge_compatibility()
        result = {"tools": self.server.tools}
        if modern:
            result.update(resultType="complete", ttlMs=300000, cacheScope="private",
                          _meta=self.server.response_meta(), bridgeCompatibility=compatibility)
        return result

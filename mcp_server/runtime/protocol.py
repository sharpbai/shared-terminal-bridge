"""Initialization and cheap model discovery for the task-only interface."""
from mcp_server.config import (
    CLIENT_CAPABILITIES_META, LEGACY_VERSION, MODERN_VERSION,
    PROTOCOL_VERSION_META, SERVER_INFO, SERVER_INFO_META, SUPPORTED_VERSIONS,
)
from mcp_server.transport import MCPError

INSTRUCTIONS = (
    "Self-discovery is the entrypoint: these instructions and tools/list schemas "
    "are sufficient for normal work; no local skill or repository document read is required. "
    "STB-RDC exclusive-mode contract: RDC is transport/bootstrap only; independent "
    "target-host capabilities require explicit one-shot bypass and human bypass approval; "
    "never bypass Human Override, pane ACL or risk approvals. If a needed capability is "
    "missing, fail closed; broad continue is not bypass permission. "
    "Observe exact named managed sessions; list only when the name is unknown. "
    "For execution use terminal_run with pane, unique request_id and command. "
    "Core handles authority and waits, normally up to 600000 ms. Never manage internal "
    "authority counters or call removed acquire/submit tools. "
    "Same ID retries observe the original job, never reexecute. Use terminal_wait_job "
    "only to continue observing, terminal_input_job to reply to a running program, and "
    "terminal_interrupt_job for Agent Ctrl+C. Job IDs cannot target newer work. "
    "Human Ctrl+C stops that chain; a genuinely new run is authorized by local receipt "
    "order. Do not replay queued steps. Canceling a wait does not stop the job. "
    "High-risk operations still require human confirmation. high_io/full_scan returns "
    "an approval request: show exact command and impact, end the turn, then after a "
    "later explicit approval use terminal_approve_request and a new run ID. "
    "STRATEGY_REVIEW_REQUIRED means compare alternatives; HUMAN_DECISION_REQUIRED "
    "does not authorize automatic interruption. Never inject target scripts, markers, "
    "TTY changes or hidden environment probes. "
    "Use bounded output/deltas, don't re-read after a complete run result. For known "
    "TUI programs prefer terminal_program_profile and their CLI; otherwise ask for "
    "human assistance before costly Agent-driven TUI operation. "
    "Disable pagers for command output: use git --no-pager ... or GIT_PAGER=cat, "
    "and systemctl --no-pager ... to avoid getting stuck at (END). "
    "Bound output where practical; do not change global target configuration."
)


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

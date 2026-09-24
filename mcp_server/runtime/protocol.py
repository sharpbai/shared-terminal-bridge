"""MCP initialization, discovery, and protocol metadata."""

from mcp_server.config import (
    CLIENT_CAPABILITIES_META, LEGACY_VERSION, MODERN_VERSION,
    PROTOCOL_VERSION_META, SERVER_INFO, SERVER_INFO_META, SUPPORTED_VERSIONS,
)
from mcp_server.transport import MCPError

class ProtocolService:
    def __init__(self, server):
        self.server = server

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
        compatibility = self.server.refresh_bridge_compatibility()
        return {
            "supportedVersions": SUPPORTED_VERSIONS,
            "capabilities": {"tools": {"listChanged": False}},
            "instructions": (
                "STB-RDC exclusive-mode contract: when the user selected STB-RDC, "
                "treat any companion Remote Desktop Commander as transport/bootstrap only. "
                "Independent RDC target-host capabilities require explicit one-shot bypass "
                "approval and must never bypass Human Override, lease, ACL, or long-run controls. "
                "For an exact managed session name, use the name-based tools "
                "directly; do not list sessions first. Observation tools "
                "are pane-ACL constrained and never require an execution lease. "
                "For requests that only inspect existing history or state, use "
                "terminal_read_delta/terminal_read/terminal_state without "
                "terminal_session_acquire. Only when new terminal input is "
                "required, call terminal_session_acquire once for the selected "
                "managed session, then submit every command visibly and "
                "separately with terminal_submit. For its returned job_id, "
                "prefer terminal_wait_job: it waits locally up to 10 minutes "
                "in one call without repeated short model waits. On completion "
                "it returns bounded output for that command, so do not add a "
                "terminal_job_status call unless explicit diagnostics are needed. Its default "
                "600000 ms should normally be left unchanged. On "
                "STRATEGY_REVIEW_REQUIRED "
                "compare alternative approaches and wait again only if justified. "
                "HUMAN_DECISION_REQUIRED never authorizes "
                "automatic interruption. "
                "Commands expected to exceed 120 seconds or marked high_io/"
                "full_scan must first call terminal_long_run_request, show its "
                "exact command and impact, and end the turn. A later explicit "
                "user approval can call terminal_long_run_approve with the "
                "request ID, but must acquire the new user turn's lease before "
                "calling approve; never require the user to retype the command. "
                "terminal_task_block is optional local "
                "planning metadata only and never executes its command list. "
                "For 2-8 independent, simple read-only commands whose next "
                "steps do not require semantic judgment, prefer "
                "terminal_task_block_execute. It is intentionally conservative "
                "and stops on Human Ctrl+C, interaction, assertion failure, or "
                "lease change. "
                "Before operating a known full-screen terminal program, call "
                "terminal_program_profile and prefer its CLI/CMD/batch interface. "
                "If no adequate non-interactive path exists, tell the human the "
                "target checkpoint, end the turn, and observe once after they reach it. "
                "Agent-driven TUI keys are a last resort; avoid one-key/one-read loops. "
                "Batch independent lightweight read-only probes into one visible "
                "shell command line to reduce model round trips; keep mutations, "
                "dependent steps, and verification boundaries separate. "
                "Prefer terminal_read_delta over terminal_read and always pass "
                "its latest cursor. Never guess "
                "or reuse a generation from terminal history. If terminal_read "
                "reports human_override=true, or an action reports a revoked "
                "lease, read available output at most once and immediately "
                "finish the current user turn. Never reacquire in that turn. "
                "A later user message requesting more work authorizes a fresh "
                "terminal_session_acquire, including in the same Codex task."
            ),
            "ttlMs": 300000,
            "cacheScope": "private",
            "bridgeCompatibility": compatibility,
            "_meta": self.server.response_meta(),
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
        self.server.legacy_initialized = True
        return {
            "protocolVersion": selected,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "When STB-RDC is selected, RDC is transport/bootstrap only; independent "
                "RDC target-host capabilities require explicit one-shot human bypass approval. "
                "Use exact managed session names directly; list only when the "
                "name is missing or ambiguous. Observation does not require a "
                "lease. Before the first actual write call "
                "terminal_session_acquire; never guess a generation. If a "
                "human override is reported, read once and immediately return "
                "to the user without more writes or reacquisition. A later user "
                "message may acquire a fresh generation."
            ),
        }

    def list_tools(self, modern):
        compatibility = self.server.refresh_bridge_compatibility()
        result = {"tools": self.server.tools}
        if modern:
            result.update(
                {
                    "resultType": "complete",
                    "ttlMs": 300000,
                    "cacheScope": "private",
                    "_meta": self.server.response_meta(),
                    "bridgeCompatibility": compatibility,
                }
            )
        return result

"""MCP protocol versions, server metadata, and Bridge feature gates."""

from bridge.config import BRIDGE_VERSION

SERVER_INFO = {
    "name": "shared-terminal-bridge",
    "version": BRIDGE_VERSION,
    "description": "Local, human-first tmux observation and leased actions",
}
MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"
SUPPORTED_VERSIONS = [MODERN_VERSION, LEGACY_VERSION]
SERVER_INFO_META = "io.modelcontextprotocol/serverInfo"
PROTOCOL_VERSION_META = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities"
REQUIRES_BRIDGE_V2 = {
    "terminal_read_delta", "terminal_task_block", "terminal_task_observe",
}
REQUIRES_BRIDGE_V3 = {
    "terminal_wait_delta", "terminal_long_run_approve",
    "terminal_session_read_delta", "terminal_session_wait_delta",
    "terminal_session_state",
}
REQUIRES_BRIDGE_V4 = {"terminal_long_run_request"}
REQUIRES_BRIDGE_V5 = {"terminal_job_list", "terminal_job_status"}
REQUIRES_BRIDGE_V6 = {"terminal_wait_job"}
REQUIRES_BRIDGE_V7 = {"terminal_history"}
REQUIRES_BRIDGE_V8 = {"terminal_task_block_execute"}
REQUIRES_BRIDGE_V9 = {"terminal_program_profile"}

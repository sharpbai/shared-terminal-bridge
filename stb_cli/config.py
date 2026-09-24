"""Paths and tmux formats used by the STB command-line client."""

import pathlib

DEFAULT_BRIDGE_SOCKET = pathlib.Path("/tmp/shared-terminal-bridge.sock")
DEFAULT_EVENT_SOCKET = pathlib.Path("/tmp/shared-terminal-events.sock")
DEFAULT_STATE_FILE = pathlib.Path("/tmp/shared-terminal-bridge-state.json")
DEFAULT_PID_FILE = pathlib.Path("/tmp/shared-terminal-bridge.pid")
DEFAULT_LOG_FILE = pathlib.Path("/tmp/shared-terminal-bridge.log")
DEFAULT_HISTORY_FILE = pathlib.Path.home() / ".local/state/shared-terminal-bridge/history.jsonl"
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE_SCRIPT = PROJECT_ROOT / "bridge" / "local_bridge.py"
SESSION_FORMAT = "\t".join([
    "#{session_name}", "#{session_id}", "#{session_windows}",
    "#{session_attached}", "#{@shared_terminal_managed}",
    "#{@shared_terminal_id}", "#{@shared_terminal_created_at}",
    "#{history_limit}", "#{mouse}",
])

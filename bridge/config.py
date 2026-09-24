"""Central configuration and static capability data for the Bridge."""

import pathlib

MAX_LINES = 5000
CONTEXT_CAPTURE_LINES = 5000
JOB_CAPTURE_LINES = 1000
MAX_RETAINED_JOBS = 128
MANAGED_HISTORY_LIMIT = 100000
DEFAULT_CONTROL_SOCKET = pathlib.Path("/tmp/shared-terminal-bridge.sock")
DEFAULT_EVENT_SOCKET = pathlib.Path("/tmp/shared-terminal-events.sock")
DEFAULT_STATE_FILE = pathlib.Path("/tmp/shared-terminal-bridge-state.json")
DEFAULT_HISTORY_FILE = pathlib.Path.home() / ".local/state/shared-terminal-bridge/history.jsonl"
BRIDGE_API_VERSION = 9
BRIDGE_VERSION = "0.15.0"
DEFAULT_WAIT_MS = 10_000
DEFAULT_IDLE_BUDGET_MS = 30_000
DEFAULT_TOTAL_BUDGET_MS = 60_000
MAX_WAIT_MS = 30_000
MAX_TOTAL_BUDGET_MS = 600_000
LONG_RUN_APPROVAL_MS = 120_000
HIGH_RESOURCE_CLASSES = {"high_io", "full_scan"}
LONG_RUN_REQUEST_TTL_MS = 60 * 60 * 1000
MAX_JOB_WAIT_MS = 600_000
JOB_POLL_INTERVAL_SECONDS = 0.5
JOB_PROMPT_STABLE_MS = 1_500
REMOTE_TRANSPORT_COMMANDS = {"ssh", "mosh", "telnet"}
JOB_TERMINAL_STATES = {
    "COMPLETED",
    "INTERRUPTED_BY_HUMAN",
    "NEEDS_ATTENTION",
    "HUMAN_DECISION_REQUIRED",
}
TASK_BLOCK_MAX_STEPS = 8
TASK_BLOCK_MAX_DURATION_MS = 120_000
READ_ONLY_COMMANDS = {
    "blkid", "cat", "cut", "date", "df", "du", "fdisk", "file", "findmnt", "free", "grep",
    "head", "hostname", "id", "iostat", "journalctl", "ls", "lsblk", "lscpu",
    "lsmod", "lsof", "pgrep", "ps", "pwd", "qemu-img", "qemu-nbd", "sort", "stat", "systemctl",
    "tail", "test", "testdisk", "uname", "uptime", "virsh", "vmstat", "wc", "whoami",
}

# Guidance only: installed versions and supported arguments must still be
# verified. Keeping this local avoids probing or modifying the target shell.
PROGRAM_CAPABILITY_PROFILES = {
    "testdisk": {
        "program": "testdisk",
        "preferred_interface": "cmd",
        "safe_probe": "testdisk /version",
        "interfaces": ["/cmd scripted commands", "interactive TUI"],
        "guidance": [
            "Prefer the official /cmd interface for repeatable analysis or listing.",
            "For selective recovery, confirm that the installed version and filesystem support the required scripted operation.",
            "If scripting is insufficient, ask the human to navigate to a named TUI checkpoint, then observe once.",
        ],
        "tui_policy": "human_assisted",
        "references": ["https://www.cgsecurity.org/testdisk_doc/scripted_run.html"],
    },
    "photorec": {
        "program": "photorec",
        "preferred_interface": "cmd",
        "safe_probe": "photorec /version",
        "interfaces": ["/cmd scripted commands", "/d output directory", "interactive TUI"],
        "guidance": [
            "Prefer /cmd and fileopt/search for repeatable recovery runs.",
            "Treat recovery as a write-producing, potentially high-I/O long run requiring explicit approval.",
            "Use human-assisted TUI only when scripting cannot express the selection.",
        ],
        "tui_policy": "human_assisted",
        "references": ["https://www.cgsecurity.org/testdisk_doc/photorec.html"],
    },
}
READ_ONLY_SUBCOMMANDS = {
    "qemu-img": {"info", "measure", "map"},
    "virsh": {
        "capabilities", "domblkinfo", "domblklist", "domifaddr", "domiflist",
        "dominfo", "domstate", "dumpxml", "list", "nodeinfo", "pool-info",
        "pool-list", "snapshot-list", "version", "vol-info", "vol-list",
    },
    "systemctl": {
        "is-active", "is-enabled", "is-failed", "list-dependencies",
        "list-unit-files", "list-units", "show", "status",
    },
}

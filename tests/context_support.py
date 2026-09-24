#!/usr/bin/env python3
"""Bridge-level tests for cursor observations and terminal task blocks."""

import pathlib
import sys
import tempfile
import threading
import types
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bridge.local_bridge import BridgeError, LocalBridge, TmuxBackend, unix_ms  # noqa: E402


class FakeTmux:
    socket_name = "test"

    def __init__(self):
        self.content = "prompt$ "
        self.typed = []
        self.keys = []
        self.current_command = "zsh"

    def read(self, pane, lines):
        return self.content

    def send_text(self, pane, text):
        self.typed.append((pane, text))

    def send_key(self, pane, key):
        self.keys.append((pane, key))

    def state(self, pane):
        return {"current_command": self.current_command}


def bridge_fixture():
    bridge = LocalBridge.__new__(LocalBridge)
    bridge.tmux = FakeTmux()
    bridge.allowed_panes = {"%0"}
    bridge.leases = {"%0": {"pane": "%0", "generation": 1, "state": "ACTIVE"}}
    bridge.observation_cursors = {}
    bridge.managed_sessions = {}
    bridge.task_blocks = {}
    bridge.long_run_requests = {}
    bridge.long_run_approvals = {}
    bridge.jobs = {}
    bridge.wait_handles = {}
    bridge.cancelled_wait_ids = set()
    bridge.interrupt_sources = {}
    bridge.audit = []
    bridge.history_file = None
    bridge.lock = threading.RLock()
    bridge.persist_state = lambda: None
    bridge._notify_job = lambda job: None
    return bridge

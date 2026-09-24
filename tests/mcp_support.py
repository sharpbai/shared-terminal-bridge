#!/usr/bin/env python3
"""Protocol and safety tests for the minimal MCP adapter."""

import io
import datetime
import json
import pathlib
import sys
import tempfile
import threading
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server.server import (  # noqa: E402
    CLIENT_CAPABILITIES_META,
    CodexTurnResolver,
    MODERN_VERSION,
    PROTOCOL_VERSION_META,
    MinimalMCPServer,
)


class FakeBridge:
    def __init__(self, response=None):
        self.response = response or {"ok": True, "result": {"panes": []}}
        self.calls = []

    def call(self, method, params):
        if method == "bridge_info":
            return {
                "ok": True,
                "result": {"api_version": 2, "version": "test"},
            }
        self.calls.append((method, params))
        return self.response


class FakeBridgeV3(FakeBridge):
    def call(self, method, params):
        if method == "bridge_info":
            return {"ok": True, "result": {"api_version": 3, "version": "test"}}
        self.calls.append((method, params))
        return self.response


class FakeBridgeV4(FakeBridgeV3):
    def call(self, method, params):
        if method == "bridge_info":
            return {"ok": True, "result": {"api_version": 4, "version": "test"}}
        self.calls.append((method, params))
        return self.response


class FakeBridgeV5(FakeBridgeV4):
    def call(self, method, params):
        if method == "bridge_info":
            return {"ok": True, "result": {"api_version": 5, "version": "test"}}
        self.calls.append((method, params))
        return self.response


class FakeBridgeV6(FakeBridgeV5):
    def call(self, method, params):
        if method == "bridge_info":
            return {"ok": True, "result": {"api_version": 6, "version": "test"}}
        self.calls.append((method, params))
        return self.response


class FakeBridgeV7(FakeBridgeV6):
    def call(self, method, params):
        if method == "bridge_info":
            return {"ok": True, "result": {"api_version": 7, "version": "test"}}
        self.calls.append((method, params))
        return self.response


class FakeBridgeV8(FakeBridgeV7):
    def call(self, method, params):
        if method == "bridge_info":
            return {"ok": True, "result": {"api_version": 8, "version": "test"}}
        self.calls.append((method, params))
        return self.response


class FakeBridgeV9(FakeBridgeV8):
    def call(self, method, params):
        if method == "bridge_info":
            return {"ok": True, "result": {"api_version": 9, "version": "test"}}
        self.calls.append((method, params))
        return self.response


class FakeTurnResolver:
    def __init__(self, turn=1):
        self.turn = turn

    def current(self):
        return {
            "thread_id": "thread-1",
            "turn_id": f"turn-{self.turn}",
            "turn_started_at_ms": 1_000 * self.turn,
        }


def modern_params(**values):
    return {
        **values,
        "_meta": {
            PROTOCOL_VERSION_META: MODERN_VERSION,
            CLIENT_CAPABILITIES_META: {},
        },
    }

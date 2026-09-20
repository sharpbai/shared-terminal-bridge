#!/usr/bin/env python3
"""Regression tests for verified Codex user-turn lease gating."""

import pathlib
import sys
import threading
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bridge.local_bridge import BridgeError, LocalBridge  # noqa: E402


class TurnGateTest(unittest.TestCase):
    def bridge_with_revoked_lease(self):
        bridge = LocalBridge.__new__(LocalBridge)
        bridge.lock = threading.RLock()
        bridge.generations = {"%5": 3}
        bridge.leases = {
            "%5": {
                "pane": "%5",
                "generation": 3,
                "state": "REVOKED",
                "revoked_at_ms": 1500,
                "authorization": {
                    "thread_id": "thread-1",
                    "turn_id": "turn-1",
                    "turn_started_at_ms": 1000,
                },
            }
        }
        bridge.authorize = lambda pane: None
        bridge.persist_state = lambda: None
        bridge.record = lambda *args, **kwargs: None
        return bridge

    def test_same_or_older_turn_is_rejected(self):
        bridge = self.bridge_with_revoked_lease()
        cases = [("turn-1", 2000), ("turn-2", 1400)]
        for turn_id, started_at_ms in cases:
            with self.subTest(turn_id=turn_id, started_at_ms=started_at_ms):
                with self.assertRaises(BridgeError) as raised:
                    bridge.acquire_execution(
                        "%5",
                        thread_id="thread-1",
                        turn_id=turn_id,
                        turn_started_at_ms=started_at_ms,
                    )
                self.assertEqual(raised.exception.code, "NEW_USER_TURN_REQUIRED")

    def test_newer_distinct_user_turn_is_authorized(self):
        bridge = self.bridge_with_revoked_lease()
        lease = bridge.acquire_execution(
            "%5",
            thread_id="thread-1",
            turn_id="turn-2",
            turn_started_at_ms=1600,
        )
        self.assertEqual(lease["generation"], 4)
        self.assertEqual(lease["authorization"]["turn_id"], "turn-2")

    def test_newer_turn_supersedes_active_lease_in_same_thread(self):
        bridge = self.bridge_with_revoked_lease()
        bridge.leases["%5"]["state"] = "ACTIVE"
        records = []
        bridge.record = lambda action, **fields: records.append((action, fields))
        lease = bridge.acquire_execution(
            "%5",
            thread_id="thread-1",
            turn_id="turn-2",
            turn_started_at_ms=2000,
        )
        self.assertEqual(lease["generation"], 4)
        self.assertIn("LEASE_SUPERSEDE", [action for action, _ in records])

    def test_active_lease_cannot_be_stolen_by_other_thread(self):
        bridge = self.bridge_with_revoked_lease()
        bridge.leases["%5"]["state"] = "ACTIVE"
        with self.assertRaises(BridgeError) as raised:
            bridge.acquire_execution(
                "%5",
                thread_id="thread-2",
                turn_id="turn-9",
                turn_started_at_ms=9000,
            )
        self.assertEqual(
            raised.exception.code,
            "EXECUTION_LEASE_ALREADY_ACTIVE",
        )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Focused tests for bridge sessions."""

from tests.context_support import *  # noqa: F401,F403

class ContextBridgeTest(unittest.TestCase):
    def test_managed_session_sets_history_before_creating_initial_pane(self):
        tmux = TmuxBackend("fresh-server")
        calls = []

        def run(*arguments, check=True):
            calls.append(arguments)
            if arguments[0] == "has-session":
                return types.SimpleNamespace(returncode=1, stdout="", stderr="no server")
            if arguments[0] == "display-message" and arguments[-1] == "#{pane_id}":
                return types.SimpleNamespace(returncode=0, stdout="%0\n", stderr="")
            if arguments[0] == "display-message" and arguments[-1] == "#{history_limit}":
                return types.SimpleNamespace(returncode=0, stdout="100000\n", stderr="")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        tmux.run = run
        created = tmux.create_managed_session("verify33", "/tmp")

        bootstrap = next(call for call in calls if call[0] == "start-server")
        self.assertEqual(
            bootstrap,
            (
                "start-server",
                ";",
                "set-option",
                "-g",
                "history-limit",
                "100000",
                ";",
                "new-session",
                "-d",
                "-s",
                "verify33",
                "-c",
                "/tmp",
            ),
        )
        self.assertEqual(created["pane"], "%0")
        self.assertEqual(created["history_limit"], 100000)

    def test_tmux_submit_orders_literal_text_and_enter_in_one_call(self):
        tmux = TmuxBackend("test")
        calls = []
        tmux.run = lambda *args, **kwargs: calls.append(args)

        tmux.submit("%0", "printf ok")

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0],
            (
                "send-keys", "-t", "%0", "-l", "printf ok",
                ";", "send-keys", "-t", "%0", "Enter",
            ),
        )


if __name__ == "__main__":
    unittest.main()

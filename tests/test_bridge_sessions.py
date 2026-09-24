#!/usr/bin/env python3
"""Focused tests for bridge sessions."""

from tests.context_support import *  # noqa: F401,F403

class ContextBridgeTest(unittest.TestCase):
    def test_first_managed_session_starts_server_before_global_options(self):
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

        new_session_index = next(
            index for index, call in enumerate(calls) if call[0] == "new-session"
        )
        global_option_index = next(
            index
            for index, call in enumerate(calls)
            if call[:3] == ("set-option", "-g", "history-limit")
        )
        self.assertLess(new_session_index, global_option_index)
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

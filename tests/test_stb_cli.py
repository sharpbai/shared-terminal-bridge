#!/usr/bin/env python3
"""Command-level tests for stb enter behavior."""

import importlib.machinery
import importlib.util
import os
import pathlib
import subprocess
import unittest
from unittest import mock


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
STB_PATH = PROJECT_ROOT / "bin" / "stb"
loader = importlib.machinery.SourceFileLoader("stb_cli", str(STB_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
stb_cli = importlib.util.module_from_spec(spec)
loader.exec_module(stb_cli)


class STBEnterTest(unittest.TestCase):
    def test_enter_outside_tmux_execs_attach(self):
        with (
            mock.patch.object(stb_cli, "find_session", return_value={"name": "ops"}),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(os, "execvp", side_effect=OSError("stop")) as execvp,
        ):
            with self.assertRaises(OSError):
                stb_cli.enter_session("default", "ops")
        execvp.assert_called_once_with(
            "tmux",
            ["tmux", "-L", "default", "attach-session", "-t", "ops"],
        )

    def test_enter_inside_tmux_switches_client(self):
        completed = subprocess.CompletedProcess([], 0)
        with (
            mock.patch.object(stb_cli, "find_session", return_value={"name": "ops"}),
            mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux/default,1,0"}),
            mock.patch.object(stb_cli, "tmux", return_value=completed) as tmux,
        ):
            stb_cli.enter_session("default", "ops")
        tmux.assert_called_once_with(
            "default",
            "switch-client",
            "-t",
            "ops",
            check=False,
        )


if __name__ == "__main__":
    unittest.main()

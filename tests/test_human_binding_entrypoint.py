"""Binding must launch the CLI entry point, not the relocated service file."""

import pathlib
import unittest
from unittest import mock

from tests.context_support import bridge_fixture


class BindingEntrypointTest(unittest.TestCase):
    def test_install_uses_real_cli_without_overwriting_original_snapshot(self):
        bridge = bridge_fixture()
        bridge.human_binding_installed = False
        bridge.binding_snapshot_taken = False
        bridge.event_socket = pathlib.Path('/tmp/test-events.sock')
        bridge.tmux.get_root_ctrl_c_binding = mock.Mock(return_value='original binding')
        bridge.tmux.install_human_binding = mock.Mock()
        bridge.install_human_binding()
        args = bridge.tmux.install_human_binding.call_args.args
        self.assertEqual(args[1], pathlib.Path(__file__).resolve().parents[1] / 'bridge/local_bridge.py')
        self.assertTrue(args[1].is_file())
        bridge.install_human_binding()
        bridge.tmux.install_human_binding.assert_called_once()
        self.assertEqual(bridge.original_human_binding, 'original binding')

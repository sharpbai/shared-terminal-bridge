"""Agent execution and human maintenance have separate public entrypoints."""
import contextlib
import io
import unittest
from stb_cli.parser import parser as agent_parser
from stb_manage.parser import parser as manage_parser


class CliRoleTest(unittest.TestCase):
    def test_socket_options_only_belong_to_management(self):
        for flag in ('--tmux-socket', '--bridge-socket'):
            self.assertNotIn(flag, agent_parser().format_help())
            self.assertIn(flag, manage_parser().format_help())
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                agent_parser().parse_args([flag, 'custom', 'list'])
        args = manage_parser().parse_args(['--tmux-socket', 'isolated', '--bridge-socket', '/tmp/test.sock', 'list'])
        self.assertEqual(args.tmux_socket, 'isolated')
        self.assertEqual(str(args.bridge_socket), '/tmp/test.sock')
    def test_agent_rejects_management_actions(self):
        for command in ('create', 'enter', 'stop', 'daemon', 'history', 'cleanup-tasks', 'mcp'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                agent_parser().parse_args([command])
        for argv in (['list'], ['info', 'ops'], ['discover', '--json'],
                     ['run', 'ops', '--text', 'pwd'], ['job', 'job-id'],
                     ['wait', 'job-id'], ['interrupt', 'job-id']):
            agent_parser().parse_args(argv)

    def test_management_has_lifecycle_but_not_execution(self):
        for argv in (['list'], ['info', 'ops'], ['create', 'ops'], ['enter', 'ops'],
                     ['stop', 'ops'], ['daemon', 'status'], ['history'], ['cleanup-tasks'], ['mcp']):
            manage_parser().parse_args(argv)
        for command in ('run', 'wait', 'interrupt'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                manage_parser().parse_args([command])

    def test_help_is_separated(self):
        agent = agent_parser().format_help()
        manage = manage_parser().format_help()
        self.assertNotIn('stb-manage', agent)
        self.assertNotIn('cleanup-tasks', agent)
        self.assertIn('cleanup-tasks', manage)
        self.assertIn('stb-manage', manage)

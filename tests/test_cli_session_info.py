"""Info replaces separate pane/job inventories without implying terminal idle."""
import contextlib
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from stb_cli.session_info import session_info
from stb_cli.output import print_session_info
from stb_cli.commands_sessions import handle_session_command
from stb_cli.parser import parser

SESSION = dict(name='test', session_id='$1', pane='%1', windows=2, attached=1,
               managed_id='managed', history_limit=100000, mouse=True, created_at='now')
PANES = '%1\t@1\t0\tbash\t/tmp\n%2\t@2\t0\tssh\t/work\n'


class SessionInfoTest(unittest.TestCase):
    def test_all_windows_and_only_unfinished_jobs_of_this_session(self):
        jobs = [dict(job_id='running', pane='%2', state='RUNNING', execution_phase='EXECUTING', command='not needed'),
                dict(job_id='attention', pane='%1', state='NEEDS_ATTENTION', execution_phase='EXECUTING'),
                dict(job_id='done', pane='%1', state='COMPLETED', execution_phase='FINISHED'),
                dict(job_id='other', pane='%9', state='RUNNING', execution_phase='EXECUTING')]
        args = parser().parse_args(['info', 'test', '--json'])
        with patch('stb_cli.session_info.tmux', return_value=SimpleNamespace(stdout=PANES)) as tmux, \
                patch('stb_cli.session_info.bridge_call', return_value={'jobs': jobs}):
            result = session_info(args, SESSION)
        self.assertIn('-s', tmux.call_args.args)
        self.assertIn('$1', tmux.call_args.args)
        self.assertEqual(len(result['panes']), 2)
        self.assertEqual([j['job_id'] for j in result['current_jobs']], ['running', 'attention'])
        self.assertNotIn('command', result['current_jobs'][0])
        self.assertTrue(result['jobs_available'])

    def test_offline_bridge_preserves_panes_and_reports_unknown_not_idle(self):
        args = parser().parse_args(['info', 'test'])
        with patch('stb_cli.session_info.tmux', return_value=SimpleNamespace(stdout=PANES)), \
                patch('stb_cli.session_info.bridge_call', side_effect=RuntimeError('Bridge offline')):
            result = session_info(args, SESSION)
        self.assertFalse(result['jobs_available'])
        self.assertEqual(len(result['panes']), 2)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            print_session_info(result)
        self.assertIn('不能据此判断终端空闲', output.getvalue())

    def test_info_json_keeps_original_fields_and_new_details(self):
        args = parser().parse_args(['info', 'test', '--json'])
        expected = dict(SESSION, panes=[], current_jobs=[], jobs_available=True)
        output = io.StringIO()
        with patch('stb_cli.commands_sessions._require_session', return_value=SESSION), \
                patch('stb_cli.commands_sessions.session_info', return_value=expected), \
                contextlib.redirect_stdout(output):
            handle_session_command(args)
        self.assertEqual(json.loads(output.getvalue()), expected)

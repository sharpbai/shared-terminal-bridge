import unittest
from stb_cli.task_cleanup import clear_unfinished
from stb_cli.parser import parser


class TaskCleanupTest(unittest.TestCase):
    def test_scoped_cleanup_preserves_history_cache_and_replay_protection(self):
        state = dict(jobs={'a': dict(pane='%1', execution_phase='EXECUTING'),
                           'b': dict(pane='%2', execution_phase='EXECUTING'),
                           'c': dict(pane='%1', execution_phase='FINISHED')},
                     pane_prompts={'%1': {'prompt': 'root@host:~#'}},
                     command_requests={'r': dict(state='RETURNED', fingerprint='keep',
                                                result={'job_id': 'a'})})
        self.assertEqual(clear_unfinished(state, '%1'), ['a'])
        self.assertEqual(set(state['jobs']), {'b', 'c'})
        self.assertIn('%1', state['pane_prompts'])
        self.assertEqual(state['command_requests']['r']['state'], 'REJECTED')
        self.assertEqual(state['command_requests']['r']['fingerprint'], 'keep')
        self.assertEqual(clear_unfinished(state, '%1'), [])

    def test_preview_is_default(self):
        self.assertFalse(parser().parse_args(['cleanup-tasks']).yes)

"""Removing resource approval must not remove actual execution protections."""
import contextlib
import io
import unittest
from bridge.common import BridgeError
from bridge.protocol.registry import METHOD_HANDLERS
from tests.context_support import bridge_fixture
from stb_cli.parser import parser


class NoResourceApprovalTest(unittest.TestCase):
    def test_old_entrypoints_are_removed(self):
        for name in ('terminal_long_run_request', 'terminal_long_run_approve',
                     'terminal_long_run_decide', 'terminal_long_run_requests', 'terminal_approve_request'):
            self.assertNotIn(name, METHOD_HANDLERS)
        for name in ('approve', 'reject', 'approvals'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser().parse_args([name])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser().parse_args(['run', 'test', '--text', 'echo x', '--long-run-approval-id', 'old'])

    def test_resource_run_still_enforces_acl_and_human_override(self):
        core = bridge_fixture()
        core.event_sequence = 0
        with self.assertRaises(BridgeError):
            core.dispatch('terminal_run', dict(pane='%99', text='du /', resource_class='full_scan', wait_ms=1))
        result = core.dispatch('terminal_run', dict(pane='%0', text='du /', resource_class='full_scan', wait_ms=1))
        core.handle_human_event(dict(type='human_interrupt', pane='%0', pre_interrupt_content='busy'))
        with self.assertRaises(BridgeError):
            core.dispatch('terminal_input_job', dict(job_id=result['job_id'], text='yes'))
        self.assertEqual(core.leases['%0']['state'], 'REVOKED')

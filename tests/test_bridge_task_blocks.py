#!/usr/bin/env python3
"""Focused tests for bridge task blocks."""

from tests.context_support import *  # noqa: F401,F403

class ContextBridgeTest(unittest.TestCase):
    def test_task_block_is_local_metadata_and_writes_nothing(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_task_block(
            "%0", 1, ["printf 'alpha\\n'", "printf 'beta\\n'"]
        )
        block_id = submitted["block_id"]
        self.assertEqual(bridge.tmux.typed, [])
        self.assertEqual(bridge.tmux.keys, [])
        self.assertEqual(submitted["transport"], "none")
        self.assertFalse(submitted["writes_to_pane"])
        self.assertTrue(submitted["explicit_submits_required"])
        self.assertEqual(bridge.task_blocks[block_id]["commands"], 2)
        bridge.tmux.content += "\nalpha\nbeta\n"
        observed = bridge.terminal_task_observe(block_id)
        self.assertEqual(observed["state"], "ACTIVE")
        self.assertIsNone(observed["exit_code"])
        self.assertEqual(observed["content"], "alpha\nbeta")

    def test_read_only_task_runner_executes_steps_and_assertions(self):
        bridge = bridge_fixture()
        submitted = []

        def submit(pane, generation, text, expected_duration_ms, resource_class):
            submitted.append(text)
            return {"job_id": f"job-{len(submitted)}"}

        outputs = {
            "job-1": "Filesystem Used\n/dev/x 10G",
            "job-2": "x86_64",
        }
        bridge.terminal_submit = submit
        bridge.terminal_wait_job = lambda job_id, wait_ms: {
            "state": "COMPLETED",
            "completion_confidence": "prompt_returned",
            "output_excerpt": {"content": outputs[job_id]},
        }

        result = bridge.terminal_task_block_execute(
            "%0",
            1,
            [
                {"text": "df -h", "assert": {"contains": "Filesystem"}},
                {"text": "uname -m", "assert": {"regex": "x86_64"}},
            ],
        )

        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(submitted, ["df -h", "uname -m"])
        self.assertTrue(all(step["assertion"]["passed"] for step in result["steps"]))
        self.assertTrue(all(step["output_ref"].startswith("job://") for step in result["steps"]))

    def test_read_only_task_runner_rejects_shell_programs_before_writing(self):
        bridge = bridge_fixture()

        with self.assertRaises(BridgeError) as raised:
            bridge.terminal_task_block_execute(
                "%0", 1, [{"text": "df -h | sort -h"}]
            )

        self.assertEqual(raised.exception.code, "TASK_BLOCK_COMMAND_NOT_READ_ONLY")
        self.assertEqual(bridge.tmux.keys, [])

    def test_read_only_task_runner_rejects_mutating_variants(self):
        bridge = bridge_fixture()
        commands = (
            "sed -i s/a/b/ file",
            "qemu-img check -r all disk.qcow2",
            "systemctl stop ssh status",
            "journalctl --vacuum-time=1s",
        )
        for command in commands:
            with self.subTest(command=command):
                with self.assertRaises(BridgeError) as raised:
                    bridge.terminal_task_block_execute(
                        "%0", 1, [{"text": command}]
                    )
                self.assertEqual(
                    raised.exception.code, "TASK_BLOCK_COMMAND_NOT_READ_ONLY"
                )
        self.assertEqual(bridge.tmux.keys, [])

    def test_recovery_diagnostics_have_exact_read_only_runner_profiles(self):
        allowed = (
            "fdisk -l /dev/sda",
            "blkid -p /dev/sda1",
            "blkid -p -O 33554432 disk.img",
            "testdisk /version",
            "qemu-nbd --version",
        )
        for command in allowed:
            with self.subTest(command=command):
                self.assertTrue(LocalBridge._validate_read_only_command(command))

        denied = (
            "fdisk /dev/sda",
            "blkid /dev/sda1",
            "blkid -p -c cache /dev/sda1",
            "testdisk /dev/sda",
            "qemu-nbd --connect=/dev/nbd0 disk.qcow2",
        )
        for command in denied:
            with self.subTest(command=command):
                with self.assertRaises(BridgeError) as raised:
                    LocalBridge._validate_read_only_command(command)
                self.assertEqual(raised.exception.code, "TASK_BLOCK_COMMAND_NOT_READ_ONLY")

    def test_program_profile_is_local_guidance(self):
        bridge = bridge_fixture()
        listed = bridge.terminal_program_profile()
        self.assertEqual(
            [item["program"] for item in listed["profiles"]],
            ["photorec", "testdisk"],
        )
        profile = bridge.terminal_program_profile("/usr/local/bin/testdisk")
        self.assertEqual(profile["profile"]["preferred_interface"], "cmd")
        self.assertEqual(profile["profile"]["tui_policy"], "human_assisted")
        self.assertEqual(bridge.tmux.typed, [])
        with self.assertRaises(BridgeError) as raised:
            bridge.terminal_program_profile("unknown-tui")
        self.assertEqual(raised.exception.code, "PROGRAM_PROFILE_NOT_FOUND")

    def test_read_only_task_runner_stops_after_human_interrupt(self):
        bridge = bridge_fixture()
        submitted = []

        def submit(pane, generation, text, expected_duration_ms, resource_class):
            submitted.append(text)
            return {"job_id": "job-1"}

        def wait(job_id, wait_ms):
            bridge.leases["%0"].update({"state": "REVOKED", "event_seq": 4})
            return {
                "state": "INTERRUPTED_BY_HUMAN",
                "completion_confidence": "authoritative",
                "output_excerpt": {"content": "partial"},
            }

        bridge.terminal_submit = submit
        bridge.terminal_wait_job = wait
        result = bridge.terminal_task_block_execute(
            "%0", 1, [{"text": "df -h"}, {"text": "uname -m"}]
        )

        self.assertEqual(result["state"], "INTERRUPTED")
        self.assertEqual(submitted, ["df -h"])


if __name__ == "__main__":
    unittest.main()

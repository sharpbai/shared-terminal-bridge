"""Conservative classifier for task-block read-only commands."""

import pathlib
import re
import shlex

from bridge.common import BridgeError
from bridge.config import READ_ONLY_COMMANDS, READ_ONLY_SUBCOMMANDS
from bridge.execution.long_run import LongRunService
from bridge.execution.submit import SubmitService


class ReadOnlyPolicy:
    @staticmethod
    def validate(text: str):
        incomplete = SubmitService._command_completeness(text)
        if incomplete:
            raise BridgeError("COMMAND_INCOMPLETE", reason=incomplete)
        # Runner v1 intentionally accepts one simple command, not shell programs.
        if re.search(r"(?:[;&|<>`]|\$\(|\$\{|\n|\r)", text):
            raise BridgeError(
                "TASK_BLOCK_COMMAND_NOT_READ_ONLY",
                reason="shell control operators, redirection, and expansion are not supported",
                command=LongRunService._history_command(text),
            )
        try:
            tokens = shlex.split(text, posix=True)
        except ValueError as error:
            raise BridgeError("COMMAND_INCOMPLETE", reason=str(error)) from error
        if not tokens:
            raise BridgeError("INVALID_TASK_BLOCK", reason="empty command")
        executable = pathlib.PurePath(tokens[0]).name
        if executable not in READ_ONLY_COMMANDS:
            raise BridgeError(
                "TASK_BLOCK_COMMAND_NOT_READ_ONLY",
                reason="executable is not in the read-only allowlist",
                executable=executable,
            )
        allowed_subcommands = READ_ONLY_SUBCOMMANDS.get(executable)
        if allowed_subcommands:
            subcommand = next((token for token in tokens[1:] if not token.startswith("-")), None)
            if subcommand not in allowed_subcommands:
                raise BridgeError(
                    "TASK_BLOCK_COMMAND_NOT_READ_ONLY",
                    reason="subcommand is not in the read-only allowlist",
                    executable=executable,
                    subcommand=subcommand,
                )
        if executable == "journalctl" and any(
            token == "--rotate"
            or token == "--flush"
            or token == "--sync"
            or token == "--relinquish-var"
            or token.startswith("--vacuum")
            for token in tokens[1:]
        ):
            raise BridgeError(
                "TASK_BLOCK_COMMAND_NOT_READ_ONLY",
                reason="journal mutation option is not allowed",
                executable=executable,
            )
        if executable == "fdisk":
            if len(tokens) != 3 or tokens[1] not in ("-l", "--list"):
                raise BridgeError(
                    "TASK_BLOCK_COMMAND_NOT_READ_ONLY",
                    reason="fdisk Runner only permits: fdisk -l|--list TARGET",
                    executable=executable,
                )
        if executable == "blkid":
            index = 1
            saw_probe = False
            saw_target = False
            while index < len(tokens):
                token = tokens[index]
                if token in ("-p", "--probe"):
                    saw_probe = True
                elif token in ("-O", "--offset"):
                    index += 1
                    if index >= len(tokens) or not tokens[index].isdigit():
                        raise BridgeError(
                            "TASK_BLOCK_COMMAND_NOT_READ_ONLY",
                            reason="blkid offset must be a non-negative integer",
                            executable=executable,
                        )
                elif token.startswith("-") or saw_target:
                    raise BridgeError(
                        "TASK_BLOCK_COMMAND_NOT_READ_ONLY",
                        reason="blkid Runner only permits -p [ -O OFFSET ] TARGET",
                        executable=executable,
                    )
                else:
                    saw_target = True
                index += 1
            if not saw_probe or not saw_target:
                raise BridgeError(
                    "TASK_BLOCK_COMMAND_NOT_READ_ONLY",
                    reason="blkid Runner requires -p and one TARGET",
                    executable=executable,
                )
        if executable == "testdisk" and tokens[1:] not in (
            ["/version"], ["--version"], ["-version"], ["/v"],
        ):
            raise BridgeError(
                "TASK_BLOCK_COMMAND_NOT_READ_ONLY",
                reason="testdisk Runner permits a version probe only",
                executable=executable,
            )
        if executable == "qemu-nbd" and tokens[1:] not in (["--version"], ["-V"]):
            raise BridgeError(
                "TASK_BLOCK_COMMAND_NOT_READ_ONLY",
                reason="qemu-nbd Runner permits a version probe only",
                executable=executable,
            )
        return tokens

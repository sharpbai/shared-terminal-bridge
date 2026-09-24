"""Shared primitives for the local Bridge implementation."""

import datetime
import time


class BridgeError(Exception):
    """Structured error returned by the local Bridge protocol."""

    def __init__(self, code: str, **details):
        super().__init__(code)
        self.code = code
        self.details = details

    def response(self):
        return {"ok": False, "error": {"code": self.code, **self.details}}


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")


def unix_ms() -> int:
    return time.time_ns() // 1_000_000

"""Trusted local receipt order. Never accept request timestamps from callers."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import itertools
import threading
import uuid


EPOCH = uuid.uuid4().hex
_counter = itertools.count(1)
_lock = threading.Lock()
_request = ContextVar('stb_request_receipt', default=None)


@dataclass(frozen=True)
class Receipt:
    epoch: str
    sequence: int

    def as_dict(self):
        return dict(epoch=self.epoch, sequence=self.sequence)


def receive():
    with _lock:
        return Receipt(EPOCH, next(_counter))


def current_request():
    return _request.get()


@contextmanager
def request_scope(receipt=None):
    token = _request.set(receipt if isinstance(receipt, Receipt) else receive())
    try:
        yield _request.get()
    finally:
        _request.reset(token)


def received_after_revocation(lease):
    receipt = current_request()
    if receipt is None:
        return False
    # Successfully restored leases were revoked before this process admitted
    # any calls. Restart revocation is not a Human Event and has no event_seq.
    if lease.get('revoke_reason') == 'daemon_restart':
        return True
    if lease.get('event_seq') is None:
        return False
    revoked = lease.get('revoked_receipt')
    # A successfully restored lease from an older daemon predates this process.
    if not revoked or revoked.get('epoch') != receipt.epoch:
        return True
    return receipt.sequence > revoked['sequence']

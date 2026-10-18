"""Durable submit admission: a logical request is never executed twice.

Reserve before any terminal side effect. A crash between reservation and result
is deliberately ambiguous, not permission to resend. Store a fingerprint rather
than another command copy; original result/error fields retain Core semantics.
"""

import copy
import hashlib
import json

from bridge.common import BridgeError

MAX_REQUESTS = 10000


def submit_once(bridge, params, execute):
    request_id = params.get("request_id")
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        raise BridgeError("INVALID_COMMAND_REQUEST_ID")
    fingerprint = hashlib.sha256(json.dumps(
        params, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    with bridge.lock:
        entries = bridge.__dict__.setdefault("command_requests", {})
        prior = entries.get(request_id)
        if prior:
            if prior["fingerprint"] != fingerprint:
                raise BridgeError("COMMAND_REQUEST_CONFLICT", request_id=request_id)
            bridge.authorize(params["pane"])
            if prior["state"] == "REJECTED":
                raise BridgeError(prior["error"]["code"], **prior["error"]["details"])
            if prior["state"] != "RETURNED":
                raise BridgeError("COMMAND_REQUEST_AMBIGUOUS", request_id=request_id)
            return copy.deepcopy(prior["result"])
        # Never silently evict replay protection; fail closed at capacity.
        if len(entries) >= MAX_REQUESTS:
            raise BridgeError("COMMAND_REQUEST_CAPACITY")
        bridge.authorize(params["pane"])
        entries[request_id] = {"fingerprint": fingerprint, "state": "RESERVED"}
        bridge.persist_state()
        # Release the lock while executing; Human Events must remain responsive.
    try:
        result = execute()
    except BridgeError as error:
        with bridge.lock:
            entries[request_id].update(state="REJECTED", error={
                "code": error.code, "details": error.details})
            bridge.persist_state()
        raise
    with bridge.lock:
        entries[request_id].update(state="RETURNED", result=copy.deepcopy(result))
        bridge.persist_state()
    return result

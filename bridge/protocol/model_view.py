"""Hide internal authority metadata, never alter terminal command/output text."""
INTERNAL_FIELDS = {"generation", "lease_generation", "lease", "authorization",
                   "stream_epoch", "last_stream_seq", "revoked_receipt",
                   "thread_id", "turn_id", "turn_started_at_ms", "event_seq"}


def model_view(value):
    if isinstance(value, dict):
        result = {key: model_view(item) for key, item in value.items() if key not in INTERNAL_FIELDS}
        if isinstance(result.get("code"), str):
            result["code"] = {"EXECUTION_LEASE_INVALID": "JOB_NOT_CURRENT",
                "EXECUTION_LEASE_ALREADY_ACTIVE": "TERMINAL_BUSY"}.get(result["code"], result["code"])
        return result
    if isinstance(value, list):
        return [model_view(item) for item in value]
    return value

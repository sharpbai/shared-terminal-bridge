"""Shared JSON-schema fragments for MCP tool declarations."""

def object_schema(properties=None, required=None):
    schema = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


PANE = {"type": "string", "pattern": r"^%[0-9]+$"}
GENERATION = {"type": "integer", "minimum": 1}

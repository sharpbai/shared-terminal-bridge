"""Compatibility exports for MCP tool schemas.

New code should start at :mod:`mcp_server.tools.registry` and then open only
the relevant feature-domain module under :mod:`mcp_server.tools`.
"""

from mcp_server.tools.common import GENERATION, PANE, object_schema
from mcp_server.tools.registry import (
    ACTION_TOOLS,
    JOB_TOOLS,
    OBSERVATION_TOOLS,
    SESSION_TOOLS,
    TOOLS_BY_NAME,
)

__all__ = [
    "ACTION_TOOLS",
    "GENERATION",
    "JOB_TOOLS",
    "OBSERVATION_TOOLS",
    "PANE",
    "SESSION_TOOLS",
    "TOOLS_BY_NAME",
    "object_schema",
]

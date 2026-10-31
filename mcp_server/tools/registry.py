"""Canonical MCP tool registry grouped by feature domain.

Start here to locate the schema for a public MCP tool.
"""

from mcp_server.tools.jobs import TOOLS as JOB_TOOLS
from mcp_server.tools.observation import TOOLS as OBSERVATION_TOOLS
from mcp_server.tools.sessions import TOOLS as SESSION_DOMAIN_TOOLS
from mcp_server.tools.programs import TOOLS as PROGRAM_TOOLS
from mcp_server.tools.tasks import TOOLS as MODEL_TASK_TOOLS


SESSION_TOOLS = SESSION_DOMAIN_TOOLS
ACTION_TOOLS = [
    *MODEL_TASK_TOOLS,
    *PROGRAM_TOOLS,
]

TOOLS_BY_NAME = {
    tool["name"]: tool
    for tool in [
        *OBSERVATION_TOOLS,
        *ACTION_TOOLS,
        *JOB_TOOLS,
        *SESSION_TOOLS,
    ]
}

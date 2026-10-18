"""Canonical MCP tool registry grouped by feature domain.

Start here to locate the schema for a public MCP tool.
"""

from mcp_server.tools.jobs import TOOLS as JOB_TOOLS
from mcp_server.tools.observation import TOOLS as OBSERVATION_TOOLS
from mcp_server.tools.sessions import TOOLS as SESSION_DOMAIN_TOOLS
from mcp_server.tools.task_blocks import TOOLS as TASK_BLOCK_TOOLS
from mcp_server.tools.tasks import TOOLS as MODEL_TASK_TOOLS


# The first legacy definition is not part of the model API.
SESSION_TOOLS = SESSION_DOMAIN_TOOLS[1:]
ACTION_TOOLS = [
    *MODEL_TASK_TOOLS,
    *[tool for tool in TASK_BLOCK_TOOLS if tool["name"] == "terminal_program_profile"],
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

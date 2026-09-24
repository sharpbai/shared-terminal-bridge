"""Canonical MCP tool registry grouped by feature domain.

Start here to locate the schema for a public MCP tool.
"""

from mcp_server.tools.execution import TOOLS as EXECUTION_TOOLS
from mcp_server.tools.jobs import TOOLS as JOB_TOOLS
from mcp_server.tools.long_run import TOOLS as LONG_RUN_TOOLS
from mcp_server.tools.observation import TOOLS as OBSERVATION_TOOLS
from mcp_server.tools.sessions import TOOLS as SESSION_DOMAIN_TOOLS
from mcp_server.tools.task_blocks import TOOLS as TASK_BLOCK_TOOLS


SESSION_ACQUIRE = SESSION_DOMAIN_TOOLS[0]
SESSION_TOOLS = SESSION_DOMAIN_TOOLS[1:]
ACTION_TOOLS = [
    *LONG_RUN_TOOLS,
    *TASK_BLOCK_TOOLS,
    SESSION_ACQUIRE,
    *EXECUTION_TOOLS,
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

"""Keep public tool, protocol, and facade routing in sync."""

import unittest

from bridge.local_bridge import LocalBridge
from bridge.protocol.registry import METHOD_HANDLERS
from bridge.service import ServiceMethod
from mcp_server.tools.registry import (
    ACTION_TOOLS,
    JOB_TOOLS,
    OBSERVATION_TOOLS,
    SESSION_TOOLS,
    TOOLS_BY_NAME,
)


class RegistryConsistencyTest(unittest.TestCase):
    def test_bridge_registry_targets_real_facade_service_methods(self):
        for method, (source_path, implementation) in METHOD_HANDLERS.items():
            with self.subTest(method=method):
                descriptor = vars(LocalBridge).get(implementation)
                self.assertIsInstance(descriptor, ServiceMethod)
                service_type = LocalBridge._service_types[descriptor.service_name]
                self.assertTrue(hasattr(service_type, implementation))
                self.assertIn(source_path.rsplit("/", 1)[0], service_type.__module__)

    def test_mcp_tools_have_unique_names_and_bridge_routes(self):
        tools = [*OBSERVATION_TOOLS, *ACTION_TOOLS, *JOB_TOOLS, *SESSION_TOOLS]
        names = [tool["name"] for tool in tools]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(TOOLS_BY_NAME))
        special_routes = {
            "terminal_session_acquire": "acquire_execution",
            "terminal_execution_status": "execution_status",
        }
        for name in names:
            with self.subTest(tool=name):
                bridge_method = special_routes.get(name, name)
                self.assertIn(bridge_method, METHOD_HANDLERS)


if __name__ == "__main__":
    unittest.main()

"""Keep public routing and domain-service boundaries in sync."""

import ast
import inspect
import textwrap
import types
import unittest

from bridge.local_bridge import LocalBridge
from bridge.protocol.registry import METHOD_HANDLERS
from bridge.service import SERVICE_DEPENDENCIES, ServiceContext, ServiceMethod
from mcp_server.tools.registry import (
    ACTION_TOOLS,
    JOB_TOOLS,
    OBSERVATION_TOOLS,
    SESSION_TOOLS,
    TOOLS_BY_NAME,
)


class RegistryConsistencyTest(unittest.TestCase):
    @staticmethod
    def _owner_dependencies(service_type):
        tree = ast.parse(textwrap.dedent(inspect.getsource(service_type)))
        dependencies = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "self"
            and node.value.attr == "bridge"
        }
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
            ):
                continue
            owner, name = node.args[:2]
            if (
                isinstance(owner, ast.Attribute)
                and isinstance(owner.value, ast.Name)
                and owner.value.id == "self"
                and owner.attr == "bridge"
                and isinstance(name, ast.Constant)
                and isinstance(name.value, str)
            ):
                dependencies.add(name.value)
        return dependencies

    def test_domain_services_declare_exact_owner_dependencies(self):
        self.assertEqual(set(LocalBridge._service_types), set(SERVICE_DEPENDENCIES))
        for name, service_type in LocalBridge._service_types.items():
            with self.subTest(service=name):
                self.assertEqual(
                    self._owner_dependencies(service_type),
                    SERVICE_DEPENDENCIES[name],
                )

    def test_service_context_rejects_undeclared_owner_access(self):
        owner = types.SimpleNamespace(audit=[], tmux="must stay hidden")
        context = ServiceContext(owner, "audit")
        self.assertIs(context.audit, owner.audit)
        with self.assertRaisesRegex(AttributeError, "not declared: tmux"):
            _ = context.tmux
        with self.assertRaisesRegex(AttributeError, "not declared: tmux"):
            context.tmux = "replacement"

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

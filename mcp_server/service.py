"""Explicit descriptors for the small MCP server compatibility facade."""


class ServerMethod:
    def __init__(self, component_name, method_name=None):
        self.component_name = component_name
        self.method_name = method_name

    def __set_name__(self, owner, name):
        if self.method_name is None:
            self.method_name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return getattr(instance._component(self.component_name), self.method_name)

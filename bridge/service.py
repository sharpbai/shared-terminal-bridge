"""Explicit descriptors used by the compatibility Bridge facade."""


class ServiceMethod:
    """Bind one facade attribute to one named domain service method."""

    def __init__(self, service_name, method_name=None):
        self.service_name = service_name
        self.method_name = method_name

    def __set_name__(self, owner, name):
        if self.method_name is None:
            self.method_name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        service = instance._service(self.service_name)
        return getattr(service, self.method_name)

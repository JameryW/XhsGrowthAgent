import pytest
from xhs_growth.core.di import ServiceContainer, get_container, reset_container

class MockService:
    def __init__(self, value: str = "default"):
        self.value = value

def setup_function():
    reset_container()

def test_container_register_instance():
    container = ServiceContainer()
    service = MockService("instance")
    container.register_instance("mock", service)
    result = container.get("mock")
    assert result.value == "instance"
    assert result is service

def test_container_register_factory():
    container = ServiceContainer()
    container.register_factory("mock", lambda: MockService("factory"))
    result1 = container.get("mock")
    result2 = container.get("mock")
    assert result1.value == "factory"
    assert result1 is result2

def test_container_not_found():
    container = ServiceContainer()
    with pytest.raises(KeyError, match="Service 'unknown' not registered"):
        container.get("unknown")

def test_container_has():
    container = ServiceContainer()
    assert container.has("unknown") is False
    container.register_instance("mock", MockService())
    assert container.has("mock") is True

def test_container_clear():
    container = ServiceContainer()
    container.register_instance("mock", MockService())
    container.clear()
    with pytest.raises(KeyError):
        container.get("mock")

def test_get_container():
    container = get_container()
    assert isinstance(container, ServiceContainer)

def test_reset_container():
    container1 = get_container()
    container1.register_instance("test", MockService())
    reset_container()
    container2 = get_container()
    with pytest.raises(KeyError):
        container2.get("test")
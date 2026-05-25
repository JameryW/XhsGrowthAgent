"""Dependency Injection container for service management."""
from typing import Callable, Any
import logging

logger = logging.getLogger("xhs_growth.di")

class ServiceContainer:
    """Lightweight dependency injection container."""
    def __init__(self):
        self._services: dict[str, Any] = {}
        self._factories: dict[str, Callable[[], Any]] = {}

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a singleton instance."""
        self._services[name] = instance
        logger.debug(f"Registered instance: {name}")

    def register_factory(self, name: str, factory: Callable[[], Any]) -> None:
        """Register a factory function (lazy creation, cached as singleton)."""
        self._factories[name] = factory
        logger.debug(f"Registered factory: {name}")

    def get(self, name: str) -> Any:
        """Get service by name (factory results are cached)."""
        if name in self._services:
            return self._services[name]
        if name in self._factories:
            instance = self._factories[name]()
            self._services[name] = instance
            logger.debug(f"Created service from factory: {name}")
            return instance
        raise KeyError(f"Service '{name}' not registered")

    def has(self, name: str) -> bool:
        """Check if service is registered."""
        return name in self._services or name in self._factories

    def clear(self) -> None:
        """Clear all registrations (for testing)."""
        self._services.clear()
        self._factories.clear()
        logger.debug("Container cleared")

_container: ServiceContainer | None = None

def get_container() -> ServiceContainer:
    """Get the global container instance."""
    global _container
    if _container is None:
        _container = ServiceContainer()
    return _container

def reset_container() -> None:
    """Reset the global container (for testing)."""
    global _container
    _container = ServiceContainer()
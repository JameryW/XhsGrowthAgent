"""Core utilities - dependency injection and configuration."""
from xhs_growth.core.di import ServiceContainer, get_container, reset_container

__all__ = ["ServiceContainer", "get_container", "reset_container"]
"""Service layer for XHS Growth Agent.

Services orchestrate multiple tools and handle errors/caching.
They sit between Agents (business logic) and Tools (atomic operations).
"""

from xhs_growth.services.optimization_service import OptimizationService

__all__ = ["OptimizationService"]

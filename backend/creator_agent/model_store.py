"""Creator Model administration behind a small revision-aware interface."""

from __future__ import annotations

from backend.creator_agent.models import CreatorModel, CreatorModelDefinition
from backend.creator_agent.repository import CreatorAgentRepository


class CreatorModelStore:
    def __init__(self, repository: CreatorAgentRepository):
        self._repository = repository

    async def get(self, account_id: str) -> CreatorModel | None:
        return await self._repository.get_model(account_id.strip())

    async def save(
        self,
        account_id: str,
        definition: CreatorModelDefinition,
        *,
        expected_revision: int,
    ) -> CreatorModel:
        return await self._repository.save_model(
            account_id.strip(),
            definition,
            expected_revision=expected_revision,
        )


__all__ = ["CreatorModelStore"]

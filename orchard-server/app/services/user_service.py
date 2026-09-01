"""User-context business logic: read / update the singleton scheduling
constraints. HTTP-agnostic; returns pure Pydantic models."""
from __future__ import annotations

from ..repositories.user_repository import UserRepository
from ..schemas.user_context import UserContextRead, UserContextUpdate


class UserService:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def get_constraints(self) -> UserContextRead:
        """Return the scheduling constraints, creating defaults on first read."""
        row = self._users.get() or self._users.create_default()
        return UserContextRead.model_validate(row)

    async def update_constraints(
        self, payload: UserContextUpdate
    ) -> UserContextRead:
        if self._users.get() is None:
            self._users.create_default()
        row = self._users.update(payload.model_dump(exclude_unset=True))
        return UserContextRead.model_validate(row)

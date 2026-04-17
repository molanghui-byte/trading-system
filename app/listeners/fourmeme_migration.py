from __future__ import annotations

from app.listeners.base import BaseListener


class FourMemeMigrationListener(BaseListener):
    name = "fourmeme_migration"

    async def fetch(self) -> list[dict]:
        return []

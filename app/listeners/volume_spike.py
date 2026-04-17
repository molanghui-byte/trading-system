from __future__ import annotations

from app.listeners.base import BaseListener


class VolumeSpikeListener(BaseListener):
    name = "volume_spike"

    async def fetch(self) -> list[dict]:
        return []

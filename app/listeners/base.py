from __future__ import annotations

from abc import ABC, abstractmethod


class BaseListener(ABC):
    name: str

    def __init__(self, config) -> None:
        self.config = config

    @abstractmethod
    async def fetch(self) -> list[dict]:
        raise NotImplementedError

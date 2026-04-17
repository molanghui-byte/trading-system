from __future__ import annotations

import os
from typing import Any

import httpx


class Client6551:
    def __init__(self, config) -> None:
        self.config = config.integration_6551
        self.base_url = self.config.api_base_url.rstrip("/")

    def is_enabled(self) -> bool:
        return self.config.enabled and bool(self._token())

    async def search_twitter(
        self,
        *,
        keywords: str | None = None,
        from_user: str | None = None,
        hashtag: str | None = None,
        min_likes: int = 0,
        product: str = "Latest",
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "product": product,
            "maxResults": max_results or self.config.max_rows,
        }
        if keywords:
            payload["keywords"] = keywords
        if from_user:
            payload["fromUser"] = from_user
        if hashtag:
            payload["hashtag"] = hashtag
        if min_likes:
            payload["minLikes"] = min_likes
        response = await self._post("/open/twitter_search", payload)
        return self._extract_rows(response)

    async def get_user_tweets(
        self,
        username: str,
        *,
        max_results: int | None = None,
        product: str = "Latest",
        include_replies: bool = False,
        include_retweets: bool = False,
    ) -> list[dict[str, Any]]:
        payload = {
            "username": username,
            "maxResults": max_results or self.config.max_rows,
            "product": product,
            "includeReplies": include_replies,
            "includeRetweets": include_retweets,
        }
        response = await self._post("/open/twitter_user_tweets", payload)
        return self._extract_rows(response)

    async def get_user_info(self, username: str) -> dict[str, Any]:
        response = await self._post("/open/twitter_user_info", {"username": username})
        if isinstance(response, dict):
            for key in ("data", "result", "user"):
                value = response.get(key)
                if isinstance(value, dict):
                    return value
            return response
        return {}

    async def get_watch_list(self) -> list[dict[str, Any]]:
        response = await self._post("/open/twitter_watch", {})
        return self._extract_rows(response)

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        token = self._token()
        if not token:
            raise RuntimeError("6551 token is not configured")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(
            timeout=self.config.request_timeout_seconds,
            trust_env=False,
            headers=headers,
        ) as client:
            response = await client.post(f"{self.base_url}{path}", json=payload)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _extract_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(response, list):
            return [item for item in response if isinstance(item, dict)]
        for key in ("data", "rows", "items", "result"):
            value = response.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                for nested_key in ("rows", "items", "list", "data"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        return [item for item in nested if isinstance(item, dict)]
        return []

    def _token(self) -> str:
        return os.getenv(self.config.token_env, "").strip()

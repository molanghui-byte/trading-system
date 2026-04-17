from __future__ import annotations

from datetime import datetime, timezone

from app.integrations.client_6551 import Client6551
from app.listeners.base import BaseListener


class Twitter6551Listener(BaseListener):
    name = "twitter6551"

    def __init__(self, config) -> None:
        super().__init__(config)
        self.client = Client6551(config)

    async def fetch(self) -> list[dict]:
        cfg = self.config.integration_6551
        listener_cfg = self.config.listeners.get(self.name)
        if not listener_cfg or not listener_cfg.enabled:
            return []
        if not self.client.is_enabled():
            return []

        payloads: list[dict] = []
        seen_ids: set[str] = set()

        for keyword in cfg.default_keywords:
            rows = await self.client.search_twitter(
                keywords=keyword,
                product="Latest",
                max_results=listener_cfg.max_items,
            )
            payloads.extend(self._normalize_search_rows(rows, f"keyword:{keyword}", seen_ids))

        for username in cfg.default_watch_accounts:
            rows = await self.client.get_user_tweets(
                username,
                max_results=listener_cfg.max_items,
                product="Latest",
            )
            payloads.extend(self._normalize_user_rows(rows, username, seen_ids))

        return payloads[: listener_cfg.max_items]

    def _normalize_search_rows(self, rows: list[dict], query_label: str, seen_ids: set[str]) -> list[dict]:
        payloads: list[dict] = []
        for row in rows:
            signal = self._build_signal(row, source_detail=query_label)
            if not signal or signal["signal_id"] in seen_ids:
                continue
            seen_ids.add(signal["signal_id"])
            payloads.append(signal)
        return payloads

    def _normalize_user_rows(self, rows: list[dict], username: str, seen_ids: set[str]) -> list[dict]:
        payloads: list[dict] = []
        for row in rows:
            signal = self._build_signal(row, source_detail=f"user:{username}")
            if not signal or signal["signal_id"] in seen_ids:
                continue
            seen_ids.add(signal["signal_id"])
            payloads.append(signal)
        return payloads

    def _build_signal(self, row: dict, source_detail: str) -> dict | None:
        text = str(row.get("text") or row.get("content") or "").strip()
        tweet_id = str(row.get("id") or row.get("tweetId") or row.get("twId") or "").strip()
        if not tweet_id:
            return None
        ca = self._extract_ca(text) or str(row.get("ca") or "").strip()
        hashtags = row.get("hashtags") or []
        narrative = ",".join(hashtags[:3]) if isinstance(hashtags, list) else ""
        likes = self._to_int(row.get("favoriteCount") or row.get("likeCount"))
        retweets = self._to_int(row.get("retweetCount"))
        replies = self._to_int(row.get("replyCount"))
        followers = self._to_int(row.get("userFollowers") or row.get("followerCount"))
        score = min(0.35 + min((likes + retweets * 2 + replies) / 5000, 0.45), 0.95)
        risk_score = 0.25 if ca else 0.6
        created_at = row.get("createdAt") or datetime.now(timezone.utc).isoformat()
        username = str(row.get("userScreenName") or row.get("twAccount") or "").strip()
        symbol = self._guess_symbol(text)
        return {
            "signal_id": f"6551:{tweet_id}",
            "source_type": "twitter_6551",
            "source_detail": source_detail,
            "chain": "bsc",
            "ca": ca,
            "symbol": symbol,
            "narrative": narrative or "twitter_signal",
            "content": text[:500],
            "signal_score": score,
            "risk_score": risk_score,
            "liquidity": 0.0,
            "market_cap": 0.0,
            "holder_count": 0,
            "top10_rate": 0.0,
            "bundler_rate": 0.0,
            "bot_rate": 0.0,
            "discovered_at": created_at,
            "raw_item": row,
            "username": username,
        }

    @staticmethod
    def _extract_ca(text: str) -> str:
        for token in text.replace("\n", " ").split():
            cleaned = token.strip(" ,.;:!?()[]{}<>\"'")
            if cleaned.startswith("0x") and len(cleaned) == 42:
                return cleaned
        return ""

    @staticmethod
    def _guess_symbol(text: str) -> str:
        for token in text.split():
            cleaned = token.strip(" ,.;:!?()[]{}<>\"'")
            if cleaned.startswith("$") and 1 < len(cleaned) <= 12:
                return cleaned[1:].upper()
        return ""

    @staticmethod
    def _to_int(value) -> int:
        try:
            if value in ("", None):
                return 0
            return int(float(value))
        except (TypeError, ValueError):
            return 0

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.listeners.base import BaseListener


class SolanaNewPairsListener(BaseListener):
    name = "solnewpairs"

    async def fetch(self) -> list[dict[str, Any]]:
        cfg = self.config.listeners.get(self.name)
        if not cfg or not cfg.enabled:
            return []
        live_items = await self._fetch_live(cfg)
        if live_items:
            return live_items[: cfg.max_items]
        return self._load_mock(cfg)[: cfg.max_items]

    async def _fetch_live(self, cfg) -> list[dict[str, Any]]:
        urls = [url for url in ([cfg.endpoint] + cfg.endpoints) if url]
        if not urls:
            return []
        headers = {
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ),
            "accept": "application/json, text/plain, */*",
        }
        headers.update(cfg.browser_headers)
        async with httpx.AsyncClient(
            timeout=cfg.timeout_seconds,
            headers=headers,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            for url in urls:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    items = self._extract_items(response)
                    normalized = [self._normalize_item(item, url) for item in items]
                    normalized = [item for item in normalized if item]
                    if normalized:
                        return normalized
                except Exception:
                    continue
        return []

    def _extract_items(self, response: httpx.Response) -> list[dict[str, Any]]:
        data = response.json()
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        for key in ("items", "pairs", "data", "rows", "list", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                for nested_key in ("items", "pairs", "rows", "list"):
                    nested_value = value.get(nested_key)
                    if isinstance(nested_value, list):
                        return [item for item in nested_value if isinstance(item, dict)]
        return []

    def _normalize_item(self, item: dict[str, Any], source_url: str) -> dict[str, Any]:
        ca = str(
            item.get("ca")
            or item.get("mint")
            or item.get("tokenAddress")
            or item.get("address")
            or item.get("baseTokenAddress")
            or ""
        ).strip()
        if not ca:
            return {}
        symbol = str(item.get("symbol") or item.get("ticker") or item.get("tokenSymbol") or "").strip()
        liquidity = self._to_float(
            item.get("liquidity")
            or item.get("liquidityUsd")
            or item.get("liquidityUSD")
            or item.get("lpUsd")
        )
        market_cap = self._to_float(
            item.get("market_cap") or item.get("marketCap") or item.get("fdv") or item.get("fdvUsd")
        )
        holder_count = self._to_int(item.get("holder_count") or item.get("holders") or item.get("holderCount"))
        top10_rate = self._to_ratio(item.get("top10_rate") or item.get("top10Rate"))
        bundler_rate = self._to_ratio(item.get("bundler_rate") or item.get("bundlerRate"))
        bot_rate = self._to_ratio(item.get("bot_rate") or item.get("botRate"))
        raw_score = self._to_float(item.get("score") or item.get("hotScore") or item.get("trendScore") or 0.5)
        signal_score = min(max(raw_score, 0.0), 1.0) if raw_score <= 1 else min(raw_score / 100, 1.0)
        risk_score = min(max((bundler_rate + bot_rate + top10_rate) / 3, 0.0), 1.0)
        discovered_at = (
            item.get("createdAt")
            or item.get("launchTime")
            or item.get("created_at")
            or item.get("discovered_at")
            or datetime.now(timezone.utc).isoformat()
        )
        return {
            "signal_id": str(item.get("id") or item.get("pairId") or item.get("uuid") or f"sol:{ca}:{discovered_at}"),
            "source_type": "api",
            "source_detail": source_url,
            "chain": "sol",
            "ca": ca,
            "symbol": symbol,
            "narrative": str(item.get("narrative") or item.get("category") or "meme"),
            "content": str(item.get("name") or item.get("title") or symbol or ca),
            "signal_score": signal_score or 0.5,
            "risk_score": risk_score,
            "liquidity": liquidity,
            "market_cap": market_cap,
            "holder_count": holder_count,
            "top10_rate": top10_rate,
            "bundler_rate": bundler_rate,
            "bot_rate": bot_rate,
            "discovered_at": discovered_at,
            "raw_item": {**item, "__endpoint__": source_url},
        }

    def _load_mock(self, cfg) -> list[dict[str, Any]]:
        if not cfg.mock_payload_path:
            return []
        path = Path(cfg.mock_payload_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / cfg.mock_payload_path
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload if isinstance(payload, list) else payload.get("items", [])
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            enriched["chain"] = "sol"
            enriched.setdefault("raw_item", {})
            enriched["raw_item"] = {
                **(enriched["raw_item"] if isinstance(enriched["raw_item"], dict) else {}),
                "__mock__": True,
            }
            normalized.append(enriched)
        return normalized

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            if value in ("", None):
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            if value in ("", None):
                return 0
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_ratio(value: Any) -> float:
        try:
            if value in ("", None):
                return 0.0
            numeric = float(value)
            if numeric > 1:
                return min(numeric / 100.0, 1.0)
            return max(numeric, 0.0)
        except (TypeError, ValueError):
            return 0.0

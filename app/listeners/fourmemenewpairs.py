from __future__ import annotations

import asyncio
import json
import ssl
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.listeners.base import BaseListener


class FourMemeNewPairsListener(BaseListener):
    name = "fourmemenewpairs"
    token_purchase_topic = "0x0a5575b3648bae2210cee56bf33254cc1ddfbc7bf637c0af2ac18b14fb1bae19"

    def __init__(self, config) -> None:
        super().__init__(config)
        self._rpc_cooldown_until: datetime | None = None
        self._rpc_failure_count = 0
        self._last_rpc_error = ""

    async def fetch(self) -> list[dict[str, Any]]:
        cfg = self.config.listeners.get(self.name)
        if not cfg or not cfg.enabled:
            return []
        now = datetime.now(timezone.utc)
        chain_items = await self._fetch_chain(cfg, now)
        if chain_items:
            return chain_items[: cfg.max_items]
        live_items = await self._fetch_live(cfg)
        if live_items:
            return live_items[: cfg.max_items]
        if cfg.use_mock_on_rpc_failure:
            return self._load_mock(cfg)
        return []

    async def _fetch_chain(self, cfg, now: datetime) -> list[dict[str, Any]]:
        rpc_urls = [url for url in ([cfg.rpc_url] + cfg.rpc_urls) if url]
        if not rpc_urls or not cfg.contract_address:
            return []
        if self._rpc_cooldown_until and now < self._rpc_cooldown_until:
            return []
        topic = cfg.event_topic or self.token_purchase_topic
        for rpc_url in rpc_urls:
            latest_block = await self._rpc_call(rpc_url, "eth_blockNumber", [])
            if not latest_block:
                continue
            latest_int = int(latest_block, 16)
            from_block = max(latest_int - max(cfg.block_window, 10), cfg.start_block or 0)
            params = [
                {
                    "fromBlock": hex(from_block),
                    "toBlock": hex(latest_int),
                    "address": cfg.contract_address,
                    "topics": [topic],
                }
            ]
            result = await self._rpc_call(rpc_url, "eth_getLogs", params)
            logs = result or []
            normalized = [self._normalize_chain_log(log, rpc_url) for log in logs]
            normalized = [item for item in normalized if item]
            if normalized:
                self._rpc_failure_count = 0
                self._last_rpc_error = ""
                self._rpc_cooldown_until = None
                return normalized
        return []

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
            "accept-language": "en-US,en;q=0.9",
            "origin": cfg.page_url or "https://4.meme",
            "referer": (cfg.page_url.rstrip("/") + "/") if cfg.page_url else "https://4.meme/",
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
        for key in ("items", "data", "rows", "list", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                for nested_key in ("items", "rows", "list"):
                    nested_value = value.get(nested_key)
                    if isinstance(nested_value, list):
                        return [item for item in nested_value if isinstance(item, dict)]
        return []

    def _normalize_item(self, item: dict[str, Any], source_url: str) -> dict[str, Any]:
        ca = str(
            item.get("ca")
            or item.get("tokenAddress")
            or item.get("address")
            or item.get("contractAddress")
            or item.get("token_address")
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
        )
        return {
            "signal_id": str(item.get("id") or item.get("pairId") or item.get("uuid") or f"{ca}:{discovered_at or symbol}"),
            "source_type": "api",
            "source_detail": source_url,
            "chain": "bsc",
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
            if isinstance(item, dict):
                enriched = dict(item)
                enriched.setdefault("raw_item", {})
                enriched["raw_item"] = {
                    **(enriched["raw_item"] if isinstance(enriched["raw_item"], dict) else {}),
                    "__mock__": True,
                }
                normalized.append(enriched)
        return normalized

    async def _rpc_call(self, rpc_url: str, method: str, params: list[Any]) -> Any:
        try:
            return await asyncio.to_thread(self._rpc_call_sync, rpc_url, method, params)
        except Exception as exc:
            cfg = self.config.listeners.get(self.name)
            cooldown_seconds = cfg.rpc_error_cooldown_seconds if cfg else 30
            self._rpc_failure_count += 1
            self._last_rpc_error = str(exc)
            self._rpc_cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)
            return None

    def _rpc_call_sync(self, rpc_url: str, method: str, params: list[Any]) -> Any:
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        ).encode("utf-8")
        request = urllib.request.Request(
            rpc_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, timeout=20, context=context) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("error"):
            return None
        return data.get("result")

    def _normalize_chain_log(self, log: dict[str, Any], rpc_url: str) -> dict[str, Any]:
        data = log.get("data", "")
        if not isinstance(data, str) or not data.startswith("0x"):
            return {}
        words = [data[2 + i : 2 + i + 64] for i in range(0, len(data) - 2, 64)]
        if len(words) < 8:
            return {}
        token_address = self._word_to_address(words[0])
        buyer = self._word_to_address(words[1])
        bnb_amount = self._word_to_float(words[2], decimals=18)
        token_amount = self._word_to_float(words[3], decimals=18)
        market_cap = self._word_to_float(words[5], decimals=18)
        liquidity = self._word_to_float(words[6], decimals=18)
        block_timestamp = int(log.get("blockTimestamp", "0x0"), 16) if log.get("blockTimestamp") else 0
        discovered_at = (
            datetime.fromtimestamp(block_timestamp, tz=timezone.utc).isoformat()
            if block_timestamp
            else datetime.now(timezone.utc).isoformat()
        )
        price_estimate = (bnb_amount / token_amount) if token_amount else 0.0
        signal_score = min(0.5 + min(liquidity / 100000, 0.4), 0.95)
        return {
            "signal_id": f"{log.get('transactionHash')}:{log.get('logIndex')}",
            "source_type": "chain_event",
            "source_detail": log.get("transactionHash", ""),
            "chain": "bsc",
            "ca": token_address,
            "symbol": "",
            "narrative": "fourmeme_chain_purchase",
            "content": f"buyer {buyer} purchased token on fourmeme bonding curve",
            "signal_score": signal_score,
            "risk_score": 0.2,
            "liquidity": liquidity,
            "market_cap": market_cap or (price_estimate * token_amount),
            "holder_count": 0,
            "top10_rate": 0.0,
            "bundler_rate": 0.0,
            "bot_rate": 0.0,
            "discovered_at": discovered_at,
            "raw_item": {**log, "__rpc_url__": rpc_url},
        }

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

    @staticmethod
    def _word_to_address(word: str) -> str:
        return "0x" + word[-40:]

    @staticmethod
    def _word_to_float(word: str, decimals: int = 18) -> float:
        try:
            return int(word, 16) / (10**decimals)
        except (TypeError, ValueError):
            return 0.0

    def diagnostics(self) -> dict[str, Any]:
        return {
            "rpc_failure_count": self._rpc_failure_count,
            "rpc_cooldown_until": self._rpc_cooldown_until.isoformat() if self._rpc_cooldown_until else "",
            "last_rpc_error": self._last_rpc_error,
        }

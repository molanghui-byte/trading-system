from __future__ import annotations

import asyncio
import json
import ssl
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.listeners.base import BaseListener


class EthereumNewPairsListener(BaseListener):
    name = "ethnewpairs"
    uniswap_v2_pair_created_topic = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
    weth_address = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"

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
        return []

    async def _fetch_chain(self, cfg, now: datetime) -> list[dict[str, Any]]:
        rpc_urls = [url for url in ([cfg.rpc_url] + cfg.rpc_urls) if url]
        if not rpc_urls or not cfg.contract_address:
            return []
        if self._rpc_cooldown_until and now < self._rpc_cooldown_until:
            return []
        topic = cfg.event_topic or self.uniswap_v2_pair_created_topic
        for rpc_url in rpc_urls:
            latest_block = await self._rpc_call(rpc_url, "eth_blockNumber", [])
            if not latest_block:
                continue
            latest_int = int(latest_block, 16)
            from_block = max(latest_int - max(cfg.block_window, 10), cfg.start_block or 0)
            result = await self._rpc_call(
                rpc_url,
                "eth_getLogs",
                [
                    {
                        "fromBlock": hex(from_block),
                        "toBlock": hex(latest_int),
                        "address": cfg.contract_address,
                        "topics": [topic],
                    }
                ],
            )
            logs = result or []
            normalized = [self._normalize_pair_created_log(log, rpc_url) for log in logs]
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
        base_token = item.get("baseToken") if isinstance(item.get("baseToken"), dict) else {}
        token = item.get("token") if isinstance(item.get("token"), dict) else {}
        liquidity_obj = item.get("liquidity") if isinstance(item.get("liquidity"), dict) else {}
        ca = str(
            item.get("ca")
            or item.get("tokenAddress")
            or item.get("address")
            or item.get("contractAddress")
            or item.get("baseTokenAddress")
            or base_token.get("address")
            or token.get("address")
            or ""
        ).strip()
        if not ca:
            return {}
        symbol = str(
            item.get("symbol")
            or item.get("ticker")
            or item.get("tokenSymbol")
            or base_token.get("symbol")
            or token.get("symbol")
            or ""
        ).strip()
        liquidity = self._to_float(
            liquidity_obj.get("usd")
            or item.get("liquidityUsd")
            or item.get("liquidityUSD")
            or item.get("lpUsd")
            or item.get("liquidity")
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
        discovered_at = self._normalize_timestamp(
            item.get("createdAt")
            or item.get("pairCreatedAt")
            or item.get("launchTime")
            or item.get("created_at")
            or item.get("discovered_at")
        )
        return {
            "signal_id": str(item.get("id") or item.get("pairAddress") or item.get("pairId") or f"eth:{ca}:{discovered_at}"),
            "source_type": "api",
            "source_detail": source_url,
            "chain": "eth",
            "ca": ca,
            "symbol": symbol,
            "narrative": str(item.get("narrative") or item.get("category") or "eth_meme"),
            "content": str(item.get("name") or item.get("title") or symbol or ca),
            "signal_score": signal_score or 0.5,
            "risk_score": min(max((bundler_rate + bot_rate + top10_rate) / 3, 0.0), 1.0),
            "liquidity": liquidity,
            "market_cap": market_cap,
            "holder_count": holder_count,
            "top10_rate": top10_rate,
            "bundler_rate": bundler_rate,
            "bot_rate": bot_rate,
            "discovered_at": discovered_at,
            "raw_item": {**item, "__endpoint__": source_url},
        }

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
            headers={
                "Content-Type": "application/json",
                "User-Agent": "trading-system/1.0",
                "Accept": "application/json",
            },
        )
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, timeout=20, context=context) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("error"):
            return None
        return data.get("result")

    def _normalize_pair_created_log(self, log: dict[str, Any], rpc_url: str) -> dict[str, Any]:
        topics = log.get("topics") or []
        if len(topics) < 3:
            return {}
        token0 = self._topic_to_address(topics[1])
        token1 = self._topic_to_address(topics[2])
        ca = token1 if token0.lower() == self.weth_address else token0
        data = log.get("data", "")
        pair_address = ""
        if isinstance(data, str) and data.startswith("0x") and len(data) >= 66:
            pair_address = self._word_to_address(data[2:66])
        discovered_at = datetime.now(timezone.utc).isoformat()
        tx_hash = str(log.get("transactionHash") or "")
        log_index = str(log.get("logIndex") or "0x0")
        return {
            "signal_id": f"{tx_hash}:{log_index}",
            "source_type": "chain_event",
            "source_detail": tx_hash,
            "chain": "eth",
            "ca": ca,
            "symbol": "",
            "narrative": "eth_uniswap_v2_pair_created",
            "content": f"new ETH pair created {pair_address or ca}",
            "signal_score": 0.55,
            "risk_score": 0.35,
            "liquidity": 0.0,
            "market_cap": 0.0,
            "holder_count": 0,
            "top10_rate": 0.0,
            "bundler_rate": 0.0,
            "bot_rate": 0.0,
            "discovered_at": discovered_at,
            "raw_item": {**log, "__rpc_url__": rpc_url, "pair_address": pair_address, "token0": token0, "token1": token1},
        }

    def diagnostics(self) -> dict[str, Any]:
        return {
            "rpc_failure_count": self._rpc_failure_count,
            "last_rpc_error": self._last_rpc_error,
            "rpc_cooldown_until": self._rpc_cooldown_until.isoformat() if self._rpc_cooldown_until else "",
        }

    @staticmethod
    def _topic_to_address(topic: str) -> str:
        value = str(topic)
        return "0x" + value[-40:]

    @staticmethod
    def _word_to_address(word: str) -> str:
        return "0x" + word[-40:]

    @staticmethod
    def _normalize_timestamp(value: Any) -> str:
        if value in ("", None):
            return datetime.now(timezone.utc).isoformat()
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        return str(value)

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            if value in ("", None) or isinstance(value, dict):
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

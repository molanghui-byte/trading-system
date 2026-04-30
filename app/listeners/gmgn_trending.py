from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timezone
from typing import Any

from app.listeners.base import BaseListener
from app.market_decision import evaluate_market_item


class GMGNTrendingListener(BaseListener):
    name = "gmgn_trending"
    supported_chains = {"sol", "bsc", "base", "eth"}

    def __init__(self, config) -> None:
        super().__init__(config)
        self._last_error = ""

    async def fetch(self) -> list[dict[str, Any]]:
        cfg = self.config.listeners.get(self.name)
        if not cfg or not cfg.enabled:
            return []

        chain = (self.config.system.chain or "sol").strip().lower()
        if chain not in self.supported_chains:
            self._last_error = f"unsupported GMGN chain: {chain}"
            return []

        gmgn_cli = shutil.which("gmgn-cli")
        if not gmgn_cli:
            self._last_error = "gmgn-cli not found"
            return []

        try:
            items = await self._fetch_trending(gmgn_cli, cfg, chain)
        except Exception as exc:
            self._last_error = str(exc)
            return []

        self._last_error = ""
        payloads = [self._normalize_item(item, chain, cfg) for item in items]
        payloads = [item for item in payloads if item and self._passes_filters(item, cfg)]
        return payloads[: cfg.max_items]

    async def _fetch_trending(self, gmgn_cli: str, cfg, chain: str) -> list[dict[str, Any]]:
        args = [
            gmgn_cli,
            "market",
            "trending",
            "--chain",
            chain,
            "--interval",
            cfg.interval,
            "--order-by",
            cfg.order_by,
            "--limit",
            str(cfg.max_items),
            "--raw",
        ]
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=cfg.timeout_seconds)
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(message or f"gmgn-cli exited with {process.returncode}")

        data = json.loads(stdout.decode("utf-8"))
        rank = data.get("data", {}).get("rank", [])
        if not isinstance(rank, list):
            return []
        return [item for item in rank if isinstance(item, dict)]

    def _normalize_item(self, item: dict[str, Any], chain: str, cfg) -> dict[str, Any]:
        ca = str(item.get("address") or item.get("ca") or "").strip()
        if not ca:
            return {}

        discovered_at = self._timestamp_to_iso(
            item.get("open_timestamp") or item.get("creation_timestamp")
        )
        symbol = str(item.get("symbol") or item.get("name") or "").strip()
        volume = self._to_float(item.get("volume"))
        liquidity = self._to_float(item.get("liquidity"))
        market_cap = self._to_float(item.get("market_cap"))
        holder_count = self._to_int(item.get("holder_count"))
        top10_rate = self._to_ratio(item.get("top_10_holder_rate"))
        bundler_rate = self._to_ratio(item.get("bundler_rate"))
        bot_rate = self._to_ratio(item.get("bot_degen_rate"))
        rug_ratio = self._to_ratio(item.get("rug_ratio"))
        wash_trading = bool(item.get("is_wash_trading"))
        creator_closed = bool(item.get("creator_close")) or item.get("creator_token_status") == "creator_close"
        smart_degen_count = self._to_int(item.get("smart_degen_count"))
        renowned_count = self._to_int(item.get("renowned_count"))
        decision = evaluate_market_item(item)

        signal_score = max(
            decision.score / 100,
            self._score_signal(
                volume=volume,
                liquidity=liquidity,
                smart_degen_count=smart_degen_count,
                renowned_count=renowned_count,
                price_change_1h=self._to_float(item.get("price_change_percent1h")),
                creator_closed=creator_closed,
            ),
        )
        risk_score = max(
            decision.risk_score,
            self._score_risk(
                top10_rate=top10_rate,
                bundler_rate=bundler_rate,
                bot_rate=bot_rate,
                rug_ratio=rug_ratio,
                wash_trading=wash_trading,
                liquidity=liquidity,
            ),
        )

        return {
            "signal_id": f"gmgn:{chain}:{ca}",
            "source_type": "api",
            "source_detail": f"gmgn:trending:{cfg.interval}:{cfg.order_by}",
            "chain": chain,
            "ca": ca,
            "symbol": symbol,
            "narrative": str(item.get("launchpad_platform") or item.get("launchpad") or "gmgn_trending"),
            "content": (
                f"GMGN trending {chain.upper()} {symbol or ca}: "
                f"volume={volume:.2f}, liquidity={liquidity:.2f}, smart={smart_degen_count}"
            ),
            "signal_score": signal_score,
            "risk_score": risk_score,
            "liquidity": liquidity,
            "market_cap": market_cap,
            "holder_count": holder_count,
            "top10_rate": top10_rate,
            "bundler_rate": bundler_rate,
            "bot_rate": bot_rate,
            "discovered_at": discovered_at,
            "raw_item": {
                **item,
                "__endpoint__": "gmgn-cli market trending",
                "__source_mode__": "gmgn-cli",
                "__gmgn_interval__": cfg.interval,
                "__gmgn_volume_usd__": volume,
                "__gmgn_rug_ratio__": rug_ratio,
                "__gmgn_smart_degen_count__": smart_degen_count,
                "__gmgn_renowned_count__": renowned_count,
                "__decision_label__": decision.label,
                "__decision_score__": decision.score,
                "__decision_reasons__": decision.reasons,
                "__decision_blockers__": decision.blockers,
            },
        }

    def _passes_filters(self, payload: dict[str, Any], cfg) -> bool:
        raw = payload.get("raw_item") if isinstance(payload.get("raw_item"), dict) else {}
        if bool(raw.get("is_wash_trading")):
            return False
        if self._to_ratio(raw.get("rug_ratio")) > cfg.max_rug_ratio:
            return False
        if payload["liquidity"] < cfg.min_liquidity:
            return False
        if payload["market_cap"] < cfg.min_market_cap:
            return False
        if self._to_float(raw.get("volume")) < cfg.min_volume:
            return False
        if payload["top10_rate"] > cfg.max_top10_rate:
            return False
        if payload["bundler_rate"] > cfg.max_bundler_rate:
            return False
        if payload["bot_rate"] > cfg.max_bot_rate:
            return False
        return True

    def diagnostics(self) -> dict[str, Any]:
        return {
            "last_rpc_error": self._last_error,
            "rpc_failure_count": 1 if self._last_error else 0,
            "rpc_cooldown_until": "",
        }

    @staticmethod
    def _score_signal(
        *,
        volume: float,
        liquidity: float,
        smart_degen_count: int,
        renowned_count: int,
        price_change_1h: float,
        creator_closed: bool,
    ) -> float:
        score = 0.25
        if volume >= 1_000_000:
            score += 0.2
        elif volume >= 250_000:
            score += 0.12
        if liquidity >= 50_000:
            score += 0.18
        elif liquidity >= 10_000:
            score += 0.08
        score += min(smart_degen_count, 10) * 0.025
        score += min(renowned_count, 5) * 0.02
        if price_change_1h > 20:
            score += 0.08
        if creator_closed:
            score += 0.07
        return min(score, 1.0)

    @staticmethod
    def _score_risk(
        *,
        top10_rate: float,
        bundler_rate: float,
        bot_rate: float,
        rug_ratio: float,
        wash_trading: bool,
        liquidity: float,
    ) -> float:
        score = max(top10_rate, bundler_rate, bot_rate, rug_ratio)
        if wash_trading:
            score = max(score, 0.95)
        if liquidity < 10_000:
            score = max(score, 0.65)
        return min(max(score, 0.0), 1.0)

    @staticmethod
    def _timestamp_to_iso(value: Any) -> str:
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            return datetime.now(timezone.utc).isoformat()
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()

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
        except (TypeError, ValueError):
            return 0.0
        if numeric > 1:
            return min(numeric / 100, 1.0)
        return max(numeric, 0.0)

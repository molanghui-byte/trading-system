from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.client_6551 import Client6551
from app.models import RuntimeState


SNIPE_KEYWORDS = (
    "ca",
    "contract",
    "ticker",
    "token",
    "launch",
    "mint",
    "ape",
    "buy",
    "send",
    "pair",
    "listing",
)

MCAP_PATTERNS = [
    re.compile(r"\bmc(?:ap)?\s*[:=]?\s*\$?\s*([\d,.]+)\s*([kmb])?\b", re.IGNORECASE),
    re.compile(r"\$([\d,.]+)\s*([kmb])\s*mcap\b", re.IGNORECASE),
]


@dataclass
class HotspotSnipe:
    record_id: str
    sniper_person: str
    situation: str
    buy_market_cap: str
    pnl_usd: float
    pnl_pct: float
    status: str
    ca: str
    symbol: str
    tweet_id: str
    tweet_url: str
    created_at: str
    is_new: bool = False


@dataclass
class HotspotSniperResult:
    items: list[HotspotSnipe]
    alert_count: int
    auto_refresh_seconds: int


class HotspotSniperScanner:
    def __init__(self, config) -> None:
        self.config = config
        self.client = Client6551(config)
        self.state_key = "hotspot_sniper_records"
        self.alert_key = "hotspot_sniper_alerts"
        self.auto_refresh_seconds = 60
        self.bootstrap_accounts = ["cz_binance", "heyibinance"]

    async def scan(self, session: AsyncSession) -> HotspotSniperResult:
        accounts = self._watch_accounts()
        if not self.client.is_enabled():
            return HotspotSniperResult(
                items=[
                    HotspotSnipe(
                        record_id="system:no_token",
                        sniper_person="系统",
                        situation="未检测到 TWITTER_TOKEN，热点狙击暂未启用。",
                        buy_market_cap="未知",
                        pnl_usd=0.0,
                        pnl_pct=0.0,
                        status="未启用",
                        ca="",
                        symbol="",
                        tweet_id="",
                        tweet_url="#",
                        created_at=datetime.now(timezone.utc).isoformat(),
                        is_new=False,
                    )
                ],
                alert_count=0,
                auto_refresh_seconds=self.auto_refresh_seconds,
            )

        if not accounts:
            return HotspotSniperResult(
                items=[
                    HotspotSnipe(
                        record_id="system:no_accounts",
                        sniper_person="等待名单",
                        situation="请提供特别关注的人名单，系统会开始持续盯推并生成狙击记录。",
                        buy_market_cap="未知",
                        pnl_usd=0.0,
                        pnl_pct=0.0,
                        status="待配置",
                        ca="",
                        symbol="",
                        tweet_id="",
                        tweet_url="#",
                        created_at=datetime.now(timezone.utc).isoformat(),
                        is_new=False,
                    )
                ],
                alert_count=0,
                auto_refresh_seconds=self.auto_refresh_seconds,
            )

        existing = await self._load_existing(session)
        existing_map = {item.record_id: item for item in existing}
        new_alerts = 0

        scanned: list[HotspotSnipe] = []
        for username in accounts:
            rows = await self.client.get_user_tweets(
                username,
                max_results=8,
                product="Latest",
                include_replies=False,
                include_retweets=False,
            )
            for row in rows:
                item = self._extract(username, row)
                if not item:
                    continue
                prior = existing_map.get(item.record_id)
                if prior:
                    item.pnl_usd = prior.pnl_usd
                    item.pnl_pct = prior.pnl_pct
                    item.status = prior.status
                    item.is_new = False
                else:
                    item.is_new = True
                    new_alerts += 1
                scanned.append(item)

        scanned.sort(key=lambda item: item.created_at, reverse=True)
        dedup: dict[str, HotspotSnipe] = {}
        for item in scanned:
            dedup[item.record_id] = item
        items = list(dedup.values())[:20]

        await self._save_records(session, items)
        await self._save_alert_state(session, new_alerts)
        return HotspotSniperResult(
            items=items,
            alert_count=new_alerts,
            auto_refresh_seconds=self.auto_refresh_seconds,
        )

    def _watch_accounts(self) -> list[str]:
        env_value = os.getenv("HOTSPOT_SNIPER_ACCOUNTS", "")
        env_accounts = [item.strip().lstrip("@") for item in env_value.split(",") if item.strip()]
        config_accounts = [item.strip().lstrip("@") for item in self.config.integration_6551.default_watch_accounts if item.strip()]
        merged = env_accounts + config_accounts + self.bootstrap_accounts
        return list(dict.fromkeys(account for account in merged if account))

    async def _load_existing(self, session: AsyncSession) -> list[HotspotSnipe]:
        result = await session.execute(select(RuntimeState).where(RuntimeState.state_key == self.state_key))
        row = result.scalar_one_or_none()
        if not row or not row.state_json:
            return []
        try:
            payload = json.loads(row.state_json)
        except json.JSONDecodeError:
            return []
        items = payload.get("items", []) if isinstance(payload, dict) else []
        parsed: list[HotspotSnipe] = []
        for item in items:
            if isinstance(item, dict):
                try:
                    parsed.append(HotspotSnipe(**item))
                except TypeError:
                    continue
        return parsed

    async def _save_records(self, session: AsyncSession, items: list[HotspotSnipe]) -> None:
        payload = {"items": [asdict(item) for item in items]}
        await self._upsert_state(session, self.state_key, payload)

    async def _save_alert_state(self, session: AsyncSession, count: int) -> None:
        payload = {
            "alert_count": count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._upsert_state(session, self.alert_key, payload)

    async def _upsert_state(self, session: AsyncSession, key: str, payload: dict[str, Any]) -> None:
        result = await session.execute(select(RuntimeState).where(RuntimeState.state_key == key))
        row = result.scalar_one_or_none()
        if row:
            row.state_json = json.dumps(payload, ensure_ascii=False)
        else:
            session.add(RuntimeState(state_key=key, state_json=json.dumps(payload, ensure_ascii=False)))

    def _extract(self, username: str, row: dict[str, Any]) -> HotspotSnipe | None:
        text = str(row.get("text") or row.get("content") or "").strip()
        if not text:
            return None
        created_at = self._parse_datetime(row.get("createdAt") or "")
        if not created_at or created_at < datetime.now(timezone.utc) - timedelta(days=3):
            return None

        ca = self._extract_ca(text)
        symbol = self._extract_symbol(text)
        lower = text.lower()
        if not ca and not symbol and not any(keyword in lower for keyword in SNIPE_KEYWORDS):
            return None

        tweet_id = str(row.get("id") or row.get("tweetId") or row.get("twId") or "").strip()
        if not tweet_id:
            return None

        buy_market_cap = self._extract_market_cap(text)
        if ca or symbol:
            status = "已识别标的，准备狙击"
        else:
            status = "观察中，持续扫描"
        summary = self._summary(text, ca=ca, symbol=symbol)
        return HotspotSnipe(
            record_id=f"{username.lower()}:{tweet_id}",
            sniper_person=f"@{username}",
            situation=summary,
            buy_market_cap=buy_market_cap,
            pnl_usd=0.0,
            pnl_pct=0.0,
            status=status,
            ca=ca,
            symbol=symbol,
            tweet_id=tweet_id,
            tweet_url=f"https://x.com/{username}/status/{tweet_id}",
            created_at=created_at.isoformat(),
            is_new=True,
        )

    @staticmethod
    def _summary(text: str, *, ca: str, symbol: str) -> str:
        clean = " ".join(text.split())
        parts: list[str] = []
        if symbol:
            parts.append(f"建议买入 ${symbol}")
        if ca:
            parts.append("建议按 CA 狙击")
        if not parts:
            parts.append("命中热点语义，暂未唯一识别币种，继续盯后续推文并在识别后第一时间买入")
        parts.append(clean[:120])
        return " / ".join(parts)

    @staticmethod
    def _extract_ca(text: str) -> str:
        for token in text.replace("\n", " ").split():
            cleaned = token.strip(" ,.;:!?()[]{}<>\"'")
            if cleaned.startswith("0x") and len(cleaned) == 42:
                return cleaned
            if 32 <= len(cleaned) <= 48 and cleaned.isalnum() and not cleaned.startswith("http"):
                return cleaned
        return ""

    @staticmethod
    def _extract_symbol(text: str) -> str:
        for token in text.split():
            cleaned = token.strip(" ,.;:!?()[]{}<>\"'")
            if cleaned.startswith("$") and 1 < len(cleaned) <= 12:
                return cleaned[1:].upper()
        return ""

    @staticmethod
    def _extract_market_cap(text: str) -> str:
        for pattern in MCAP_PATTERNS:
            match = pattern.search(text)
            if match:
                number = match.group(1)
                suffix = (match.group(2) or "").upper()
                return f"{number}{suffix}"
        return "未知"

    @staticmethod
    def _parse_datetime(raw: str) -> datetime | None:
        if not raw:
            return None
        normalized = raw.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

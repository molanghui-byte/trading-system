from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.integrations.client_6551 import Client6551


TIME_PATTERNS = [
    re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z| UTC)?)", re.IGNORECASE),
    re.compile(r"(\d{4}/\d{2}/\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)", re.IGNORECASE),
    re.compile(r"(\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?(?:\s+\d{1,2}:\d{2}\s*(?:utc|gmt|am|pm)?)?)", re.IGNORECASE),
]

KEYWORDS = (
    "mint",
    "presale",
    "fair launch",
    "launch",
    "whitelist",
    "fcfs",
    "ido",
    "tge",
    "claim",
    "snapshot",
    "register",
    "airdrop",
)


@dataclass
class LaunchOpportunity:
    project_twitter: str
    display_name: str
    tweet_id: str
    tweet_url: str
    summary: str
    start_time: str
    end_time: str
    source_account: str
    source_verified: bool
    created_at: str


class LaunchOpportunityScanner:
    def __init__(self, config) -> None:
        self.config = config
        self.client = Client6551(config)
        self.seed_username = "ETH3210"
        self.max_watch_accounts = 30

    async def scan(self) -> list[LaunchOpportunity]:
        if not self.client.is_enabled():
            return [
                LaunchOpportunity(
                    project_twitter="@unknown",
                    display_name="Twitter 数据未启用",
                    tweet_id="",
                    tweet_url="#",
                    summary="未检测到 TWITTER_TOKEN 或 6551 集成未开启，打新机会扫描暂未运行。",
                    start_time="未知",
                    end_time="未知",
                    source_account="system",
                    source_verified=False,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            ]

        watch_accounts = await self._discover_watch_accounts()
        opportunities: list[LaunchOpportunity] = []
        for account in watch_accounts:
            username = account.get("username") or account.get("screen_name") or account.get("twAccount") or ""
            if not username:
                continue
            verified = bool(account.get("verified") or account.get("isVerified") or account.get("userVerified"))
            if not verified:
                continue
            if self._is_stale(account):
                continue
            tweets = await self.client.get_user_tweets(username, max_results=15, product="Latest")
            for row in tweets:
                item = self._extract_opportunity(row, username, verified)
                if item:
                    opportunities.append(item)

        opportunities.sort(key=lambda item: item.created_at, reverse=True)
        dedup: dict[str, LaunchOpportunity] = {}
        for item in opportunities:
            dedup[f"{item.project_twitter}:{item.tweet_id}"] = item
        return list(dedup.values())[:20]

    async def _discover_watch_accounts(self) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = []
        seed_info = await self.client.get_user_info(self.seed_username)
        if seed_info:
            accounts.append(seed_info)
        watch_list = await self.client.get_watch_list()
        for row in watch_list:
            username = str(row.get("twAccount") or row.get("username") or "").strip()
            if not username:
                continue
            if username.lower() == self.seed_username.lower():
                continue
            accounts.append(
                {
                    "username": username,
                    "screen_name": username,
                    "verified": bool(row.get("userVerified") or row.get("verified")),
                    "createdAt": row.get("createdAt") or row.get("updatedAt") or "",
                    "lastActiveAt": row.get("lastActiveAt") or row.get("updatedAt") or "",
                }
            )
        unique: dict[str, dict[str, Any]] = {}
        for item in accounts:
            username = str(item.get("username") or item.get("screen_name") or "").strip().lower()
            if username and username not in unique:
                unique[username] = item
        return list(unique.values())[: self.max_watch_accounts]

    def _is_stale(self, account: dict[str, Any]) -> bool:
        raw = (
            account.get("lastActiveAt")
            or account.get("createdAt")
            or account.get("updatedAt")
            or ""
        )
        dt = self._parse_datetime(raw)
        if not dt:
            return False
        return dt < datetime.now(timezone.utc) - timedelta(days=30)

    def _extract_opportunity(self, row: dict[str, Any], username: str, verified: bool) -> LaunchOpportunity | None:
        text = str(row.get("text") or row.get("content") or "").strip()
        lower = text.lower()
        if not text or not any(keyword in lower for keyword in KEYWORDS):
            return None

        tweet_id = str(row.get("id") or row.get("tweetId") or row.get("twId") or "").strip()
        if not tweet_id:
            return None

        start_time, end_time = self._extract_time_window(text)
        created_at = row.get("createdAt") or datetime.now(timezone.utc).isoformat()
        display_name = str(row.get("userName") or row.get("twUserName") or username).strip()
        summary = text[:180]
        return LaunchOpportunity(
            project_twitter=f"@{username}",
            display_name=display_name or username,
            tweet_id=tweet_id,
            tweet_url=f"https://x.com/{username}/status/{tweet_id}",
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            source_account=username,
            source_verified=verified,
            created_at=created_at,
        )

    def _extract_time_window(self, text: str) -> tuple[str, str]:
        matches: list[str] = []
        for pattern in TIME_PATTERNS:
            matches.extend(match.group(1) for match in pattern.finditer(text))
        if not matches:
            return ("未知", "未知")
        if len(matches) == 1:
            return (matches[0], "未知")
        return (matches[0], matches[1])

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

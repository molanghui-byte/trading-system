from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class DailyDog:
    chain: str
    ca: str
    ath_market_cap: float
    current_market_cap: float
    tags: str
    kol_count: int
    summary: str


class DailyDogScanner:
    def __init__(self) -> None:
        self.cli = self._resolve_cli()
        self.chains = ("bsc", "sol")

    def scan(self) -> list[DailyDog]:
        if not self.cli:
            return [
                DailyDog(
                    chain="SYSTEM",
                    ca="未检测到 gmgn-cli",
                    ath_market_cap=0.0,
                    current_market_cap=0.0,
                    tags="待安装 GMGN",
                    kol_count=0,
                    summary="已接入百倍归零狗筛选逻辑，但当前运行环境未安装 gmgn-cli，暂时无法完成真实链上排查。",
                )
            ]

        dogs: list[DailyDog] = []
        for chain in self.chains:
            rows = self._fetch_trending(chain)
            for row in rows:
                item = self._normalize(chain, row)
                if item:
                    dogs.append(item)

        dogs.sort(key=lambda item: (item.kol_count, item.ath_market_cap), reverse=True)
        dedup: dict[str, DailyDog] = {}
        for item in dogs:
            dedup[f"{item.chain}:{item.ca}"] = item
        return list(dedup.values())[:20]

    def _resolve_cli(self) -> str | None:
        for candidate in (
            shutil.which("gmgn-cli"),
            shutil.which("gmgn-cli.cmd"),
            "/usr/local/bin/gmgn-cli",
            "/usr/bin/gmgn-cli",
            r"C:\Users\Administrator\AppData\Roaming\npm\gmgn-cli.cmd",
            r"C:\Users\Administrator\AppData\Roaming\npm\gmgn-cli",
        ):
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    def _fetch_trending(self, chain: str) -> list[dict[str, Any]]:
        command = [
            self.cli,
            "market",
            "trending",
            "--chain",
            chain,
            "--interval",
            "24h",
            "--order-by",
            "history_highest_market_cap",
            "--direction",
            "desc",
            "--limit",
            "80",
            "--raw",
        ]
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=90,
                check=True,
                env=os.environ.copy(),
            )
        except Exception:
            return []

        payload = self._load_json(proc.stdout)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("data", "list", "rows", "items", "rank", "tokens"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    def _normalize(self, chain: str, row: dict[str, Any]) -> DailyDog | None:
        ca = str(row.get("address") or row.get("token_address") or row.get("base_address") or "").strip()
        if not ca:
            return None

        ath_market_cap = self._to_float(
            row.get("history_highest_market_cap")
            or row.get("ath_market_cap")
            or row.get("highest_market_cap")
            or row.get("historical_high_mc")
        )
        current_market_cap = self._to_float(
            row.get("market_cap")
            or row.get("fdv")
            or row.get("marketcap")
            or row.get("market_cap_usd")
        )
        kol_count = self._to_int(row.get("renowned_count") or row.get("kol_count") or 0)
        smart_count = self._to_int(row.get("smart_degen_count") or 0)

        if ath_market_cap < 1_000_000:
            return None
        if kol_count < 10:
            return None
        if current_market_cap <= 0:
            return None

        name = str(row.get("name") or row.get("symbol") or "").strip()
        launchpad = str(row.get("launchpad") or row.get("launchpad_platform") or "").strip()
        narrative = str(row.get("narrative") or row.get("description") or row.get("concept") or "").strip()
        tags = self._tags(name=name, narrative=narrative, launchpad=launchpad)
        ratio = current_market_cap / ath_market_cap if ath_market_cap else 1.0
        if ratio > 0.35:
            return None

        summary = (
            f"ATH {ath_market_cap:,.0f}，现市值 {current_market_cap:,.0f}，"
            f"KOL {kol_count}，Smart {smart_count}，适合继续跟踪是否出现二次叙事。"
        )
        return DailyDog(
            chain=chain.upper(),
            ca=ca,
            ath_market_cap=ath_market_cap,
            current_market_cap=current_market_cap,
            tags=tags,
            kol_count=kol_count,
            summary=summary,
        )

    @staticmethod
    def _load_json(raw: str) -> Any:
        text = raw.strip()
        if not text:
            return []
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return []

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
    def _tags(*, name: str, narrative: str, launchpad: str) -> str:
        text = " ".join(part for part in (name, narrative, launchpad) if part).lower()
        tags: list[str] = []
        keyword_map = {
            "musk": "马斯克",
            "doge": "狗",
            "dog": "狗",
            "ai": "AI",
            "agent": "AI",
            "pepe": "青蛙",
            "cat": "猫",
            "frog": "青蛙",
            "pump": "发射台",
            "fourmeme": "四狗",
            "sol": "SOL生态",
            "bsc": "BSC生态",
            "base": "Base生态",
            "trump": "政治",
        }
        for keyword, label in keyword_map.items():
            if keyword in text and label not in tags:
                tags.append(label)
        if not tags:
            tags.append("低市值回收")
        return "、".join(tags[:3])

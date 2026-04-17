from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import httpx

from app.config import AppConfig


class Notifier:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.logger = logging.getLogger("trading_system")
        self.logger.setLevel(getattr(logging, config.system.log_level.upper(), logging.INFO))
        if config.notifier.file_enabled and not self.logger.handlers:
            log_path = Path(config.notifier.log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.logger.addHandler(handler)

    async def notify(self, event: str, message: str, detail: Optional[dict] = None) -> None:
        detail = detail or {}
        if self.config.notifier.console_enabled:
            print(f"[{event}] {message}")
        if self.config.notifier.file_enabled:
            self.logger.info("%s %s %s", event, message, json.dumps(detail, ensure_ascii=False))
        if self.config.notifier.telegram_enabled:
            await self._send_telegram(event, message)

    async def _send_telegram(self, event: str, message: str) -> None:
        import os

        token = os.getenv(self.config.notifier.telegram_bot_token_env, "")
        chat_id = os.getenv(self.config.notifier.telegram_chat_id_env, "")
        if not token or not chat_id:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": f"{event}\n{message}"},
            )

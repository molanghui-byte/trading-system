from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.listeners.fourmeme_migration import FourMemeMigrationListener
from app.listeners.fourmemenewpairs import FourMemeNewPairsListener
from app.listeners.twitter6551 import Twitter6551Listener
from app.listeners.volume_spike import VolumeSpikeListener
from app.models import RuntimeState, Signal, SystemLog


class ListenerService:
    def __init__(self, config, notifier, state_machine) -> None:
        self.config = config
        self.notifier = notifier
        self.state_machine = state_machine
        self.listeners = [
            FourMemeNewPairsListener(config),
            Twitter6551Listener(config),
            VolumeSpikeListener(config),
            FourMemeMigrationListener(config),
        ]

    async def poll(self, session) -> None:
        for listener in self.listeners:
            try:
                payloads = await listener.fetch()
                listener_meta = self._extract_listener_meta(payloads)
                diagnostics = listener.diagnostics() if hasattr(listener, "diagnostics") else {}
                for payload in payloads:
                    await self._store_signal(session, listener.name, payload)
                await self._set_listener_state(
                    session,
                    listener.name,
                    {
                        "last_polled_at": datetime.now(timezone.utc).isoformat(),
                        "last_item_count": len(payloads),
                        "last_source_mode": listener_meta["source_mode"],
                        "last_rpc_url": listener_meta["rpc_url"],
                        "last_endpoint": listener_meta["endpoint"],
                        "last_mock_used": listener_meta["mock_used"],
                        "last_error": diagnostics.get("last_rpc_error", ""),
                        "rpc_failure_count": diagnostics.get("rpc_failure_count", 0),
                        "rpc_cooldown_until": diagnostics.get("rpc_cooldown_until", ""),
                    },
                )
            except Exception as exc:
                session.add(
                    SystemLog(
                        event="SYSTEM_ERROR",
                        level="ERROR",
                        message=f"listener {listener.name} failed: {exc}",
                        detail=json.dumps({"listener": listener.name}, ensure_ascii=False),
                    )
                )
                await self.notifier.notify(
                    "SYSTEM_ERROR",
                    f"listener {listener.name} failed: {exc}",
                    {"listener": listener.name},
                )
                await self._set_listener_state(
                    session,
                    listener.name,
                    {
                        "last_polled_at": datetime.now(timezone.utc).isoformat(),
                        "last_item_count": 0,
                        "last_source_mode": "error",
                        "last_rpc_url": "",
                        "last_endpoint": "",
                        "last_mock_used": False,
                        "last_error": str(exc),
                        "rpc_failure_count": 0,
                        "rpc_cooldown_until": "",
                    },
                )

    async def _store_signal(self, session, source: str, payload: dict) -> None:
        signal_id = str(
            payload.get("signal_id")
            or payload.get("id")
            or f"{source}:{payload.get('ca', '')}:{payload.get('discovered_at', '')}"
        )
        exists = await session.execute(select(Signal).where(Signal.signal_id == signal_id))
        if exists.scalar_one_or_none():
            return
        ca = str(payload.get("ca", "")).strip()
        signal = Signal(
            signal_id=signal_id,
            source=source,
            source_type=payload.get("source_type", "listener"),
            source_detail=payload.get("source_detail", ""),
            chain=payload.get("chain", "bsc"),
            ca=ca,
            symbol=payload.get("symbol", ""),
            narrative=payload.get("narrative", ""),
            content=payload.get("content", ""),
            raw_payload=json.dumps(payload.get("raw_item") or payload, ensure_ascii=False),
            signal_score=float(payload.get("signal_score", 0.5)),
            risk_score=float(payload.get("risk_score", 0.0)),
            liquidity=float(payload.get("liquidity", 0.0)),
            market_cap=float(payload.get("market_cap", 0.0)),
            holder_count=int(payload.get("holder_count", 0)),
            top10_rate=float(payload.get("top10_rate", 0.0)),
            bundler_rate=float(payload.get("bundler_rate", 0.0)),
            bot_rate=float(payload.get("bot_rate", 0.0)),
            discovered_at=datetime.fromisoformat(payload.get("discovered_at"))
            if payload.get("discovered_at")
            else datetime.now(timezone.utc),
        )
        session.add(signal)
        await session.flush()
        if not ca:
            await self.state_machine.transition_signal(session, signal, "ERROR", "missing_ca")
            return
        await self.notifier.notify(
            "SIGNAL_FOUND",
            f"signal found {signal.signal_id}",
            {"source": source, "ca": ca},
        )

    async def _set_listener_state(self, session, listener_name: str, payload: dict) -> None:
        key = f"listener:{listener_name}"
        result = await session.execute(select(RuntimeState).where(RuntimeState.state_key == key))
        state = result.scalar_one_or_none()
        if not state:
            session.add(RuntimeState(state_key=key, state_json=json.dumps(payload, ensure_ascii=False)))
            return
        state.state_json = json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _extract_listener_meta(payloads: list[dict[str, Any]]) -> dict[str, Any]:
        if not payloads:
            return {
                "source_mode": "idle",
                "rpc_url": "",
                "endpoint": "",
                "mock_used": False,
            }
        first = payloads[0]
        detail = str(first.get("source_detail") or "")
        raw_item = first.get("raw_item") if isinstance(first.get("raw_item"), dict) else {}
        source_type = str(first.get("source_type") or "")
        return {
            "source_mode": "mock" if bool(raw_item.get("__mock__")) else source_type or "listener",
            "rpc_url": raw_item.get("__rpc_url__", ""),
            "endpoint": detail if source_type == "api" else raw_item.get("__endpoint__", ""),
            "mock_used": bool(raw_item.get("__mock__")),
        }

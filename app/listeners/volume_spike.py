from __future__ import annotations

import json
from pathlib import Path

from app.listeners.base import BaseListener


class VolumeSpikeListener(BaseListener):
    name = "volume_spike"

    async def fetch(self) -> list[dict]:
        listener_cfg = self.config.listeners.get(self.name)
        if not listener_cfg or not listener_cfg.enabled:
            return []
        mock_path = (Path(__file__).resolve().parents[2] / listener_cfg.mock_payload_path).resolve()
        if not listener_cfg.mock_payload_path or not mock_path.exists():
            return []
        rows = json.loads(mock_path.read_text(encoding="utf-8"))
        payloads: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item.setdefault("source_type", "mock")
            item.setdefault("source_detail", "volume_spike:mock")
            item.setdefault("narrative", "volume_spike")
            item.setdefault("content", "volume spike detected")
            item["signal_score"] = max(float(item.get("signal_score", 0.82)), 0.88)
            item["risk_score"] = min(float(item.get("risk_score", 0.18)), 0.18)
            raw_item = item.get("raw_item") if isinstance(item.get("raw_item"), dict) else {}
            raw_item["__mock__"] = True
            raw_item["spike_multiple"] = raw_item.get("spike_multiple", 6.5)
            raw_item["recent_volume_usd"] = raw_item.get("recent_volume_usd", 185000)
            raw_item["baseline_volume_usd"] = raw_item.get("baseline_volume_usd", 22000)
            item["raw_item"] = raw_item
            payloads.append(item)
        return payloads

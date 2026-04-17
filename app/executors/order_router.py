from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1


@dataclass
class RoutedOrder:
    order_id: str
    tx_hash: str
    price: float
    quantity_raw: str
    value_usd: float


class OrderRouter:
    def __init__(self, config) -> None:
        self.config = config

    async def route(self, side: str, ca: str, amount_usd: float, reference_price: float) -> RoutedOrder:
        price = reference_price or 0.000001
        quantity = amount_usd / price if price else 0
        digest = sha1(
            f"{side}:{ca}:{amount_usd}:{datetime.now(timezone.utc).isoformat()}".encode("utf-8")
        ).hexdigest()
        return RoutedOrder(
            order_id=f"{side.lower()}_{digest[:16]}",
            tx_hash=f"paper_{digest[:24]}",
            price=price,
            quantity_raw=str(int(quantity * 10**18)),
            value_usd=amount_usd,
        )

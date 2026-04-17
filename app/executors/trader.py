from __future__ import annotations

from app.executors.buyer import Buyer
from app.executors.order_router import OrderRouter
from app.executors.seller import Seller


class Trader:
    def __init__(self, config, notifier, state_machine) -> None:
        router = OrderRouter(config)
        self.buyer = Buyer(config, notifier, state_machine, router)
        self.seller = Seller(config, notifier, state_machine, router)

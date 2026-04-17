from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import get_config
from app.db import init_db
from app.executors.trader import Trader
from app.instance_lock import InstanceLock
from app.listener_service import ListenerService
from app.managers.candidate_pool import CandidatePoolManager
from app.managers.position_manager import PositionManager
from app.notifier import Notifier
from app.recovery import RecoveryService
from app.risk import RiskManager
from app.scheduler import SchedulerService
from app.state_machine import StateMachine
from app.strategies.bscfourmememvp import BscFourMemeMvpStrategy


async def bootstrap() -> SchedulerService:
    config = get_config()
    notifier = Notifier(config)
    await init_db()
    state_machine = StateMachine(notifier)
    strategy = BscFourMemeMvpStrategy(config)
    risk_manager = RiskManager(config, notifier)
    trader = Trader(config, notifier, state_machine)
    candidate_pool = CandidatePoolManager(config, notifier, state_machine, strategy, risk_manager)
    position_manager = PositionManager(config, notifier, state_machine, trader)
    listener_service = ListenerService(config, notifier, state_machine)
    recovery_service = RecoveryService(notifier, state_machine)
    return SchedulerService(
        config,
        notifier,
        listener_service,
        candidate_pool,
        trader,
        position_manager,
        recovery_service,
        state_machine,
    )


async def main() -> None:
    lock = InstanceLock(Path("data") / "app_main.lock")
    lock.acquire()
    try:
        scheduler = await bootstrap()
        await scheduler.start()
    finally:
        lock.release()


if __name__ == "__main__":
    asyncio.run(main())

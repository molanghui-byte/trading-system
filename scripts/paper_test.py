from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "trading.db"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import bootstrap


TABLES = [
    "candidate_signals",
    "strategy_logs",
    "system_logs",
    "daily_reports",
    "trades",
    "orders",
    "positions",
    "candidates",
    "signals",
    "runtime_state",
]


def reset_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for table in TABLES:
        cur.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()


def collect_summary() -> dict:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    def fetchall(sql: str) -> list[tuple]:
        return list(cur.execute(sql))

    summary = {
        "signals": fetchall(
            "select id, signal_id, processing_status from signals order by id"
        ),
        "candidates": fetchall(
            "select id, candidate_id, status, reject_reason from candidates order by id"
        ),
        "orders": fetchall(
            "select id, order_id, side, status, tx_hash from orders order by id"
        ),
        "positions": fetchall(
            "select id, position_id, status, exit_reason from positions order by id"
        ),
        "trades": fetchall(
            "select id, trade_id, trade_status, pnl_usd, why_exit from trades order by id"
        ),
        "daily_reports": fetchall(
            "select report_date, total_pnl_usd, total_trades, win_rate from daily_reports order by id"
        ),
        "runtime_state": fetchall(
            "select state_key, state_json from runtime_state order by state_key"
        ),
    }
    conn.close()
    return summary


async def run_once(run_seconds: int) -> dict:
    scheduler = await bootstrap()
    task = asyncio.create_task(scheduler.start())
    try:
        await asyncio.sleep(run_seconds)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return collect_summary()


async def main() -> None:
    reset_db()
    rounds: list[dict] = []
    for idx in range(3):
        summary = await run_once(18)
        rounds.append(
            {
                "round": idx + 1,
                "orders": len(summary["orders"]),
                "positions": len(summary["positions"]),
                "trades": len(summary["trades"]),
                "daily_reports": len(summary["daily_reports"]),
                "sell_orders": len([row for row in summary["orders"] if row[2] == "SELL"]),
                "exited_positions": len([row for row in summary["positions"] if row[2] == "EXITED"]),
                "reviewed_trades": len([row for row in summary["trades"] if row[2] == "REVIEWED"]),
                "raw": summary,
            }
        )
    print(json.dumps(rounds, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

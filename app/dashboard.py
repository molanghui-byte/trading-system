from __future__ import annotations

import json
from math import ceil
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select

from app.config import get_config
from app.db import get_session, init_db
from app.daily_dogs import DailyDogScanner
from app.launch_opportunities import LaunchOpportunityScanner
from app.models import Candidate, DailyReport, Order, Position, RuntimeState, Signal, StrategyLog, SystemLog, Trade


BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title="交易系统看板")


@app.on_event("startup")
async def startup() -> None:
    await init_db()


@app.get("/healthz", response_class=JSONResponse)
async def healthz() -> JSONResponse:
    async with get_session() as session:
        signal_count = await session.scalar(select(func.count()).select_from(Signal)) or 0
        distinct_chains = (
            await session.execute(select(Signal.chain).distinct().order_by(Signal.chain.asc()))
        ).scalars().all()
        latest_log = (
            await session.execute(select(SystemLog).order_by(desc(SystemLog.id)).limit(1))
        ).scalar_one_or_none()
    config = get_config()
    return JSONResponse(
        {
            "status": "ok",
            "app": "trading-dashboard",
            "mode": config.system.mode,
            "chain": config.system.chain,
            "chains": distinct_chains or config.system.chains,
            "signal_count": signal_count,
            "latest_system_event": latest_log.event if latest_log else "",
        }
    )


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    signal_page: int = Query(default=1, ge=1),
    position_page: int = Query(default=1, ge=1),
    order_page: int = Query(default=1, ge=1),
    trade_page: int = Query(default=1, ge=1),
    candidate_page: int = Query(default=1, ge=1),
    runtime_page: int = Query(default=1, ge=1),
    system_log_page: int = Query(default=1, ge=1),
    strategy_log_page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    page_size = 5
    config = get_config()
    enabled_wallets = [wallet for wallet in config.wallets if wallet.enabled]
    launch_scanner = LaunchOpportunityScanner(config)
    launch_opportunities = await launch_scanner.scan()
    daily_dogs = DailyDogScanner().scan()

    async with get_session() as session:
        active_position_filter = Position.status.in_(["OPEN", "TP_PENDING", "SL_PENDING", "EXIT_PENDING"])
        counts = {
            "signals": await session.scalar(select(func.count()).select_from(Signal)) or 0,
            "candidates": await session.scalar(select(func.count()).select_from(Candidate)) or 0,
            "orders": await session.scalar(select(func.count()).select_from(Order)) or 0,
            "positions": await session.scalar(select(func.count()).select_from(Position).where(active_position_filter)) or 0,
            "trades": await session.scalar(select(func.count()).select_from(Trade)) or 0,
        }
        totals = {
            "signals": counts["signals"],
            "positions": counts["positions"],
            "orders": counts["orders"],
            "trades": counts["trades"],
            "candidates": counts["candidates"],
            "runtime": await session.scalar(
                select(func.count()).select_from(RuntimeState).where(~RuntimeState.state_key.like("listener:%"))
            ) or 0,
            "system_logs": await session.scalar(select(func.count()).select_from(SystemLog)) or 0,
            "strategy_logs": await session.scalar(select(func.count()).select_from(StrategyLog)) or 0,
        }

        latest_daily_report = (
            await session.execute(select(DailyReport).order_by(desc(DailyReport.report_date)).limit(1))
        ).scalar_one_or_none()
        signals = await _paged(session, Signal, Signal.id, signal_page, page_size)
        positions = await _paged_positions(session, position_page, page_size)
        orders = await _paged(session, Order, Order.id, order_page, page_size)
        trades = await _paged(session, Trade, Trade.id, trade_page, page_size)
        candidates = await _paged(session, Candidate, Candidate.id, candidate_page, page_size)
        runtime_state = await _paged_runtime_state(session, runtime_page, page_size)
        system_logs = await _paged(session, SystemLog, SystemLog.id, system_log_page, page_size)
        strategy_logs = await _paged(session, StrategyLog, StrategyLog.id, strategy_log_page, page_size)
        wallet_state_row = (
            await session.execute(select(RuntimeState).where(RuntimeState.state_key == "wallet_summary"))
        ).scalar_one_or_none()
        wallet_state = _parse_state_json(wallet_state_row.state_json) if wallet_state_row else {}

        realized_pnl = (
            await session.scalar(
                select(func.coalesce(func.sum(Trade.pnl_usd), 0.0)).where(Trade.trade_status.in_(["CLOSED", "REVIEWED"]))
            )
            or 0.0
        )
        unrealized_pnl = (
            await session.scalar(
                select(func.coalesce(func.sum(Position.unrealized_pnl_usd), 0.0)).where(
                    active_position_filter
                )
            )
            or 0.0
        )
        open_position_value = (
            await session.scalar(
                select(func.coalesce(func.sum(Position.current_value), 0.0)).where(
                    active_position_filter
                )
            )
            or 0.0
        )

    starting_balance = sum(wallet.paper_balance_usd for wallet in enabled_wallets)
    total_equity = starting_balance + realized_pnl + unrealized_pnl
    available_cash = total_equity - open_position_value
    wallet_summary = {
        "mode": "模拟盘" if config.system.mode == "paper" else "实盘",
        "chain": " / ".join(chain.upper() for chain in config.system.chains),
        "enabled_wallet_count": len(enabled_wallets),
        "enabled_wallets": enabled_wallets,
        "starting_balance": starting_balance,
        "open_position_value": open_position_value,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "total_equity": total_equity,
        "available_cash": available_cash,
        "updated_at": wallet_state.get("updated_at", ""),
    }

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "counts": counts,
            "latest_daily_report": latest_daily_report,
            "wallet_summary": wallet_summary,
            "signals": signals,
            "positions": positions,
            "orders": orders,
            "launch_opportunities": launch_opportunities,
            "daily_dogs": daily_dogs,
            "trades": trades,
            "candidates": candidates,
            "runtime_state": runtime_state,
            "system_logs": system_logs,
            "strategy_logs": strategy_logs,
            "signal_page": signal_page,
            "position_page": position_page,
            "order_page": order_page,
            "trade_page": trade_page,
            "candidate_page": candidate_page,
            "runtime_page": runtime_page,
            "system_log_page": system_log_page,
            "strategy_log_page": strategy_log_page,
            "signal_has_prev": signal_page > 1,
            "position_has_prev": position_page > 1,
            "order_has_prev": order_page > 1,
            "trade_has_prev": trade_page > 1,
            "candidate_has_prev": candidate_page > 1,
            "runtime_has_prev": runtime_page > 1,
            "system_log_has_prev": system_log_page > 1,
            "strategy_log_has_prev": strategy_log_page > 1,
            "signal_has_next": signal_page * page_size < totals["signals"],
            "position_has_next": position_page * page_size < totals["positions"],
            "order_has_next": order_page * page_size < totals["orders"],
            "trade_has_next": trade_page * page_size < totals["trades"],
            "candidate_has_next": candidate_page * page_size < totals["candidates"],
            "runtime_has_next": runtime_page * page_size < totals["runtime"],
            "system_log_has_next": system_log_page * page_size < totals["system_logs"],
            "strategy_log_has_next": strategy_log_page * page_size < totals["strategy_logs"],
            "signal_total_pages": _total_pages(totals["signals"], page_size),
            "position_total_pages": _total_pages(totals["positions"], page_size),
            "order_total_pages": _total_pages(totals["orders"], page_size),
            "trade_total_pages": _total_pages(totals["trades"], page_size),
            "candidate_total_pages": _total_pages(totals["candidates"], page_size),
            "runtime_total_pages": _total_pages(totals["runtime"], page_size),
            "system_log_total_pages": _total_pages(totals["system_logs"], page_size),
            "strategy_log_total_pages": _total_pages(totals["strategy_logs"], page_size),
            "pretty_json": _pretty_json,
            "build_query": _build_query,
            "zh_status": _zh_status,
            "zh_reason": _zh_reason,
            "zh_source": _zh_source,
            "zh_runtime_key": _zh_runtime_key,
        },
    )


async def _paged(session, model, order_column, page: int, page_size: int):
    result = await session.execute(
        select(model)
        .order_by(desc(order_column))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return result.scalars().all()


async def _paged_runtime_state(session, page: int, page_size: int):
    result = await session.execute(
        select(RuntimeState)
        .where(~RuntimeState.state_key.like("listener:%"))
        .order_by(desc(RuntimeState.updated_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return result.scalars().all()


async def _paged_positions(session, page: int, page_size: int):
    result = await session.execute(
        select(Position)
        .where(Position.status.in_(["OPEN", "TP_PENDING", "SL_PENDING", "EXIT_PENDING"]))
        .order_by(desc(Position.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return result.scalars().all()


def _pretty_json(raw: str) -> str:
    if not raw:
        return ""
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except Exception:
        return raw


def _parse_state_json(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _build_query(**kwargs: int) -> str:
    defaults = {
        "signal_page": 1,
        "position_page": 1,
        "order_page": 1,
        "trade_page": 1,
        "candidate_page": 1,
        "runtime_page": 1,
        "system_log_page": 1,
        "strategy_log_page": 1,
    }
    defaults.update(kwargs)
    return "&".join(f"{key}={value}" for key, value in defaults.items())


def _total_pages(total_rows: int, page_size: int) -> int:
    return max(1, ceil(total_rows / page_size))


def _zh_status(value: str) -> str:
    mapping = {
        "NEW": "新建",
        "LINKED": "已关联",
        "IGNORED": "已忽略",
        "ERROR": "错误",
        "DISCOVERED": "已发现",
        "CHECKED": "已检查",
        "REJECTED": "已拒绝",
        "BUY_PENDING": "待买入",
        "BOUGHT": "已买入",
        "SELL_PENDING": "待卖出",
        "SOLD": "已卖出",
        "FAILED": "失败",
        "PENDING": "待处理",
        "SUBMITTED": "已提交",
        "CONFIRMED": "已确认",
        "TIMEOUT": "超时",
        "CANCELLED": "已取消",
        "OPEN": "持仓中",
        "TP_PENDING": "止盈处理中",
        "SL_PENDING": "止损处理中",
        "EXIT_PENDING": "退出处理中",
        "EXITED": "已退出",
        "FAILED_EXIT": "退出失败",
        "OPENING": "开仓中",
        "CLOSED": "已关闭",
        "REVIEWED": "已复盘",
        "BUY": "买入",
        "SELL": "卖出",
        "INFO": "信息",
        "ERROR_LEVEL": "错误",
        "WARN": "警告",
    }
    return mapping.get(value, value or "—")


def _zh_reason(value: str) -> str:
    mapping = {
        "trailing_stop": "追踪止盈",
        "fixed_take_profit": "固定止盈",
        "fixed_stop_loss": "固定止损",
        "max_hold_timeout": "超时卖出",
        "signal_reverse_exit": "信号反转退出",
        "liquidity_exit_threshold": "流动性阈值退出",
        "signal_cluster_ok": "信号聚合通过",
        "liquidity_too_low": "流动性过低",
        "liquidity_too_high": "流动性过高",
        "bundler_rate_too_high": "打包率过高",
        "bot_rate_too_high": "机器人占比过高",
        "holder_count_too_low": "持有人过少",
        "top10_concentration_too_high": "前十持仓过高",
        "ca_blacklisted": "合约在黑名单",
        "max_concurrent_positions_reached": "达到最大并发持仓",
        "rebuy_cooldown": "重复买入冷却中",
        "loss_pause": "连续亏损暂停",
        "buy_confirmed": "买入确认",
        "missing_ca": "缺少合约地址",
        "signal_score_too_low": "信号分过低",
        "already_holding": "已有持仓",
    }
    return mapping.get(value, value or "—")


def _zh_source(value: str) -> str:
    mapping = {
        "aggregated": "聚合信号",
        "fourmemenewpairs": "FourMeme 新池",
        "fourmeme_migration": "FourMeme 迁移",
        "twitter6551": "Twitter/6551",
        "volume_spike": "放量异动",
        "solnewpairs": "Solana 新池",
    }
    return mapping.get(value, value or "—")


def _zh_runtime_key(value: str) -> str:
    if not value:
        return "—"
    if value.startswith("listener:"):
        suffix = value.split(":", 1)[1]
        return f"监听器 / {_zh_source(suffix)}"
    if value.startswith("order:"):
        return f"订单 / {value.split(':', 1)[1]}"
    if value.startswith("position:"):
        return f"持仓 / {value.split(':', 1)[1]}"
    if value.startswith("daily_report:"):
        return f"日报 / {value.split(':', 1)[1]}"
    if value == "signal_scan_cursor":
        return "信号扫描游标"
    if value == "last_processed_block":
        return "最近处理区块"
    if value == "wallet_summary":
        return "资金概览"
    return value

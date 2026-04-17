from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class SystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_name: str = "bsc-fourmeme-mvp"
    mode: str = "paper"
    chain: str = "bsc"
    chains: list[str] = Field(default_factory=list)
    environment: str = "dev"
    live_enabled: bool = False
    log_level: str = "INFO"

    @model_validator(mode="after")
    def validate_live(self) -> "SystemConfig":
        if self.mode == "live" and not self.live_enabled:
            raise ValueError("live mode requires system.live_enabled=true")
        chain = (self.chain or "bsc").lower()
        self.chain = chain
        normalized = [item.strip().lower() for item in self.chains if item and item.strip()]
        if not normalized:
            normalized = [chain]
        elif chain not in normalized:
            normalized.insert(0, chain)
        self.chains = list(dict.fromkeys(normalized))
        return self


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal_scan_seconds: int = 3
    candidate_process_seconds: int = 2
    order_process_seconds: int = 2
    position_check_seconds: int = 5
    status_report_seconds: int = 60
    daily_report_seconds: int = 86400


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(
        default_factory=lambda: f"sqlite+aiosqlite:///{(DATA_DIR / 'trading.db').as_posix()}"
    )


class WalletEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    address: str
    private_key_env: str = ""
    enabled: bool = True
    paper_balance_usd: float = 1000.0


class NotifierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    console_enabled: bool = True
    file_enabled: bool = True
    telegram_enabled: bool = False
    telegram_bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    telegram_chat_id_env: str = "TELEGRAM_CHAT_ID"
    log_path: str = str(DATA_DIR / "logs" / "system.log")


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_position_usd: float = 100.0
    max_concurrent_positions: int = 2
    rebuy_cooldown_minutes: int = 60
    blacklist_ca: list[str] = Field(default_factory=list)
    blacklist_sources: list[str] = Field(default_factory=list)
    max_retry_count: int = 3
    consecutive_loss_pause_count: int = 3
    pause_minutes: int = 60


class BuyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_usd: float = 25.0


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_token: str = "USDT"
    simulated_slippage_bps: int = 150
    order_timeout_seconds: int = 30
    retry_seconds: int = 2
    max_retries: int = 3
    buy: BuyConfig = Field(default_factory=BuyConfig)


class CandidatePoolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_signal_score: float = 0.1
    max_candidates_per_cycle: int = 20


class Integration6551Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    api_base_url: str = "https://ai.6551.io"
    token_env: str = "TWITTER_TOKEN"
    max_rows: int = 20
    default_keywords: list[str] = Field(default_factory=list)
    default_watch_accounts: list[str] = Field(default_factory=list)
    request_timeout_seconds: int = 15
    use_websocket: bool = False


class ListenerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    endpoint: str = ""
    endpoints: list[str] = Field(default_factory=list)
    rpc_url: str = ""
    rpc_urls: list[str] = Field(default_factory=list)
    contract_address: str = ""
    event_topic: str = ""
    start_block: int = 0
    block_window: int = 500
    polling_seconds: int = 3
    mock_payload_path: str = ""
    timeout_seconds: int = 10
    max_items: int = 50
    rpc_error_cooldown_seconds: int = 30
    use_mock_on_rpc_failure: bool = True
    browser_headers: dict[str, str] = Field(default_factory=dict)
    page_url: str = ""


class StrategyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_liquidity: float = 1000
    max_liquidity: float = 500000
    maxbundlerrate: float = 0.15
    maxbotrate: float = 0.15
    minholdercount: int = 30
    maxtop10rate: float = 0.5
    stoplosspct: float = 0.12
    takeprofitpct: float = 0.25
    trailingstoppct: float = 0.08
    maxholdminutes: int = 45
    signalreverseexit: bool = True
    liquidityexitthreshold: float = 800
    buy: BuyConfig = Field(default_factory=BuyConfig)


class StrategiesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: str = "bscfourmememvp"
    bscfourmememvp: StrategyParams = Field(default_factory=StrategyParams)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system: SystemConfig = Field(default_factory=SystemConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    wallets: list[WalletEntry]
    notifier: NotifierConfig = Field(default_factory=NotifierConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    integration_6551: Integration6551Config = Field(default_factory=Integration6551Config)
    candidate_pool: CandidatePoolConfig = Field(default_factory=CandidatePoolConfig)
    listeners: dict[str, ListenerEntry] = Field(default_factory=dict)
    strategies: StrategiesConfig = Field(default_factory=StrategiesConfig)

    @model_validator(mode="after")
    def validate_wallets(self) -> "AppConfig":
        if not [wallet for wallet in self.wallets if wallet.enabled]:
            raise ValueError("at least one enabled wallet is required")
        return self


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_config_dict() -> dict[str, Any]:
    strategy = _read_yaml(CONFIG_DIR / "strategy.yaml")
    wallets = _read_yaml(CONFIG_DIR / "wallets.yaml")
    risk = _read_yaml(CONFIG_DIR / "risk.yaml")
    merged = _deep_merge(strategy, {"wallets": wallets.get("wallets", [])})
    merged = _deep_merge(merged, {"risk": risk.get("risk", {})})
    mode = os.getenv("APP_MODE")
    if mode:
        merged.setdefault("system", {})["mode"] = mode
    chain = os.getenv("APP_CHAIN") or os.getenv("CHAIN_OVERRIDE")
    if chain:
        merged.setdefault("system", {})["chain"] = chain
    chains = os.getenv("APP_CHAINS")
    if chains:
        merged.setdefault("system", {})["chains"] = [item.strip() for item in chains.split(",") if item.strip()]
    app_name = os.getenv("APP_NAME")
    if app_name:
        merged.setdefault("system", {})["app_name"] = app_name
    live_enabled = os.getenv("LIVE_ENABLED")
    if live_enabled:
        merged.setdefault("system", {})["live_enabled"] = live_enabled.lower() == "true"
    return merged


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig.model_validate(_load_config_dict())

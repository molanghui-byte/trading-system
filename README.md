# Multi-Chain Paper Trading Dashboard

Event-driven paper trading MVP for multi-chain meme signal flow:

`signal -> candidate -> strategy -> order -> position -> exit -> review`

## Implemented

- Async runtime with SQLite and SQLAlchemy ORM
- YAML + environment config loading with live-mode hard gate
- Strict state machine with logged transitions
- Listener service with working `fourmemenewpairs` and `solnewpairs` ingestion
- Candidate pool generation and signal linking
- Single config-driven MVP strategy
- Risk checks for blacklist, cooldown, concurrent positions, and loss pause
- Paper buy/sell execution with idempotency keys
- Position management with stop loss, take profit, timeout, and trailing stop
- Recovery bootstrap for pending orders and open positions
- Daily report and trade review jobs
- Chain-scoped worker locks so BSC and SOL paper workers can run side by side against the same SQLite database

## Run

1. Use Python 3.11+
2. Install dependencies:

```bash
pip install -r requirements.txt
```

`pydantic>=2.12` is used so Windows + Python 3.14 environments can install prebuilt wheels cleanly.

3. Start:

```bash
python -m app.main
```

Run a specific chain worker:

```bash
APP_CHAIN=bsc python -m app.main_chain
APP_CHAIN=sol python -m app.main_chain
APP_CHAIN=eth python -m app.main_chain
```

## Dashboard

Local dashboard:

```bash
python -m uvicorn app.dashboard:app --host 127.0.0.1 --port 8050
```

Production-style multi-process startup:

```bash
python start_multi_chain.py
```

Health check:

```text
/healthz
```

Deployment artifacts:

- `deploy_dashboard.ps1`
- `deploy_dashboard.bat`
- `Dockerfile`
- `docker-compose.yml`
- `deploy/nginx/trading-dashboard.conf`
- `DEPLOYMENT.md`

## Notes

- Default mode is `paper`
- Live mode requires `APP_MODE=live` and `LIVE_ENABLED=true`
- `data/mock_signals.json` and `data/mock_signals_sol.json` are included so the first boot can walk through both BSC and SOL paper pipelines
- `fourmemenewpairs` now supports real HTTP polling via `listeners.fourmemenewpairs.endpoint` or `endpoints`; if the live source returns nothing, it falls back to the mock file
- `fourmemenewpairs` also supports direct BSC RPC event polling via `rpc_url + CA + event_topic`, which is a more stable production path than scraping a frontend API
- `ethnewpairs` supports direct Ethereum RPC polling for Uniswap V2 `PairCreated` logs, plus optional HTTP endpoint ingestion
- `twitter6551` can now be enabled as a read-only signal source backed by the 6551 Twitter/X API, using `integration_6551.token_env` for the bearer token
- Listener polling metadata is persisted in `runtime_state` under keys like `listener:fourmemenewpairs`
- `app.main_chain` writes chain-specific lock files like `data/app_main_bsc.lock` and `data/app_main_sol.lock`

## 6551 Integration

The project now includes a safe 6551 client skeleton in [client_6551.py](c:\Users\Administrator\Desktop\DEV\trading-system\app\integrations\client_6551.py) and a Twitter/X signal listener in [twitter6551.py](c:\Users\Administrator\Desktop\DEV\trading-system\app\listeners\twitter6551.py).

To enable it:

1. Set the token in your shell:

```powershell
$env:TWITTER_TOKEN = "your-token"
```

2. In [strategy.yaml](c:\Users\Administrator\Desktop\DEV\trading-system\config\strategy.yaml):
   - set `integration_6551.enabled: true`
   - set `listeners.twitter6551.enabled: true`
   - optionally populate `integration_6551.default_keywords`
   - optionally populate `integration_6551.default_watch_accounts`

This integration is read-only right now. It does not place trades and does not write remote watch settings.

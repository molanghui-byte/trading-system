# Deployment Guide

This project runs a paper-trading dashboard and optional multi-chain workers. The commands below assume Python 3.11+ and Docker are available.

## Local Run

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Start the dashboard:

```bash
python -m uvicorn app.dashboard:app --host 127.0.0.1 --port 8050
```

Open:

```text
http://127.0.0.1:8050
```

Start the multi-chain workers in a separate terminal when needed:

```bash
python start_multi_chain.py
```

## Docker

Build the image:

```bash
docker build -t trading-system .
```

Run the dashboard:

```bash
docker run --rm -p 8050:8050 --env-file .env trading-system
```

If the app binds to `127.0.0.1` inside Docker, change the container command or environment to use `0.0.0.0` so the port is reachable from the host.

## Docker Compose

Copy the example environment file and adjust values:

```bash
cp .env.example .env
```

Start services:

```bash
docker compose up --build
```

Stop services:

```bash
docker compose down
```

## Data Persistence

Keep SQLite databases, lock files, and logs out of git. Recommended local paths:

```text
data/
logs/
```

For production-like deployments, mount `data/` as a persistent volume so paper-trading history survives container restarts.

## Configuration

Risk and strategy defaults live in:

```text
config/risk.yaml
config/strategy.yaml
```

Review these files before running workers. Keep all private keys, API tokens, and paid RPC endpoints in environment variables or secret managers, not in YAML committed to git.

## Health Checks

Recommended checks:

```bash
python -m compileall app scripts start_multi_chain.py
curl -fsS http://127.0.0.1:8050/healthz
```

The included Docker and Compose examples call `/healthz` from inside the container.

## Operational Notes

- This is a paper-trading system; do not connect it to real trading keys without adding authentication, audit logging, and strict risk controls.
- Keep worker lock files in `data/` or another runtime directory.
- Run only one worker instance per chain unless the locking behavior has been verified.
- Back up the SQLite database before changing schemas or upgrading long-running deployments.

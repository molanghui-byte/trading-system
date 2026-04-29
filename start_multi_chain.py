from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _spawn(command: list[str], env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(command, cwd=BASE_DIR, env=env)


def main() -> int:
    port = os.getenv("PORT", "8050")
    chains = [
        chain.strip().lower()
        for chain in os.getenv("APP_CHAINS", "bsc,sol,eth").split(",")
        if chain.strip()
    ]
    base_env = os.environ.copy()
    processes: list[subprocess.Popen] = []
    try:
        dashboard_env = base_env.copy()
        processes.append(
            _spawn(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.dashboard:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    port,
                    "--workers",
                    "1",
                    "--proxy-headers",
                ],
                dashboard_env,
            )
        )

        for chain in chains:
            worker_env = base_env.copy()
            worker_env["APP_CHAIN"] = chain
            worker_env["APP_NAME"] = f"trading-system-{chain}"
            processes.append(_spawn([sys.executable, "-m", "app.main_chain"], worker_env))

        while True:
            for proc in processes:
                code = proc.poll()
                if code is not None:
                    return code
            time.sleep(2)
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        deadline = time.time() + 10
        for proc in processes:
            if proc.poll() is None:
                timeout = max(0.0, deadline - time.time())
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
        for proc in processes:
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())

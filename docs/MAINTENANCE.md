# Maintenance Checklist

Use this checklist before merging changes or deploying a new version.

## Before Commit

```bash
python -m compileall app scripts start_multi_chain.py
docker build -t trading-system:local .
```

If you add tests later, run:

```bash
pytest
```

## Repository Hygiene

- Keep generated data out of git: SQLite databases, lock files, logs, caches, and local virtual environments.
- Keep `.env` private and commit only `.env.example`.
- Keep deployment documentation encoded as UTF-8. The previous `DEPLOYMENT.md` appears garbled on GitHub and should be replaced.
- Prefer small pull requests that separate trading logic changes from UI/documentation changes.

## Safety Boundaries

- Treat all strategies as paper trading unless there is a reviewed production integration.
- Do not store wallet private keys, exchange keys, or paid RPC keys in committed files.
- Add request authentication before exposing the dashboard beyond localhost or a private network.
- Add backup/restore instructions before relying on the SQLite database for long-running history.

## Suggested Next Improvements

1. Add unit tests around order simulation, balance updates, and risk limits.
2. Add a test or smoke check that verifies `/healthz`.
3. Add structured logging for worker startup, shutdown, and chain-specific failures.
4. Add a schema migration tool if the database tables evolve.
5. Add type checking with `mypy` or linting with `ruff` after the codebase is stable.

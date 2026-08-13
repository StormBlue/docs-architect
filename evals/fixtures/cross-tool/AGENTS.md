# Ledger Service for Codex

The service is a Python application. The source lives under `src/`, requests enter through
`src/app.py`, and balances are computed in `src/ledger.py`. The API accepts ledger entries and
returns account balances. Keep route handlers small, never use floating point arithmetic for
money, and update the architecture whenever a module moves.

## Commands

Run `python -m unittest discover -s tests` before handing off a change.

## Documentation

Read [the architecture](ARCHITECTURE.md) and [the documentation index](docs/index.md).

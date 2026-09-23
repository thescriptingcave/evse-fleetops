#!/usr/bin/env python3
"""Standalone Couchbase schema + seed provisioning.

Usage:
    EVSE_CB_HOST=localhost EVSE_CB_USERNAME=Administrator EVSE_CB_PASSWORD=password \
        python scripts/bootstrap.py
Idempotent: safe to run repeatedly.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.bootstrap import run_cli  # noqa: E402

if __name__ == "__main__":
    run_cli()
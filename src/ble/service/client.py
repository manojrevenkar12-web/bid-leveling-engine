"""Talk to the platform API (the TypeScript service that stores runs and review decisions)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx


def _headers(key: str | None) -> dict[str, str]:
    k = key or os.environ.get("BLE_PLATFORM_KEY", "")
    return {"X-API-Key": k} if k else {}


def publish(run_json: Path, api: str, key: str | None = None) -> dict[str, Any]:
    body = json.loads(run_json.read_text(encoding="utf-8"))
    r = httpx.post(f"{api.rstrip('/')}/api/runs", json=body, headers=_headers(key), timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_run(tender_id: str, api: str, key: str | None = None) -> dict[str, Any]:
    r = httpx.get(f"{api.rstrip('/')}/api/tenders/{tender_id}/export", headers=_headers(key), timeout=30)
    r.raise_for_status()
    return r.json()

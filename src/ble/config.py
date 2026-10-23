"""Paths and cached configuration."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("BLE_ROOT", Path(__file__).resolve().parents[2]))
CONFIG = ROOT / "config"
WORLD = ROOT / "world"
DATA = Path(os.environ.get("BLE_DATA", ROOT / "data"))
TRUTH = Path(os.environ.get("BLE_TRUTH", ROOT / "truth"))
REPORTS = Path(os.environ.get("BLE_REPORTS", ROOT / "reports"))
MODELS = Path(os.environ.get("BLE_MODELS", ROOT / "models"))


@cache
def load(name: str) -> dict[str, Any]:
    """config/<name>.yaml"""
    return yaml.safe_load((CONFIG / f"{name}.yaml").read_text(encoding="utf-8"))


@cache
def world(name: str) -> dict[str, Any]:
    """world/<name>.yaml (simulator only)"""
    return yaml.safe_load((WORLD / f"{name}.yaml").read_text(encoding="utf-8"))

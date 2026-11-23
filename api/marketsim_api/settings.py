"""API settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _origins() -> list[str]:
    raw = os.environ.get("MARKETSIM_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("MARKETSIM_DATA_DIR", "runs")).resolve()
    )
    cors_origins: list[str] = field(default_factory=_origins)
    log_level: str = field(default_factory=lambda: os.environ.get("MARKETSIM_LOG_LEVEL", "INFO"))
    log_json: bool = field(default_factory=lambda: os.environ.get("MARKETSIM_LOG_JSON", "1") != "0")

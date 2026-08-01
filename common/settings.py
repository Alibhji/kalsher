from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FilterSettings(BaseSettings):
    max_hours_to_close: float = 3.0
    max_duration_hours: float = 3.0
    category_allowlist: list[str] = Field(default_factory=list)
    series_allowlist: list[str] = Field(default_factory=list)
    live_event_only: bool = True
    enabled_filters: list[str] = Field(
        default_factory=lambda: ["status_active", "time_to_close", "market_duration"]
    )


class FetcherSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    kalshi_key_id: str = ""
    kalshi_private_key_path: str = "/run/secrets/kalshi_private_key.pem"
    kalshi_rest_base: str = "https://demo-api.kalshi.co/trade-api/v2"
    kalshi_ws_url: str = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
    kalshi_ws_path: str = "/trade-api/ws/v2"

    redis_url: str = "redis://redis:6379/0"
    timescale_dsn: str = "postgresql://kalshi:kalshi@timescaledb:5432/kalshi"

    config_path: str = "config.yaml"
    debug: bool = False
    log_level: str = "INFO"
    metrics_port: int = 8080

    discovery_interval_sec: float = 30.0
    rest_rps: float = 10.0
    ws_shards: int = 4
    ws_queue_size: int = 10_000
    sink_batch_size: int = 1000
    sink_flush_ms: float = 100.0
    ui_fanout: bool = True

    filters: FilterSettings = Field(default_factory=FilterSettings)

    @classmethod
    def load(cls, config_path: str | None = None) -> "FetcherSettings":
        path = Path(config_path or "config.yaml")
        yaml_data: dict[str, Any] = {}
        if path.exists():
            with path.open() as f:
                yaml_data = yaml.safe_load(f) or {}
        filters_data = yaml_data.pop("filters", None) or {}
        if filters_data:
            yaml_data["filters"] = FilterSettings(**filters_data)
        return cls(**yaml_data)


class UiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    redis_url: str = "redis://redis:6379/0"
    timescale_dsn: str = "postgresql://kalshi:kalshi@timescaledb:5432/kalshi"
    debug: bool = False
    port: int = 8090
    kalshi_web_base: str = "https://kalshi.com"
    drop_no_liquidity: bool = True
    live_only: bool = True
    archive_default_limit: int = 30
    list_flush_ms: float = 50
    market_flush_ms: float = 0
    trade_ring_size: int = 200
    history_windows: list[str] = Field(default_factory=lambda: ["5m", "15m", "1h"])
    symbol_map: dict[str, str] = Field(
        default_factory=lambda: {
            "KXBTC15M": "BRTI",
            "KXBTCD": "BRTI",
            "KXETH15M": "ETHUSDRTI",
            "KXETHD": "ERTI",
            "KXDOGE15M": "DOGEUSDRTI",
            "KXBNB15M": "BNBUSDRTI",
            "KXSOL15M": "SOLUSDRTI",
            "KXSOLD": "SOLUSD_RTI",
            "KXHYPE15M": "HYPEUSDRTI",
            "KXXRP15M": "XRPUSDRTI",
        }
    )
    trader_url: str = "http://trader:8091"

    @classmethod
    def load(cls, config_path: str | None = None) -> "UiSettings":
        path = Path(config_path or "ui/config.yaml")
        yaml_data: dict[str, Any] = {}
        if path.exists():
            with path.open() as f:
                yaml_data = yaml.safe_load(f) or {}
        return cls(**yaml_data)


class TraderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    kalshi_key_id: str = ""
    kalshi_private_key_path: str = "/run/secrets/kalshi.pem"
    kalshi_rest_base: str = "https://api.elections.kalshi.com/trade-api/v2"
    redis_url: str = "redis://redis:6379/0"
    timescale_dsn: str = "postgresql://kalshi:kalshi@timescaledb:5432/kalshi"
    debug: bool = False
    port: int = 8091
    trading_live_enabled: bool = False
    mark_interval_sec: float = 1.0
    rest_rps: float = 10.0

    @classmethod
    def load(cls, config_path: str | None = None) -> "TraderSettings":
        path = Path(config_path or "trader/config.yaml")
        yaml_data: dict[str, Any] = {}
        if path.exists():
            with path.open() as f:
                yaml_data = yaml.safe_load(f) or {}
        return cls(**yaml_data)

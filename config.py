from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_secret(name: str, default: str = "") -> str:
    """Read a secret without ever embedding it in source code."""
    value = os.getenv(name)
    if value:
        return value

    secret_path = BASE_DIR / ".streamlit" / "secrets.toml"
    try:
        with secret_path.open("rb") as file:
            secret = tomllib.load(file).get(name, default)
        if secret:
            return str(secret)
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        pass

    try:
        import streamlit as st

        secret = st.secrets.get(name, default)
        return str(secret) if secret else default
    except Exception:
        return default


@dataclass(frozen=True)
class AppConfig:
    db_path: Path = Path(
        os.getenv("FUND_MANAGER_DB", str(BASE_DIR / "data" / "fund_manager.db"))
    )
    price_lookback_days: int = int(os.getenv("PRICE_LOOKBACK_DAYS", "800"))
    max_workers: int = int(os.getenv("SCAN_MAX_WORKERS", "6"))
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "12"))
    verify_ssl: bool = _env_bool("VERIFY_SSL", True)

    # Universe safety filters. A value of 0 disables the corresponding filter.
    min_market_cap: float = float(os.getenv("MIN_MARKET_CAP", "50000000000"))
    min_daily_amount: float = float(os.getenv("MIN_DAILY_AMOUNT", "1000000000"))

    # Backtest assumptions are round-trip costs in basis points.
    commission_bps: float = float(os.getenv("COMMISSION_BPS", "15"))
    slippage_bps: float = float(os.getenv("SLIPPAGE_BPS", "10"))
    holding_days: int = int(os.getenv("HOLDING_DAYS", "5"))

    # Portfolio risk policy.
    account_equity: float = float(os.getenv("ACCOUNT_EQUITY", "100000000"))
    risk_per_trade: float = float(os.getenv("RISK_PER_TRADE", "0.0075"))
    max_position_pct: float = float(os.getenv("MAX_POSITION_PCT", "0.15"))
    max_sector_pct: float = float(os.getenv("MAX_SECTOR_PCT", "0.30"))
    max_portfolio_risk: float = float(os.getenv("MAX_PORTFOLIO_RISK", "0.04"))
    liquidity_participation: float = float(os.getenv("LIQUIDITY_PARTICIPATION", "0.02"))

    groq_model: str = field(
        default_factory=lambda: get_secret("GROQ_MODEL", "llama-3.3-70b-versatile")
    )
    benchmark_kospi: str = os.getenv("BENCHMARK_KOSPI", "KS11")
    benchmark_kosdaq: str = os.getenv("BENCHMARK_KOSDAQ", "KQ11")

    @property
    def groq_api_key(self) -> str:
        return get_secret("GROQ_API_KEY") or get_secret("GSK_API_TOKEN")

    @property
    def dart_api_key(self) -> str:
        return get_secret("DART_API_KEY")

    @property
    def krx_ready(self) -> bool:
        return bool(get_secret("KRX_ID") and get_secret("KRX_PW"))

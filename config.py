from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
GROQ_RETIRED_MODELS = {"llama-3.3-70b-versatile", "llama-3.1-8b-instant"}


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


def _groq_model() -> str:
    configured = get_secret("GROQ_MODEL", GROQ_DEFAULT_MODEL)
    return GROQ_DEFAULT_MODEL if configured in GROQ_RETIRED_MODELS else configured


@dataclass(frozen=True)
class AppConfig:
    db_path: Path = Path(
        os.getenv("FUND_MANAGER_DB", str(BASE_DIR / "data" / "fund_manager.db"))
    )
    price_lookback_days: int = int(os.getenv("PRICE_LOOKBACK_DAYS", "800"))
    max_workers: int = int(os.getenv("SCAN_MAX_WORKERS", "6"))
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "12"))
    verify_ssl: bool = _env_bool("VERIFY_SSL", True)
    news_detail_limit: int = int(os.getenv("NEWS_DETAIL_LIMIT", "3"))
    us_universe_pages: int = int(os.getenv("US_UNIVERSE_PAGES", "10"))
    sec_user_agent: str = os.getenv(
        "SEC_USER_AGENT",
        "EvidenceFirstFundManager/1.0 jjh4075161@gmail.com",
    )

    # Universe safety filters. A value of 0 disables the corresponding filter.
    min_market_cap: float = float(os.getenv("MIN_MARKET_CAP", "50000000000"))
    min_daily_amount: float = float(os.getenv("MIN_DAILY_AMOUNT", "1000000000"))
    us_min_market_cap: float = float(os.getenv("US_MIN_MARKET_CAP", "5000000000"))
    us_min_daily_amount: float = float(os.getenv("US_MIN_DAILY_AMOUNT", "20000000"))

    # Backtest assumptions are round-trip costs in basis points.
    commission_bps: float = float(os.getenv("COMMISSION_BPS", "15"))
    slippage_bps: float = float(os.getenv("SLIPPAGE_BPS", "10"))
    holding_days: int = int(os.getenv("HOLDING_DAYS", "5"))

    # Portfolio risk policy.
    account_equity: float = float(os.getenv("ACCOUNT_EQUITY", "100000000"))
    account_equity_usd: float = float(os.getenv("ACCOUNT_EQUITY_USD", "100000"))
    risk_per_trade: float = float(os.getenv("RISK_PER_TRADE", "0.0075"))
    max_position_pct: float = float(os.getenv("MAX_POSITION_PCT", "0.15"))
    max_sector_pct: float = float(os.getenv("MAX_SECTOR_PCT", "0.30"))
    max_portfolio_risk: float = float(os.getenv("MAX_PORTFOLIO_RISK", "0.04"))
    liquidity_participation: float = float(os.getenv("LIQUIDITY_PARTICIPATION", "0.02"))

    groq_model: str = field(
        default_factory=_groq_model
    )
    benchmark_kospi: str = os.getenv("BENCHMARK_KOSPI", "KS11")
    benchmark_kosdaq: str = os.getenv("BENCHMARK_KOSDAQ", "KQ11")
    benchmark_us: str = os.getenv("BENCHMARK_US", "SPY")

    @property
    def groq_api_key(self) -> str:
        return get_secret("GROQ_API_KEY") or get_secret("GSK_API_TOKEN")

    @property
    def dart_api_key(self) -> str:
        return get_secret("DART_API_KEY")

    @property
    def krx_ready(self) -> bool:
        return bool(get_secret("KRX_ID") and get_secret("KRX_PW"))

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


FACTOR_WEIGHTS = {
    "balanced": {
        "value_score": 0.18,
        "momentum_score": 0.24,
        "flow_score": 0.16,
        "quality_score": 0.20,
        "volatility_score": 0.12,
        "news_score": 0.10,
    },
    "rebound": {
        "value_score": 0.15,
        "momentum_score": 0.32,
        "flow_score": 0.16,
        "quality_score": 0.15,
        "volatility_score": 0.12,
        "news_score": 0.10,
    },
    "breakout": {
        "value_score": 0.10,
        "momentum_score": 0.38,
        "flow_score": 0.18,
        "quality_score": 0.12,
        "volatility_score": 0.12,
        "news_score": 0.10,
    },
}


def calculate_indicators(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw.copy()
    df = raw.copy().sort_values("Date").reset_index(drop=True)
    for column in ["Open", "High", "Low", "Close", "Volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    close = df["Close"]
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["RSI14"] = 100 - (100 / (1 + rs))
    df.loc[(loss == 0) & (gain > 0), "RSI14"] = 100

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()

    for window in [20, 50, 60, 120, 200]:
        df[f"MA{window}"] = close.rolling(window).mean()
    std20 = close.rolling(20).std()
    df["BBU"] = df["MA20"] + 2 * std20
    df["BBL"] = df["MA20"] - 2 * std20

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - previous_close).abs(),
            (df["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["ATR14"] = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    df["ATR_PCT"] = df["ATR14"] / close * 100

    returns = close.pct_change()
    df["VOLATILITY20"] = returns.rolling(20).std() * math.sqrt(252) * 100
    df["AVG_VOLUME20"] = df["Volume"].shift(1).rolling(20).mean()
    df["AVG_AMOUNT20"] = (close * df["Volume"]).shift(1).rolling(20).mean()
    df["VOLUME_RATIO"] = df["Volume"] / df["AVG_VOLUME20"].replace(0, np.nan)
    for window in [5, 20, 60, 120]:
        df[f"MOMENTUM{window}"] = close.pct_change(window) * 100
    rolling_high = close.shift(1).rolling(120).max()
    rolling_peak = close.rolling(120, min_periods=20).max()
    df["HIGH_DISTANCE120"] = (close / rolling_high - 1) * 100
    df["DRAWDOWN120"] = (close / rolling_peak - 1) * 100
    df["RECENT_LOW20"] = df["Low"].shift(1).rolling(20).min()
    return df.replace([np.inf, -np.inf], np.nan)


def score_stock(
    market_row: dict[str, Any],
    prices: pd.DataFrame,
    fundamental: dict[str, Any] | None,
    flow: dict[str, Any] | None,
    news: dict[str, Any] | None,
    disclosures: dict[str, Any] | None,
    strategy: str = "balanced",
) -> dict[str, Any]:
    strategy = strategy if strategy in FACTOR_WEIGHTS else "balanced"
    indicators = calculate_indicators(prices)
    ticker = str(market_row["ticker"])
    reasons: list[str] = []
    facts: dict[str, Any] = {
        "price_source": "FinanceDataReader",
        "price_as_of": None,
        "fundamental_status": (fundamental or {}).get("status", "unavailable"),
        "fundamental_period": None,
        "flow_status": (flow or {}).get("status", "unavailable"),
        "flow_source": (flow or {}).get("source"),
        "flow_observations": (flow or {}).get("observations"),
        "flow_value_method": (
            "official KRX net trading value"
            if str((flow or {}).get("source", "")).startswith("pykrx")
            else "estimated net value = net shares x daily close"
            if (flow or {}).get("status") == "ok"
            else None
        ),
        "news_status": (news or {}).get("status", "unavailable"),
        "news_count": len((news or {}).get("news", [])),
        "news_detail_coverage": (news or {}).get("article_detail_coverage"),
        "disclosure_status": (disclosures or {}).get("status", "unavailable"),
        "disclosure_count": len((disclosures or {}).get("items", [])),
    }

    if indicators.empty or len(indicators) < 120:
        return _empty_score(ticker, market_row, "가격 이력 120거래일 미만")

    latest = indicators.iloc[-1]
    facts.update(
        {
            "price_as_of": pd.Timestamp(latest["Date"]).date().isoformat(),
            "current_price": _finite(latest["Close"]),
            "rsi14": _finite(latest["RSI14"]),
            "macd": _finite(latest["MACD"]),
            "macd_signal": _finite(latest["MACD_SIGNAL"]),
            "atr14": _finite(latest["ATR14"]),
            "atr_pct": _finite(latest["ATR_PCT"]),
            "momentum20": _finite(latest["MOMENTUM20"]),
            "momentum60": _finite(latest["MOMENTUM60"]),
            "momentum120": _finite(latest["MOMENTUM120"]),
            "volume_ratio": _finite(latest["VOLUME_RATIO"]),
            "avg_amount20": _finite(latest["AVG_AMOUNT20"]),
            "volatility20": _finite(latest["VOLATILITY20"]),
            "drawdown120": _finite(latest["DRAWDOWN120"]),
            "recent_low20": _finite(latest["RECENT_LOW20"]),
        }
    )

    value_score = _value_score(fundamental)
    quality_score = _quality_score(fundamental)
    momentum_score = _momentum_score(latest, strategy)
    flow_score = _flow_score(flow, latest)
    volatility_score = _volatility_score(latest)
    news_score = _news_score(news)

    factor_scores = {
        "value_score": value_score,
        "momentum_score": momentum_score,
        "flow_score": flow_score,
        "quality_score": quality_score,
        "volatility_score": volatility_score,
        "news_score": news_score,
    }
    weights = FACTOR_WEIGHTS[strategy]
    available_weight = sum(weights[key] for key, value in factor_scores.items() if value is not None)
    weighted = sum(
        weights[key] * value
        for key, value in factor_scores.items()
        if value is not None
    )
    raw_total = weighted / available_weight if available_weight else 0.0

    completeness = 0.35
    if fundamental and fundamental.get("status") == "ok":
        completeness += 0.25
        facts["fundamental_period"] = fundamental.get("period")
        facts["fundamentals"] = {
            key: fundamental.get(key)
            for key in [
                "per", "pbr", "roe", "debt_ratio", "operating_margin",
                "revenue_growth", "operating_profit_growth", "net_income_growth",
            ]
        }
    if flow and flow.get("status") == "ok":
        completeness += 0.15
        facts["foreign_net"] = flow.get("foreign_net")
        facts["institution_net"] = flow.get("institution_net")
        facts["foreign_net_shares"] = flow.get("foreign_net_shares")
        facts["institution_net_shares"] = flow.get("institution_net_shares")
    if news and news.get("status") in {"ok", "partial"}:
        completeness += 0.15
        facts["news"] = news.get("news", [])[:5]
    if disclosures and disclosures.get("status") == "ok":
        completeness += 0.10
        facts["disclosures"] = disclosures.get("items", [])[:5]
    completeness = round(min(completeness, 1.0), 3)

    # Missing evidence cannot improve a score simply through weight redistribution.
    total_score = raw_total * (0.72 + 0.28 * completeness)
    eligible = True
    if _finite(latest["Close"]) is None or latest["Close"] <= 0:
        eligible = False
        reasons.append("유효한 현재가 없음")
    if _finite(latest["AVG_AMOUNT20"]) is None or latest["AVG_AMOUNT20"] <= 0:
        eligible = False
        reasons.append("20일 평균 거래대금 없음")
    if completeness < 0.50:
        reasons.append("재무·수급·뉴스 근거가 부족함")

    reasons.extend(_factor_reasons(latest, fundamental, flow, news, strategy))
    return {
        "ticker": ticker,
        "name": market_row.get("name", ticker),
        "market": market_row.get("market", ""),
        "sector": market_row.get("sector", "미분류"),
        "industry": market_row.get("industry", "미분류"),
        "total_score": round(float(total_score), 2),
        **{key: round(value, 2) if value is not None else None for key, value in factor_scores.items()},
        "data_completeness": completeness,
        "eligible": eligible,
        "reasons": reasons,
        "facts": facts,
        "indicators": indicators,
    }


def _value_score(fundamental: dict[str, Any] | None) -> float | None:
    if not fundamental or fundamental.get("status") != "ok":
        return None
    parts = []
    per = _finite(fundamental.get("per"))
    pbr = _finite(fundamental.get("pbr"))
    if per is not None:
        parts.append(_linear(per, 5, 35, 100, 15) if per > 0 else 0)
    if pbr is not None:
        parts.append(_linear(pbr, 0.5, 5, 100, 10) if pbr > 0 else 0)
    return _mean(parts)


def _quality_score(fundamental: dict[str, Any] | None) -> float | None:
    if not fundamental or fundamental.get("status") != "ok":
        return None
    parts = []
    mappings = [
        ("roe", -5, 20, 0, 100),
        ("operating_margin", -5, 25, 0, 100),
        ("revenue_growth", -20, 25, 0, 100),
    ]
    for key, low, high, low_score, high_score in mappings:
        value = _finite(fundamental.get(key))
        if value is not None:
            parts.append(_linear(value, low, high, low_score, high_score))
    debt = _finite(fundamental.get("debt_ratio"))
    if debt is not None:
        parts.append(_linear(debt, 20, 200, 100, 0))
    return _mean(parts)


def _momentum_score(latest: pd.Series, strategy: str) -> float:
    rsi = _finite(latest.get("RSI14")) or 50
    macd_positive = latest.get("MACD", 0) > latest.get("MACD_SIGNAL", 0)
    if strategy == "rebound":
        rsi_score = 100 - min(abs(rsi - 35) * 4, 100)
        bbl_gap = (latest.get("Close") / latest.get("BBL") - 1) * 100 if latest.get("BBL", 0) else 0
        return _mean(
            [
                rsi_score,
                80 if macd_positive else 25,
                _linear(bbl_gap, -3, 15, 95, 20),
                _linear(latest.get("MOMENTUM5", 0), -8, 8, 10, 100),
            ]
        ) or 0
    if strategy == "breakout":
        above_band = latest.get("Close", 0) >= latest.get("BBU", float("inf"))
        return _mean(
            [
                _linear(latest.get("VOLUME_RATIO", 0), 0.8, 4, 10, 100),
                95 if above_band else 30,
                _linear(latest.get("MOMENTUM20", 0), -10, 30, 10, 100),
                80 if macd_positive else 25,
            ]
        ) or 0
    trend_parts = [
        _linear(latest.get("MOMENTUM20", 0), -15, 25, 5, 100),
        _linear(latest.get("MOMENTUM60", 0), -25, 45, 5, 100),
        _linear(latest.get("MOMENTUM120", 0), -35, 70, 5, 100),
        85 if latest.get("Close", 0) > latest.get("MA60", float("inf")) else 25,
        85 if macd_positive else 25,
        100 - min(abs(rsi - 58) * 2.5, 100),
    ]
    return _mean(trend_parts) or 0


def _flow_score(flow: dict[str, Any] | None, latest: pd.Series) -> float | None:
    if not flow or flow.get("status") != "ok":
        return None
    average_amount = _finite(latest.get("AVG_AMOUNT20"))
    foreign = _finite(flow.get("foreign_net"))
    institution = _finite(flow.get("institution_net"))
    if not average_amount or foreign is None or institution is None:
        return None
    normalized = (foreign + institution) / average_amount
    return _linear(normalized, -2, 2, 0, 100)


def _volatility_score(latest: pd.Series) -> float | None:
    volatility = _finite(latest.get("VOLATILITY20"))
    atr_pct = _finite(latest.get("ATR_PCT"))
    drawdown = _finite(latest.get("DRAWDOWN120"))
    parts = []
    if volatility is not None:
        parts.append(_linear(volatility, 15, 80, 100, 5))
    if atr_pct is not None:
        parts.append(_linear(atr_pct, 1, 8, 100, 5))
    if drawdown is not None:
        parts.append(_linear(drawdown, -45, 0, 5, 100))
    return _mean(parts)


def _news_score(news: dict[str, Any] | None) -> float | None:
    articles = (news or {}).get("news", [])
    if not articles:
        return None
    sentiments = [_finite(article.get("sentiment")) for article in articles]
    sentiments = [value for value in sentiments if value is not None]
    if not sentiments:
        return 50.0
    return float(np.clip(50 + 50 * np.mean(sentiments), 0, 100))


def _factor_reasons(latest, fundamental, flow, news, strategy) -> list[str]:
    reasons = []
    if latest.get("MACD", 0) > latest.get("MACD_SIGNAL", 0):
        reasons.append("MACD가 신호선 상단")
    if latest.get("Close", 0) > latest.get("MA60", float("inf")):
        reasons.append("60일 이동평균 상단")
    if strategy == "breakout" and latest.get("Close", 0) >= latest.get("BBU", float("inf")):
        reasons.append("볼린저 상단 돌파")
    if fundamental and fundamental.get("status") == "ok":
        roe = _finite(fundamental.get("roe"))
        if roe is not None and roe >= 10:
            reasons.append(f"완료 회계연도 ROE {roe:.1f}%")
    if flow and flow.get("status") != "ok":
        reasons.append("수급 데이터 결측")
    if not (news or {}).get("news"):
        reasons.append("구조화된 뉴스 없음")
    return reasons


def _empty_score(ticker: str, row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "name": row.get("name", ticker),
        "market": row.get("market", ""),
        "sector": row.get("sector", "미분류"),
        "industry": row.get("industry", "미분류"),
        "total_score": 0.0,
        "value_score": None,
        "momentum_score": None,
        "flow_score": None,
        "quality_score": None,
        "volatility_score": None,
        "news_score": None,
        "data_completeness": 0.0,
        "eligible": False,
        "reasons": [reason],
        "facts": {},
        "indicators": pd.DataFrame(),
    }


def _linear(value: Any, low: float, high: float, low_score: float, high_score: float) -> float:
    value = _finite(value)
    if value is None:
        return float("nan")
    if low == high:
        return float(high_score)
    ratio = float(np.clip((value - low) / (high - low), 0, 1))
    return float(low_score + ratio * (high_score - low_score))


def _mean(values: list[float]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return float(np.mean(clean)) if clean else None


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None

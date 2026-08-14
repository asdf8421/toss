from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_engine import calculate_indicators


def strategy_signals(indicators: pd.DataFrame, strategy: str) -> pd.Series:
    if indicators.empty:
        return pd.Series(dtype=bool)
    if strategy == "rebound":
        macd_cross = (
            (indicators["MACD"] > indicators["MACD_SIGNAL"])
            & (indicators["MACD"].shift(1) <= indicators["MACD_SIGNAL"].shift(1))
        )
        return (indicators["RSI14"] <= 45) & macd_cross
    if strategy == "breakout":
        return (
            (indicators["VOLUME_RATIO"] >= 3)
            & (indicators["Close"] >= indicators["BBU"])
        )
    return (
        (indicators["Close"] > indicators["MA60"])
        & (indicators["MACD"] > indicators["MACD_SIGNAL"])
        & (indicators["MOMENTUM20"] > 0)
        & indicators["RSI14"].between(45, 72)
    )


def walk_forward_backtest(
    prices: pd.DataFrame,
    benchmark: pd.DataFrame | None,
    *,
    strategy: str,
    holding_days: int = 5,
    commission_bps: float = 15,
    slippage_bps: float = 10,
    warmup_days: int = 200,
    fold_days: int = 126,
) -> dict[str, Any]:
    indicators = calculate_indicators(prices)
    if len(indicators) < warmup_days + holding_days + 2:
        return _insufficient("검증에 필요한 가격 이력이 부족합니다.")

    signals = strategy_signals(indicators, strategy).fillna(False)
    benchmark_series = _benchmark_series(benchmark)
    round_trip_cost = (commission_bps + slippage_bps) / 10000
    trades: list[dict[str, Any]] = []
    last_exit = -1

    for signal_index in range(warmup_days, len(indicators) - holding_days):
        if not bool(signals.iloc[signal_index]) or signal_index <= last_exit:
            continue
        entry_index = signal_index + 1
        exit_index = signal_index + holding_days
        entry_price = _valid_price(indicators.iloc[entry_index].get("Open"))
        if entry_price is None:
            entry_price = _valid_price(indicators.iloc[entry_index].get("Close"))
        exit_price = _valid_price(indicators.iloc[exit_index].get("Close"))
        atr = _valid_price(indicators.iloc[signal_index].get("ATR14"))
        if entry_price is None or exit_price is None or atr is None:
            continue

        stop_price = max(0.0, entry_price - 2 * atr)
        window_low = pd.to_numeric(
            indicators.iloc[entry_index : exit_index + 1]["Low"], errors="coerce"
        ).min()
        stop_hit = bool(pd.notna(window_low) and window_low <= stop_price)
        effective_exit = stop_price if stop_hit else exit_price
        gross_return = effective_exit / entry_price - 1
        net_return = gross_return - round_trip_cost

        entry_date = pd.Timestamp(indicators.iloc[entry_index]["Date"])
        exit_date = pd.Timestamp(indicators.iloc[exit_index]["Date"])
        benchmark_return = _period_return(benchmark_series, entry_date, exit_date)
        fold = (signal_index - warmup_days) // fold_days + 1
        trades.append(
            {
                "signal_date": pd.Timestamp(indicators.iloc[signal_index]["Date"]).date().isoformat(),
                "entry_date": entry_date.date().isoformat(),
                "exit_date": exit_date.date().isoformat(),
                "entry_price": round(entry_price, 4),
                "exit_price": round(effective_exit, 4),
                "stop_price": round(stop_price, 4),
                "stop_hit": stop_hit,
                "gross_return": gross_return,
                "net_return": net_return,
                "benchmark_return": benchmark_return,
                "excess_return": net_return - benchmark_return if benchmark_return is not None else None,
                "fold": int(fold),
            }
        )
        last_exit = exit_index

    if not trades:
        return _insufficient("워크포워드 구간에서 독립 신호가 발생하지 않았습니다.")

    frame = pd.DataFrame(trades)
    winners = frame[frame["net_return"] > 0]["net_return"]
    losers = frame[frame["net_return"] <= 0]["net_return"]
    gross_profit = float(winners.sum())
    gross_loss = abs(float(losers.sum()))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    fold_metrics = []
    for fold, group in frame.groupby("fold"):
        fold_metrics.append(
            {
                "fold": int(fold),
                "start": group["entry_date"].min(),
                "end": group["exit_date"].max(),
                "trades": int(len(group)),
                "win_rate": round(float((group["net_return"] > 0).mean() * 100), 2),
                "average_net_return": round(float(group["net_return"].mean() * 100), 3),
            }
        )

    return {
        "status": "ok",
        "reason": None,
        "sample_count": int(len(frame)),
        "win_rate": round(float((frame["net_return"] > 0).mean() * 100), 2),
        "average_net_return": round(float(frame["net_return"].mean() * 100), 3),
        "median_net_return": round(float(frame["net_return"].median() * 100), 3),
        "average_excess_return": _percent_mean(frame["excess_return"]),
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "worst_trade": round(float(frame["net_return"].min() * 100), 3),
        "stop_hit_rate": round(float(frame["stop_hit"].mean() * 100), 2),
        "positive_fold_ratio": round(
            sum(item["average_net_return"] > 0 for item in fold_metrics) / len(fold_metrics) * 100,
            2,
        ),
        "cost_bps": commission_bps + slippage_bps,
        "holding_days": holding_days,
        "folds": fold_metrics,
        "trades": trades,
        "limitations": (
            "재무·수급·뉴스의 역사적 시점 데이터는 포함하지 않고, "
            "과거 가격으로 재현 가능한 기술 신호만 검증했습니다."
        ),
    }


def _benchmark_series(benchmark: pd.DataFrame | None) -> pd.Series | None:
    if benchmark is None or benchmark.empty:
        return None
    frame = benchmark.copy()
    frame["Date"] = pd.to_datetime(frame["Date"])
    return frame.set_index("Date")["Close"].sort_index()


def _period_return(series: pd.Series | None, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    if series is None:
        return None
    window = series[(series.index >= start) & (series.index <= end)]
    if len(window) < 2 or window.iloc[0] <= 0:
        return None
    return float(window.iloc[-1] / window.iloc[0] - 1)


def _valid_price(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def _percent_mean(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return round(float(clean.mean() * 100), 3) if not clean.empty else None


def _insufficient(reason: str) -> dict[str, Any]:
    return {
        "status": "insufficient_data",
        "reason": reason,
        "sample_count": 0,
        "win_rate": None,
        "average_net_return": None,
        "median_net_return": None,
        "average_excess_return": None,
        "profit_factor": None,
        "worst_trade": None,
        "stop_hit_rate": None,
        "positive_fold_ratio": None,
        "folds": [],
        "trades": [],
    }


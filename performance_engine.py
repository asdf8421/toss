from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pandas as pd

from config import AppConfig
from data_engine import DataEngine
from storage import Storage, utc_now


class PerformanceEngine:
    def __init__(self, config: AppConfig, storage: Storage, data_engine: DataEngine):
        self.config = config
        self.storage = storage
        self.data_engine = data_engine

    def evaluate_due(self, as_of: date | None = None) -> list[dict[str, Any]]:
        as_of = as_of or date.today()
        results = []
        total_cost = (self.config.commission_bps + self.config.slippage_bps) / 10000
        for recommendation in self.storage.pending_recommendations():
            recommendation_date = date.fromisoformat(recommendation["as_of_date"])
            if recommendation_date >= as_of:
                continue
            prices = self.data_engine.get_prices(
                recommendation["ticker"],
                as_of=as_of,
                lookback_days=max(60, (as_of - recommendation_date).days + 20),
            )
            future = prices[pd.to_datetime(prices["Date"]).dt.date > recommendation_date]
            horizon = int(recommendation["horizon_days"])
            if len(future) < horizon:
                continue
            evaluation_window = future.iloc[:horizon]
            exit_row = evaluation_window.iloc[-1]
            entry = float(recommendation["entry_price"])
            stop = recommendation.get("stop_price")
            stop_hit = bool(
                stop is not None
                and pd.to_numeric(evaluation_window["Low"], errors="coerce").min() <= float(stop)
            )
            exit_price = float(stop) if stop_hit else float(exit_row["Close"])
            gross_return = exit_price / entry - 1
            net_return = gross_return - total_cost

            benchmark = self.data_engine.get_prices(
                recommendation["benchmark_symbol"],
                as_of=as_of,
                lookback_days=max(60, (as_of - recommendation_date).days + 20),
            )
            benchmark_return = _benchmark_return(benchmark, recommendation_date, horizon)
            excess = net_return - benchmark_return if benchmark_return is not None else None
            outcome = "SUCCESS" if net_return > 0 and (excess is None or excess >= 0) else "FAIL"
            failure_reason = None if outcome == "SUCCESS" else self._failure_reason(
                recommendation, stop_hit, net_return, excess
            )
            result = {
                "recommendation_id": recommendation["id"],
                "evaluation_date": pd.Timestamp(exit_row["Date"]).date().isoformat(),
                "exit_price": exit_price,
                "gross_return": gross_return,
                "net_return": net_return,
                "benchmark_return": benchmark_return,
                "excess_return": excess,
                "stop_hit": int(stop_hit),
                "outcome": outcome,
                "failure_reason": failure_reason,
                "created_at": utc_now(),
            }
            self.storage.save_evaluation(result)
            results.append({**result, "ticker": recommendation["ticker"], "name": recommendation["name"]})
        return results

    @staticmethod
    def _failure_reason(
        recommendation: dict[str, Any],
        stop_hit: bool,
        net_return: float,
        excess_return: float | None,
    ) -> str:
        if stop_hit:
            return "ATR/가격구조 손절선 도달"
        if excess_return is not None and excess_return < 0 <= net_return:
            return "절대수익은 양수지만 벤치마크 대비 열위"
        try:
            review = json.loads(recommendation.get("review_json") or "{}")
            gaps = review.get("data_gaps") or []
            if gaps:
                return f"수익 실패; 당시 데이터 한계: {gaps[0]}"
        except json.JSONDecodeError:
            pass
        return "보유기간 종료 시 비용 차감 수익률 음수"


def _benchmark_return(frame: pd.DataFrame, recommendation_date: date, horizon: int) -> float | None:
    if frame.empty:
        return None
    future = frame[pd.to_datetime(frame["Date"]).dt.date > recommendation_date]
    if len(future) < horizon:
        return None
    entry_value = pd.to_numeric(pd.Series([future.iloc[0]["Open"]]), errors="coerce").iloc[0]
    if pd.isna(entry_value) or entry_value <= 0:
        entry_value = pd.to_numeric(pd.Series([future.iloc[0]["Close"]]), errors="coerce").iloc[0]
    entry = float(entry_value)
    exit_price = float(future.iloc[horizon - 1]["Close"])
    if entry <= 0:
        return None
    return exit_price / entry - 1

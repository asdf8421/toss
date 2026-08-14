from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import pandas as pd

from config import AppConfig
from quant_engine import calculate_indicators


class RiskEngine:
    def __init__(self, config: AppConfig):
        self.config = config

    def market_regime(self, benchmark: pd.DataFrame) -> dict[str, Any]:
        indicators = calculate_indicators(benchmark)
        if indicators.empty or len(indicators) < 200:
            return {"regime": "unknown", "cash_target": 0.40, "reason": "벤치마크 200일 데이터 부족"}
        latest = indicators.iloc[-1]
        close = float(latest["Close"])
        ma50 = float(latest["MA50"])
        ma200 = float(latest["MA200"])
        volatility = float(latest["VOLATILITY20"])
        if close > ma200 and ma50 > ma200 and volatility < 45:
            return {"regime": "bull", "cash_target": 0.10, "reason": "지수 및 50일선이 200일선 상단"}
        if close < ma200 and ma50 < ma200:
            return {"regime": "bear", "cash_target": 0.60, "reason": "지수 및 50일선이 200일선 하단"}
        return {"regime": "neutral", "cash_target": 0.30, "reason": "추세 조건 혼재"}

    def assess_position(self, candidate: dict[str, Any]) -> dict[str, Any]:
        facts = candidate.get("facts", {})
        entry = _positive(facts.get("current_price"))
        atr = _positive(facts.get("atr14"))
        recent_low = _positive(facts.get("recent_low20"))
        average_amount = _positive(facts.get("avg_amount20"))
        if entry is None or atr is None:
            return {
                "status": "rejected",
                "reason": "현재가 또는 ATR 결측",
                "entry_price": entry,
                "stop_price": None,
                "quantity": 0,
                "target_weight": 0.0,
            }

        atr_stop = entry - 2 * atr
        structure_stop = recent_low * 0.99 if recent_low and recent_low < entry else atr_stop
        stop = max(0.0, max(atr_stop, structure_stop))
        risk_per_share = entry - stop
        if risk_per_share <= 0 or risk_per_share / entry < 0.005:
            stop = max(0.0, entry - 2 * atr)
            risk_per_share = entry - stop
        if risk_per_share <= 0:
            return {
                "status": "rejected",
                "reason": "유효한 손절 폭을 계산할 수 없음",
                "entry_price": entry,
                "stop_price": stop,
                "quantity": 0,
                "target_weight": 0.0,
            }

        risk_budget = self.config.account_equity * self.config.risk_per_trade
        risk_quantity = math.floor(risk_budget / risk_per_share)
        max_value = self.config.account_equity * self.config.max_position_pct
        max_quantity = math.floor(max_value / entry)
        liquidity_quantity = (
            math.floor(average_amount * self.config.liquidity_participation / entry)
            if average_amount
            else max_quantity
        )
        quantity = max(0, min(risk_quantity, max_quantity, liquidity_quantity))
        position_value = quantity * entry
        return {
            "status": "ok" if quantity > 0 else "rejected",
            "reason": None if quantity > 0 else "위험·유동성 한도 내 매수 가능 수량 0",
            "entry_price": round(entry, 2),
            "atr14": round(atr, 2),
            "recent_low20": round(recent_low, 2) if recent_low else None,
            "stop_price": round(stop, 2),
            "stop_distance_pct": round((entry - stop) / entry * 100, 2),
            "risk_per_share": round(risk_per_share, 2),
            "quantity": int(quantity),
            "position_value": round(position_value, 2),
            "target_weight": round(position_value / self.config.account_equity, 4),
            "risk_budget": round(quantity * risk_per_share, 2),
            "liquidity_cap_applied": liquidity_quantity < min(risk_quantity, max_quantity),
        }

    def construct_portfolio(
        self,
        candidates: list[dict[str, Any]],
        regime: dict[str, Any],
        max_positions: int,
    ) -> dict[str, Any]:
        investable = max(0.0, 1 - float(regime.get("cash_target", 0.4)))
        remaining = investable
        sector_weights: defaultdict[str, float] = defaultdict(float)
        positions = []
        total_risk = 0.0

        for candidate in sorted(candidates, key=lambda item: item["total_score"], reverse=True):
            if len(positions) >= max_positions or remaining <= 0.001:
                break
            risk = candidate.get("risk") or self.assess_position(candidate)
            if risk.get("status") != "ok":
                continue
            sector = candidate.get("sector") or "미분류"
            sector_room = self.config.max_sector_pct - sector_weights[sector]
            proposed = min(float(risk["target_weight"]), remaining, sector_room)
            if proposed <= 0:
                continue
            allowed_portfolio_risk = self.config.max_portfolio_risk - total_risk
            per_position_risk_rate = proposed * (risk["stop_distance_pct"] / 100)
            if per_position_risk_rate > allowed_portfolio_risk:
                proposed = allowed_portfolio_risk / (risk["stop_distance_pct"] / 100)
            if proposed <= 0:
                break
            quantity = math.floor(self.config.account_equity * proposed / risk["entry_price"])
            actual_weight = quantity * risk["entry_price"] / self.config.account_equity
            if quantity <= 0 or actual_weight <= 0:
                continue
            position_risk = actual_weight * risk["stop_distance_pct"] / 100
            positions.append(
                {
                    "ticker": candidate["ticker"],
                    "name": candidate["name"],
                    "sector": sector,
                    "total_score": candidate["total_score"],
                    "entry_price": risk["entry_price"],
                    "stop_price": risk["stop_price"],
                    "quantity": quantity,
                    "target_weight": round(actual_weight, 4),
                    "capital_at_risk_pct": round(position_risk * 100, 3),
                }
            )
            remaining -= actual_weight
            sector_weights[sector] += actual_weight
            total_risk += position_risk

        invested = sum(item["target_weight"] for item in positions)
        return {
            "regime": regime,
            "positions": positions,
            "invested_weight": round(invested, 4),
            "cash_weight": round(1 - invested, 4),
            "portfolio_stop_risk_pct": round(total_risk * 100, 3),
            "sector_weights": {key: round(value, 4) for key, value in sector_weights.items()},
        }


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None

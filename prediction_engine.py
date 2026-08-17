from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_engine import calculate_indicators


FEATURE_COLUMNS = [
    "RETURN1",
    "MOMENTUM5",
    "MOMENTUM20",
    "MOMENTUM60",
    "MOMENTUM120",
    "RSI14",
    "MACD_PCT",
    "MACD_GAP_PCT",
    "MA20_GAP",
    "MA60_GAP",
    "MA120_GAP",
    "ATR_PCT",
    "VOLATILITY20",
    "LOG_VOLUME_RATIO",
    "DRAWDOWN120",
]


def forecast_returns(
    prices: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (5, 20),
    as_of: Any | None = None,
    min_train: int = 180,
    ridge_alpha: float = 4.0,
) -> dict[str, Any]:
    """Estimate forward returns with strictly point-in-time training samples.

    Every training target must have fully resolved before the prediction date.  The
    same routine produces both walk-forward diagnostics and the latest forecast.
    This is a statistical estimate, not a guaranteed future price.
    """
    frame = prices.copy()
    if as_of is not None and not frame.empty:
        cutoff = pd.Timestamp(as_of)
        frame = frame[pd.to_datetime(frame["Date"]) <= cutoff]
    features = _feature_frame(frame)
    if features.empty:
        return _insufficient("가격 특징을 계산할 수 없음", horizons)

    outputs: dict[str, dict[str, Any]] = {}
    for horizon in horizons:
        outputs[str(horizon)] = _forecast_horizon(
            features,
            horizon=int(horizon),
            min_train=min_train,
            ridge_alpha=ridge_alpha,
        )

    ok_count = sum(item.get("status") == "ok" for item in outputs.values())
    return {
        "status": "ok" if ok_count == len(outputs) else "partial" if ok_count else "insufficient_data",
        "price_as_of": pd.Timestamp(features.iloc[-1]["Date"]).date().isoformat(),
        "horizons": outputs,
        "method": "expanding walk-forward ridge 65% + historical-neighbour median 35%",
        "feature_count": len(FEATURE_COLUMNS),
        "limitations": [
            "과거 가격·거래량 패턴의 조건부 추정치이며 수익을 보장하지 않음",
            "각 예측 시점 이전에 확정된 목표값만 학습해 미래 데이터 누출을 차단함",
            "재무·뉴스의 과거 시점 스냅샷은 예측 회귀식에 넣지 않고 AI 심사 근거로만 사용함",
        ],
    }


def build_quant_signal(
    candidate: dict[str, Any],
    *,
    holding: dict[str, Any] | None = None,
    round_trip_cost_bps: float = 25.0,
) -> dict[str, Any]:
    """Turn measured forecasts into a deterministic action boundary for the LLM."""
    forecast = candidate.get("forecast") or {}
    short = (forecast.get("horizons") or {}).get("5", {})
    medium = (forecast.get("horizons") or {}).get("20", {})
    held = bool(holding and int(holding.get("quantity") or 0) > 0)
    reasons: list[str] = []

    if short.get("status") != "ok" or medium.get("status") != "ok":
        action = "HOLD" if held else "AVOID"
        return {
            "action": action,
            "buy_gate_passed": False,
            "allowed_ai_actions": ["HOLD", "REDUCE", "SELL"] if held else ["WATCH", "AVOID"],
            "reasons": ["5일·20일 예측 중 하나 이상이 불충분함"],
            "position_state": "HELD" if held else "NOT_HELD",
        }

    expected5 = float(short["expected_return_pct"])
    expected20 = float(medium["expected_return_pct"])
    up5 = float(short["up_probability_pct"])
    up20 = float(medium["up_probability_pct"])
    accuracy5 = float(short["oos_directional_accuracy_pct"])
    score = float(candidate.get("total_score") or 0)
    completeness = float(candidate.get("data_completeness") or 0)
    backtest = candidate.get("backtest") or {}
    average_net = float(backtest.get("average_net_return") or 0)
    excess = float(backtest.get("average_excess_return") or 0)
    stop_price = _number((candidate.get("risk") or {}).get("stop_price"))
    current = _number((candidate.get("facts") or {}).get("current_price"))

    if held:
        if current is not None and stop_price is not None and current <= stop_price:
            action = "SELL"
            reasons.append("현재가가 정량 손절선 이하")
        elif (expected5 <= -1.0 and up5 < 42) or expected20 <= -3.0:
            action = "SELL"
            reasons.append("단기 또는 중기 하락 추정이 매도 기준을 충족")
        elif expected5 < 0 or expected20 < 0 or score < 55 or average_net < 0:
            action = "REDUCE"
            reasons.append("예측·팩터·검증 중 하나가 보유 축소 기준을 충족")
        else:
            action = "HOLD"
            reasons.append("손절 미도달 및 5일·20일 기대수익이 모두 비음수가 아님")
        allowed = ["HOLD", "REDUCE", "SELL"]
        buy_gate = False
    else:
        cost_pct = float(round_trip_cost_bps) / 100
        checks = {
            "5일 기대수익이 비용과 안전마진 초과": expected5 > cost_pct + 0.50,
            "5일 상승확률 57% 이상": up5 >= 57,
            "20일 기대수익 1% 초과": expected20 > 1.0,
            "20일 상승확률 54% 이상": up20 >= 54,
            "워크포워드 방향정확도 50% 이상": accuracy5 >= 50,
            "백테스트 비용차감 수익 양수": average_net > 0,
            "벤치마크 초과수익 비음수": excess >= 0,
            "데이터 완성도 65% 이상": completeness >= 0.65,
            "리스크 산정 완료": (candidate.get("risk") or {}).get("status") == "ok",
        }
        buy_gate = all(checks.values())
        reasons.extend(
            ("통과: " if passed else "미통과: ") + label
            for label, passed in checks.items()
        )
        if buy_gate:
            action = "BUY"
            allowed = ["BUY", "WATCH", "AVOID"]
        elif expected5 > 0 and expected20 > 0 and up5 >= 52:
            action = "WATCH"
            allowed = ["WATCH", "AVOID"]
        else:
            action = "AVOID"
            allowed = ["WATCH", "AVOID"]

    return {
        "action": action,
        "buy_gate_passed": buy_gate,
        "allowed_ai_actions": allowed,
        "reasons": reasons,
        "position_state": "HELD" if held else "NOT_HELD",
    }


def build_trade_plan(candidate: dict[str, Any], holding: dict[str, Any] | None = None) -> dict[str, Any]:
    facts = candidate.get("facts") or {}
    risk = candidate.get("risk") or {}
    forecast = candidate.get("forecast") or {}
    short = (forecast.get("horizons") or {}).get("5", {})
    medium = (forecast.get("horizons") or {}).get("20", {})
    current = _number(facts.get("current_price"))
    atr = _number(facts.get("atr14"))
    if current is None:
        return {"status": "unavailable", "reason": "현재가 결측"}

    entry_low = max(0.0, current - 0.25 * atr) if atr else current
    entry_high = current + 0.15 * atr if atr else current
    exp5 = _number(short.get("expected_return_pct"))
    exp20 = _number(medium.get("expected_return_pct"))
    forecast_price5 = current * (1 + exp5 / 100) if exp5 is not None else None
    forecast_price20 = current * (1 + exp20 / 100) if exp20 is not None else None
    signal_action = (candidate.get("quant_signal") or {}).get("action")
    has_upside_plan = signal_action in {"BUY", "HOLD"}
    held_qty = max(0, int((holding or {}).get("quantity") or 0))
    return {
        "status": "ok",
        "reference_price": round(current, 2),
        "entry_zone_low": round(entry_low, 2),
        "entry_zone_high": round(entry_high, 2),
        "stop_price": risk.get("stop_price"),
        "forecast_price_5d": round(forecast_price5, 2) if forecast_price5 is not None else None,
        "forecast_price_20d": round(forecast_price20, 2) if forecast_price20 is not None else None,
        "target_5d": round(forecast_price5, 2) if has_upside_plan and forecast_price5 else None,
        "target_20d": round(forecast_price20, 2) if has_upside_plan and forecast_price20 else None,
        "model_quantity": int(risk.get("quantity") or 0),
        "holding_quantity": held_qty,
        "average_cost": _number((holding or {}).get("average_price")),
        "levels_source": "현재가, ATR, 정량 예측",
    }


def _feature_frame(prices: pd.DataFrame) -> pd.DataFrame:
    indicators = calculate_indicators(prices)
    if indicators.empty:
        return pd.DataFrame()
    close = pd.to_numeric(indicators["Close"], errors="coerce")
    out = pd.DataFrame({"Date": pd.to_datetime(indicators["Date"]), "Close": close})
    out["RETURN1"] = close.pct_change() * 100
    for column in ["MOMENTUM5", "MOMENTUM20", "MOMENTUM60", "MOMENTUM120", "RSI14", "ATR_PCT", "VOLATILITY20", "DRAWDOWN120"]:
        out[column] = pd.to_numeric(indicators[column], errors="coerce")
    out["MACD_PCT"] = pd.to_numeric(indicators["MACD"], errors="coerce") / close * 100
    out["MACD_GAP_PCT"] = (
        pd.to_numeric(indicators["MACD"], errors="coerce")
        - pd.to_numeric(indicators["MACD_SIGNAL"], errors="coerce")
    ) / close * 100
    for window in [20, 60, 120]:
        out[f"MA{window}_GAP"] = (close / pd.to_numeric(indicators[f"MA{window}"], errors="coerce") - 1) * 100
    volume_ratio = pd.to_numeric(indicators["VOLUME_RATIO"], errors="coerce").clip(lower=0.05)
    out["LOG_VOLUME_RATIO"] = np.log(volume_ratio)
    return out.replace([np.inf, -np.inf], np.nan).reset_index(drop=True)


def _forecast_horizon(
    features: pd.DataFrame,
    *,
    horizon: int,
    min_train: int,
    ridge_alpha: float,
) -> dict[str, Any]:
    target = features["Close"].shift(-horizon) / features["Close"] - 1
    usable_feature_rows = features[FEATURE_COLUMNS].notna().all(axis=1)
    known_rows = usable_feature_rows & target.notna()
    known_indices = np.flatnonzero(known_rows.to_numpy())
    latest_index = len(features) - 1
    if len(known_indices) < min_train or not bool(usable_feature_rows.iloc[-1]):
        return {
            "status": "insufficient_data",
            "reason": f"학습 가능 표본 {len(known_indices)}건; 최소 {min_train}건 필요",
            "horizon_days": horizon,
        }

    test_start = max(min_train + horizon, latest_index - 126)
    oos: list[tuple[float, float]] = []
    for test_index in range(test_start, latest_index - horizon + 1):
        if not bool(usable_feature_rows.iloc[test_index]):
            continue
        # At test_index, only targets ending strictly on or before that date are known.
        train_indices = known_indices[known_indices + horizon <= test_index]
        if len(train_indices) < min_train:
            continue
        predicted, _, _ = _fit_predict(
            features,
            target,
            train_indices,
            test_index,
            ridge_alpha,
        )
        actual = float(target.iloc[test_index])
        if math.isfinite(predicted) and math.isfinite(actual):
            oos.append((predicted, actual))

    if len(oos) < 20:
        return {
            "status": "insufficient_data",
            "reason": f"워크포워드 예측 표본 {len(oos)}건; 최소 20건 필요",
            "horizon_days": horizon,
        }

    train_indices = known_indices
    predicted, neighbours, model = _fit_predict(
        features,
        target,
        train_indices,
        latest_index,
        ridge_alpha,
    )
    actuals = np.asarray([actual for _, actual in oos], dtype=float)
    predictions = np.asarray([value for value, _ in oos], dtype=float)
    directional = float(np.mean(np.sign(predictions) == np.sign(actuals)) * 100)
    mae = float(np.mean(np.abs(predictions - actuals)) * 100)
    neighbour_values = target.iloc[neighbours].to_numpy(dtype=float)
    training_values = target.iloc[train_indices].to_numpy(dtype=float)
    robust_low, robust_high = np.quantile(training_values, [0.10, 0.90])
    horizon_cap = 0.12 if horizon <= 5 else 0.25
    lower_bound = max(-horizon_cap, min(0.0, float(robust_low)))
    upper_bound = min(horizon_cap, max(0.0, float(robust_high)))
    predicted = float(np.clip(predicted, lower_bound, upper_bound))
    wins = int(np.sum(neighbour_values > 0))
    neighbour_probability = (wins + 2) / (len(neighbour_values) + 4)
    residuals = actuals - predictions
    residual_wins = int(np.sum(predicted + residuals > 0))
    residual_probability = (residual_wins + 2) / (len(residuals) + 4)
    probability = (0.70 * residual_probability + 0.30 * neighbour_probability) * 100
    expected_pct = predicted * 100
    return {
        "status": "ok",
        "horizon_days": horizon,
        "expected_return_pct": round(expected_pct, 2),
        "up_probability_pct": round(probability, 1),
        "return_p25_pct": round(float(np.quantile(neighbour_values, 0.25) * 100), 2),
        "return_p75_pct": round(float(np.quantile(neighbour_values, 0.75) * 100), 2),
        "oos_sample_count": len(oos),
        "oos_directional_accuracy_pct": round(directional, 1),
        "oos_mae_pct": round(mae, 2),
        "training_sample_count": len(train_indices),
        "neighbour_count": len(neighbour_values),
        "ridge_return_pct": round(model["ridge"] * 100, 2),
        "neighbour_median_return_pct": round(model["neighbour_median"] * 100, 2),
    }


def _fit_predict(
    features: pd.DataFrame,
    target: pd.Series,
    train_indices: np.ndarray,
    predict_index: int,
    ridge_alpha: float,
) -> tuple[float, np.ndarray, dict[str, float]]:
    x_train = features.iloc[train_indices][FEATURE_COLUMNS].to_numpy(dtype=float)
    y_train = target.iloc[train_indices].to_numpy(dtype=float)
    x_predict = features.iloc[predict_index][FEATURE_COLUMNS].to_numpy(dtype=float)
    median = np.median(x_train, axis=0)
    scale = np.median(np.abs(x_train - median), axis=0) * 1.4826
    scale = np.where(scale < 1e-8, 1.0, scale)
    x_train_scaled = np.clip((x_train - median) / scale, -8, 8)
    x_predict_scaled = np.clip((x_predict - median) / scale, -8, 8)
    design = np.column_stack([np.ones(len(x_train_scaled)), x_train_scaled])
    penalty = np.eye(design.shape[1]) * ridge_alpha
    penalty[0, 0] = 0
    beta = np.linalg.pinv(design.T @ design + penalty) @ design.T @ y_train
    ridge_prediction = float(np.r_[1.0, x_predict_scaled] @ beta)
    distances = np.sqrt(np.mean((x_train_scaled - x_predict_scaled) ** 2, axis=1))
    neighbour_count = min(35, max(15, int(math.sqrt(len(train_indices)) * 2)))
    local_positions = np.argsort(distances)[:neighbour_count]
    neighbours = train_indices[local_positions]
    neighbour_median = float(np.median(y_train[local_positions]))
    prediction = 0.65 * ridge_prediction + 0.35 * neighbour_median
    return prediction, neighbours, {"ridge": ridge_prediction, "neighbour_median": neighbour_median}


def _insufficient(reason: str, horizons: tuple[int, ...]) -> dict[str, Any]:
    return {
        "status": "insufficient_data",
        "price_as_of": None,
        "horizons": {
            str(horizon): {"status": "insufficient_data", "reason": reason, "horizon_days": horizon}
            for horizon in horizons
        },
        "method": "expanding walk-forward ridge + historical neighbours",
        "limitations": [reason],
    }


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None

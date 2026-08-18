from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from storage import utc_now


def build_public_snapshot(result: dict[str, Any]) -> dict[str, Any]:
    """Return the audited, JSON-safe subset that the public dashboard may show."""
    decisions = []
    for candidate in result.get("ranked", []):
        facts = candidate.get("facts") or {}
        review = candidate.get("ai_review") or {}
        forecast = candidate.get("forecast") or {}
        decisions.append(
            {
                "ticker": candidate.get("ticker"),
                "name": candidate.get("name"),
                "market": candidate.get("market"),
                "sector": candidate.get("sector"),
                "strategy": candidate.get("strategy"),
                "action": review.get("action", "NO_ACTION"),
                "confidence": review.get("confidence", 0),
                "score": candidate.get("total_score"),
                "data_completeness": candidate.get("data_completeness"),
                "factors": {
                    key.removesuffix("_score"): candidate.get(key)
                    for key in [
                        "value_score",
                        "momentum_score",
                        "flow_score",
                        "quality_score",
                        "volatility_score",
                        "news_score",
                    ]
                },
                "price": {
                    "current": facts.get("current_price"),
                    "as_of": facts.get("price_as_of"),
                    "source": facts.get("price_source"),
                },
                "forecast": forecast,
                "backtest": _pick(
                    candidate.get("backtest") or {},
                    [
                        "status",
                        "reason",
                        "sample_count",
                        "win_rate",
                        "average_net_return",
                        "average_excess_return",
                        "profit_factor",
                        "worst_trade",
                        "positive_fold_ratio",
                        "cost_bps",
                        "holding_days",
                        "limitations",
                    ],
                ),
                "risk": candidate.get("risk") or {},
                "trade_plan": candidate.get("trade_plan") or {},
                "ai_review": review,
                "evidence": {
                    "fundamental_status": facts.get("fundamental_status"),
                    "fundamental_period": facts.get("fundamental_period"),
                    "fundamentals": facts.get("fundamentals") or {},
                    "flow_status": facts.get("flow_status"),
                    "flow_source": facts.get("flow_source"),
                    "flow_observations": facts.get("flow_observations"),
                    "foreign_net": facts.get("foreign_net"),
                    "institution_net": facts.get("institution_net"),
                    "news_status": facts.get("news_status"),
                    "news_detail_coverage": facts.get("news_detail_coverage"),
                    "news": facts.get("news") or [],
                    "disclosure_status": facts.get("disclosure_status"),
                    "disclosures": facts.get("disclosures") or [],
                },
            }
        )

    portfolio = result.get("portfolio") or {}
    return {
        "schema_version": 1,
        "run_id": result.get("run_id"),
        "as_of_date": result.get("as_of_date"),
        "generated_at": utc_now(),
        "market_data_mode": "latest_available_daily_snapshot",
        "market_data_notice": (
            "거래소 실시간 호가가 아니라 실행 시점에 공급원이 제공한 최신 일봉·뉴스·공시 스냅샷입니다."
        ),
        "strategy": result.get("strategy"),
        "coverage": {
            "universe": result.get("universe_count"),
            "liquid_universe": result.get("liquid_universe_count"),
            "price_screened": result.get("filtered_universe_count"),
            "deep_analyzed": result.get("deep_analysis_count"),
        },
        "data_status": result.get("data_status") or {},
        "portfolio": {
            "regime": portfolio.get("regime"),
            "invested_weight": portfolio.get("invested_weight", 0),
            "cash_weight": portfolio.get("cash_weight", 1),
            "capital_at_risk_pct": portfolio.get("capital_at_risk_pct", 0),
            "positions": portfolio.get("positions") or [],
        },
        "decisions": decisions,
        "errors": result.get("errors") or [],
    }


def write_public_snapshot(result: dict[str, Any], output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_public_snapshot(result)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def _pick(values: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: values.get(key) for key in keys}

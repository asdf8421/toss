from __future__ import annotations

import json
import math
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Callable

import pandas as pd

from ai_judge import AIJudge
from config import AppConfig
from data_engine import DataEngine
from prediction_engine import build_quant_signal, build_trade_plan, forecast_returns
from quant_engine import score_stock
from risk_engine import RiskEngine
from storage import Storage, utc_now
from validation_engine import walk_forward_backtest


ProgressCallback = Callable[[str, int, int, str], None]


class FundManagerPipeline:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or AppConfig()
        self.storage = Storage(self.config.db_path)
        self.data = DataEngine(self.config, self.storage)
        self.risk = RiskEngine(self.config)
        self.judge = AIJudge(self.config)

    def run(
        self,
        *,
        strategy: str = "balanced",
        as_of: date | None = None,
        universe_limit: int = 80,
        deep_analysis_limit: int = 20,
        max_positions: int = 5,
        holdings: list[dict[str, Any]] | None = None,
        require_ai: bool = True,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        as_of = as_of or date.today()
        callback = progress or (lambda stage, current, total, message: None)
        run_id = uuid.uuid4().hex
        holdings_map = _normalize_holdings(holdings or [])

        callback("universe", 0, 1, "KRX 전체 종목과 보유 종목을 확인합니다.")
        full_universe = self.data.get_universe(as_of)
        liquid_universe = self.data.filter_universe(full_universe, 0)
        selected = liquid_universe.head(universe_limit) if universe_limit > 0 else liquid_universe
        holding_rows = full_universe[
            full_universe["ticker"].astype(str).str.zfill(6).isin(holdings_map)
        ]
        universe = (
            pd.concat([selected, holding_rows], ignore_index=True)
            .drop_duplicates(subset=["ticker"], keep="first")
        )
        callback(
            "universe",
            1,
            1,
            f"전체 {len(full_universe):,}개 · 유동성 적격 {len(liquid_universe):,}개 · 이번 검사 {len(universe):,}개",
        )

        rows = universe.to_dict("records")
        row_map = {str(row["ticker"]).zfill(6): row for row in rows}
        price_results: dict[str, pd.DataFrame] = {}
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {
                executor.submit(self.data.get_prices, str(row["ticker"]).zfill(6), as_of=as_of): row
                for row in rows
            }
            for index, future in enumerate(as_completed(futures), start=1):
                row = futures[future]
                ticker = str(row["ticker"]).zfill(6)
                try:
                    price_results[ticker] = future.result()
                except Exception as exc:
                    errors.append(f"{ticker} 가격: {type(exc).__name__}: {exc}")
                callback("prices", index, len(futures), f"가격 이력 {index}/{len(futures)}")

        preliminary = []
        for row in rows:
            ticker = str(row["ticker"]).zfill(6)
            score = score_stock(row, price_results.get(ticker, pd.DataFrame()), None, None, None, None, strategy)
            preliminary.append(score)
        preliminary.sort(key=lambda item: item["total_score"], reverse=True)
        eligible = [item for item in preliminary if item["eligible"]]
        initial_deep = eligible[:deep_analysis_limit] if deep_analysis_limit > 0 else eligible
        deep_tickers = {item["ticker"] for item in initial_deep}
        deep_tickers.update(ticker for ticker in holdings_map if ticker in row_map)
        deep_candidates = [item for item in preliminary if item["ticker"] in deep_tickers]

        enriched: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {
                executor.submit(
                    self._enrich,
                    row_map[candidate["ticker"]],
                    price_results.get(candidate["ticker"], pd.DataFrame()),
                    as_of,
                    strategy,
                ): candidate
                for candidate in deep_candidates
            }
            for index, future in enumerate(as_completed(futures), start=1):
                candidate = futures[future]
                try:
                    enriched.append(future.result())
                except Exception as exc:
                    errors.append(f"{candidate['ticker']} 심층수집: {type(exc).__name__}: {exc}")
                callback("enrich", index, len(futures), f"재무·수급·뉴스·공시 {index}/{len(futures)}")

        enriched.sort(key=lambda item: item["total_score"], reverse=True)
        benchmark_cache: dict[str, tuple[str, pd.DataFrame]] = {}
        for market in {item["market"] for item in enriched}:
            try:
                benchmark_cache[market] = self.data.get_benchmark(market, as_of)
            except Exception as exc:
                errors.append(f"{market} 벤치마크: {type(exc).__name__}: {exc}")
                benchmark_cache[market] = (
                    self.config.benchmark_kosdaq if market == "KOSDAQ" else self.config.benchmark_kospi,
                    pd.DataFrame(),
                )

        for index, candidate in enumerate(enriched, start=1):
            ticker = candidate["ticker"]
            benchmark_symbol, benchmark = benchmark_cache[candidate["market"]]
            candidate["strategy"] = strategy
            candidate["benchmark_symbol"] = benchmark_symbol
            candidate["backtest"] = walk_forward_backtest(
                price_results.get(ticker, pd.DataFrame()),
                benchmark,
                strategy=strategy,
                holding_days=self.config.holding_days,
                commission_bps=self.config.commission_bps,
                slippage_bps=self.config.slippage_bps,
            )
            candidate["forecast"] = forecast_returns(
                price_results.get(ticker, pd.DataFrame()),
                as_of=as_of,
            )
            candidate["risk"] = self.risk.assess_position(candidate)
            candidate["holding"] = holdings_map.get(ticker)
            candidate["quant_signal"] = build_quant_signal(
                candidate,
                holding=candidate["holding"],
                round_trip_cost_bps=self.config.commission_bps + self.config.slippage_bps,
            )
            candidate["trade_plan"] = build_trade_plan(candidate, candidate["holding"])
            callback("validate", index, len(enriched), f"예측·워크포워드·위험 검증 {index}/{len(enriched)}")

        review_limit = max(max_positions * 2, max_positions)
        review_tickers = {item["ticker"] for item in enriched[:review_limit]}
        review_tickers.update(ticker for ticker in holdings_map)
        review_pool = [item for item in enriched if item["ticker"] in review_tickers]
        for index, candidate in enumerate(review_pool, start=1):
            candidate["ai_review"] = self.judge.review(candidate, require_ai=require_ai)
            callback("judge", index, len(review_pool), f"Groq 최종 분석 {index}/{len(review_pool)}")

        retained_holdings = _retained_holdings(review_pool, self.config.account_equity)
        investable = [
            item for item in review_pool
            if item.get("ai_review", {}).get("action") == "BUY"
        ]
        primary_benchmark = benchmark_cache.get(
            "KOSPI",
            next(iter(benchmark_cache.values()), ("KS11", pd.DataFrame())),
        )[1]
        regime = self.risk.market_regime(primary_benchmark)
        portfolio = self.risk.construct_portfolio(
            investable,
            regime,
            max_positions,
            existing_positions=retained_holdings,
        )
        position_map = {item["ticker"]: item for item in portfolio["positions"]}
        for candidate in review_pool:
            _finalize_order(candidate, position_map.get(candidate["ticker"]))

        self.storage.save_scan_run(
            run_id,
            as_of.isoformat(),
            strategy,
            len(full_universe),
            len(universe),
            {
                "universe_limit": universe_limit,
                "deep_analysis_limit": deep_analysis_limit,
                "max_positions": max_positions,
                "holding_tickers": sorted(holdings_map),
                "commission_bps": self.config.commission_bps,
                "slippage_bps": self.config.slippage_bps,
                "require_ai": require_ai,
            },
        )
        self.storage.save_factor_scores(run_id, [_serializable_score(item) for item in enriched])

        for candidate in review_pool:
            review = candidate["ai_review"]
            trade_plan = candidate.get("trade_plan") or {}
            self.storage.save_recommendation(
                {
                    "run_id": run_id,
                    "ticker": candidate["ticker"],
                    "name": candidate["name"],
                    "market": candidate["market"],
                    "sector": candidate["sector"],
                    "as_of_date": as_of.isoformat(),
                    "strategy": strategy,
                    "entry_price": trade_plan.get("reference_price") or candidate["facts"].get("current_price"),
                    "stop_price": trade_plan.get("stop_price"),
                    "target_weight": (position_map.get(candidate["ticker"]) or {}).get("target_weight", 0.0),
                    "quantity": trade_plan.get("order_quantity", 0),
                    "total_score": candidate["total_score"],
                    "ai_decision": review["action"],
                    "ai_confidence": review["confidence"],
                    "thesis": review["thesis"],
                    "review_json": json.dumps(
                        {**review, "forecast": candidate.get("forecast"), "trade_plan": trade_plan},
                        ensure_ascii=False,
                        default=str,
                    ),
                    "horizon_days": self.config.holding_days,
                    "benchmark_symbol": candidate["benchmark_symbol"],
                    "created_at": utc_now(),
                }
            )

        return {
            "run_id": run_id,
            "as_of_date": as_of.isoformat(),
            "strategy": strategy,
            "universe_count": len(full_universe),
            "liquid_universe_count": len(liquid_universe),
            "filtered_universe_count": len(universe),
            "deep_analysis_count": len(enriched),
            "ranked": review_pool,
            "portfolio": portfolio,
            "trade_actions": [item for item in review_pool if item.get("trade_plan")],
            "errors": errors,
            "data_status": _data_coverage(
                enriched,
                review_pool,
                inspected=len(universe),
                liquid_total=len(liquid_universe),
                groq_configured=bool(self.config.groq_api_key),
                krx_configured=self.config.krx_ready,
                dart_configured=bool(self.config.dart_api_key),
            ),
        }

    def _enrich(
        self,
        row: dict[str, Any],
        prices: pd.DataFrame,
        as_of: date,
        strategy: str,
    ) -> dict[str, Any]:
        ticker = str(row["ticker"]).zfill(6)
        fundamental = self.data.get_fundamentals(ticker, as_of)
        flow = self.data.get_investor_flow(ticker, as_of)
        news = self.data.get_news(ticker, as_of)
        disclosures = self.data.get_disclosures(ticker, as_of)
        return score_stock(row, prices, fundamental, flow, news, disclosures, strategy)


def _normalize_holdings(holdings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for item in holdings:
        ticker = str(item.get("ticker") or "").strip().zfill(6)
        try:
            quantity = max(0, int(item.get("quantity") or 0))
            average_price = float(item.get("average_price") or 0) or None
        except (TypeError, ValueError):
            continue
        if len(ticker) == 6 and ticker.isdigit() and quantity > 0:
            normalized[ticker] = {
                "ticker": ticker,
                "quantity": quantity,
                "average_price": average_price,
            }
    return normalized


def _retained_holdings(reviewed: list[dict[str, Any]], account_equity: float) -> list[dict[str, Any]]:
    retained = []
    for candidate in reviewed:
        holding = candidate.get("holding") or {}
        held_qty = int(holding.get("quantity") or 0)
        if held_qty <= 0:
            continue
        action = (candidate.get("ai_review") or {}).get("action")
        remaining_qty = 0 if action == "SELL" else held_qty - math.ceil(held_qty / 2) if action == "REDUCE" else held_qty
        price = float((candidate.get("facts") or {}).get("current_price") or 0)
        if remaining_qty <= 0 or price <= 0:
            continue
        stop_distance = float((candidate.get("risk") or {}).get("stop_distance_pct") or 0)
        weight = remaining_qty * price / account_equity
        retained.append(
            {
                "ticker": candidate["ticker"],
                "name": candidate["name"],
                "sector": candidate.get("sector") or "미분류",
                "quantity": remaining_qty,
                "target_weight": round(weight, 4),
                "capital_at_risk_pct": round(weight * stop_distance, 3),
            }
        )
    return retained


def _finalize_order(candidate: dict[str, Any], portfolio_position: dict[str, Any] | None) -> None:
    review = candidate.get("ai_review") or {}
    action = review.get("action", "NO_ACTION")
    holding_qty = int((candidate.get("holding") or {}).get("quantity") or 0)
    quantity = 0
    side = "NONE"
    if action == "BUY" and portfolio_position:
        quantity = int(portfolio_position.get("quantity") or 0)
        side = "BUY" if quantity > 0 else "NONE"
    elif action == "SELL":
        quantity = holding_qty
        side = "SELL" if quantity > 0 else "NONE"
    elif action == "REDUCE":
        quantity = math.ceil(holding_qty / 2)
        side = "SELL" if quantity > 0 else "NONE"
    candidate["trade_plan"].update(
        {
            "action": action,
            "order_side": side,
            "order_quantity": quantity,
            "target_weight": (portfolio_position or {}).get("target_weight", 0.0),
            "execution_note": "지정가·체결 여부를 확인하는 수동 주문 계획; 자동 주문 아님",
        }
    )
    if action not in {"BUY", "HOLD"}:
        candidate["trade_plan"]["target_5d"] = None
        candidate["trade_plan"]["target_20d"] = None


def _serializable_score(candidate: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "ticker", "total_score", "value_score", "momentum_score", "flow_score",
        "quality_score", "volatility_score", "news_score", "data_completeness",
        "eligible", "reasons", "facts",
    ]
    result = {key: candidate.get(key) for key in keys}
    result["facts"] = dict(result.get("facts") or {})
    backtest_keys = [
        "status", "sample_count", "win_rate", "average_net_return",
        "average_excess_return", "profit_factor", "worst_trade",
        "stop_hit_rate", "positive_fold_ratio", "cost_bps", "holding_days",
    ]
    result["facts"]["backtest"] = {
        key: candidate.get("backtest", {}).get(key) for key in backtest_keys
    }
    result["facts"]["forecast"] = candidate.get("forecast", {})
    result["facts"]["risk"] = candidate.get("risk", {})
    result["facts"]["quant_signal"] = candidate.get("quant_signal", {})
    result["facts"]["trade_plan"] = candidate.get("trade_plan", {})
    if candidate.get("ai_review"):
        result["facts"]["ai_review"] = candidate["ai_review"]
    return result


def _data_coverage(
    enriched: list[dict[str, Any]],
    reviewed: list[dict[str, Any]],
    *,
    inspected: int,
    liquid_total: int,
    groq_configured: bool,
    krx_configured: bool,
    dart_configured: bool,
) -> dict[str, Any]:
    total = len(enriched)

    def count_status(key: str, accepted: set[str]) -> int:
        return sum(item.get("facts", {}).get(key) in accepted for item in enriched)

    ai_sources: dict[str, int] = {}
    for item in reviewed:
        source = item.get("ai_review", {}).get("source", "UNKNOWN")
        ai_sources[source] = ai_sources.get(source, 0) + 1
    return {
        "universe_scope": {
            "status": "full" if inspected >= liquid_total else "partial",
            "covered": inspected,
            "total": liquid_total,
        },
        "fundamentals": {"covered": count_status("fundamental_status", {"ok"}), "total": total},
        "investor_flow": {
            "covered": count_status("flow_status", {"ok"}),
            "total": total,
            "primary": "KRX official" if krx_configured else "Naver estimated fallback",
        },
        "news": {"covered": count_status("news_status", {"ok", "partial"}), "total": total},
        "disclosures": {
            "covered": count_status("disclosure_status", {"ok", "partial"}),
            "total": total,
            "primary": "OpenDART official" if dart_configured else "Naver/KOSCOM fallback",
        },
        "prediction": {
            "covered": sum(item.get("forecast", {}).get("status") == "ok" for item in enriched),
            "total": total,
            "method": "walk-forward ridge + neighbours",
        },
        "ai_review": {"configured": groq_configured, "sources": ai_sources},
    }

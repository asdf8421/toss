from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Callable

import pandas as pd

from ai_judge import AIJudge
from config import AppConfig
from data_engine import DataEngine
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
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        as_of = as_of or date.today()
        callback = progress or (lambda stage, current, total, message: None)
        run_id = uuid.uuid4().hex

        callback("universe", 0, 1, "KRX 전체 종목과 업종 정보를 수집합니다.")
        full_universe = self.data.get_universe(as_of)
        liquid_universe = self.data.filter_universe(full_universe, 0)
        universe = liquid_universe.head(universe_limit) if universe_limit > 0 else liquid_universe
        callback(
            "universe",
            1,
            1,
            f"전체 {len(full_universe):,}개 · 유동성 적격 {len(liquid_universe):,}개 · 이번 검사 {len(universe):,}개",
        )

        rows = universe.to_dict("records")
        price_results: dict[str, pd.DataFrame] = {}
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {
                executor.submit(self.data.get_prices, row["ticker"], as_of=as_of): row
                for row in rows
            }
            for index, future in enumerate(as_completed(futures), start=1):
                row = futures[future]
                try:
                    price_results[row["ticker"]] = future.result()
                except Exception as exc:
                    errors.append(f"{row['ticker']} 가격: {type(exc).__name__}: {exc}")
                callback("prices", index, len(futures), f"가격 이력 {index}/{len(futures)}")

        preliminary = []
        for row in rows:
            prices = price_results.get(row["ticker"], pd.DataFrame())
            score = score_stock(row, prices, None, None, None, None, strategy)
            preliminary.append(score)
        preliminary.sort(key=lambda item: item["total_score"], reverse=True)
        eligible_preliminary = [item for item in preliminary if item["eligible"]]
        deep_candidates = (
            eligible_preliminary[:deep_analysis_limit]
            if deep_analysis_limit > 0
            else eligible_preliminary
        )

        enriched: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {
                executor.submit(
                    self._enrich,
                    next(row for row in rows if row["ticker"] == candidate["ticker"]),
                    price_results[candidate["ticker"]],
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
        benchmark_cache = {}
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
            benchmark_symbol, benchmark = benchmark_cache[candidate["market"]]
            candidate["strategy"] = strategy
            candidate["benchmark_symbol"] = benchmark_symbol
            candidate["backtest"] = walk_forward_backtest(
                price_results[candidate["ticker"]],
                benchmark,
                strategy=strategy,
                holding_days=self.config.holding_days,
                commission_bps=self.config.commission_bps,
                slippage_bps=self.config.slippage_bps,
            )
            candidate["risk"] = self.risk.assess_position(candidate)
            callback("validate", index, len(enriched), f"워크포워드·위험 검증 {index}/{len(enriched)}")

        review_pool = enriched[: max(max_positions * 2, max_positions)]
        for index, candidate in enumerate(review_pool, start=1):
            candidate["ai_review"] = self.judge.review(candidate)
            callback("judge", index, len(review_pool), f"AI 위험심사 {index}/{len(review_pool)}")

        # WATCH is a watchlist decision, not an authorization to deploy capital.
        # Only an explicit AI approval can reach portfolio construction.
        investable = [
            item
            for item in review_pool
            if item.get("ai_review", {}).get("decision") == "APPROVE"
        ]
        primary_benchmark = benchmark_cache.get("KOSPI", next(iter(benchmark_cache.values()), ("KS11", pd.DataFrame())))[1]
        regime = self.risk.market_regime(primary_benchmark)
        portfolio = self.risk.construct_portfolio(investable, regime, max_positions)

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
                "commission_bps": self.config.commission_bps,
                "slippage_bps": self.config.slippage_bps,
            },
        )
        serializable_scores = [_serializable_score(item) for item in enriched]
        self.storage.save_factor_scores(run_id, serializable_scores)

        position_map = {item["ticker"]: item for item in portfolio["positions"]}
        for candidate in review_pool:
            review = candidate["ai_review"]
            position = position_map.get(candidate["ticker"], {})
            self.storage.save_recommendation(
                {
                    "run_id": run_id,
                    "ticker": candidate["ticker"],
                    "name": candidate["name"],
                    "market": candidate["market"],
                    "sector": candidate["sector"],
                    "as_of_date": as_of.isoformat(),
                    "strategy": strategy,
                    "entry_price": candidate["risk"].get("entry_price") or candidate["facts"]["current_price"],
                    "stop_price": candidate["risk"].get("stop_price"),
                    "target_weight": position.get("target_weight", 0.0),
                    "quantity": position.get("quantity", 0),
                    "total_score": candidate["total_score"],
                    "ai_decision": review["decision"],
                    "ai_confidence": review["confidence"],
                    "thesis": review["thesis"],
                    "review_json": json.dumps(review, ensure_ascii=False, default=str),
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
        fundamental = self.data.get_fundamentals(row["ticker"], as_of)
        flow = self.data.get_investor_flow(row["ticker"], as_of)
        news = self.data.get_news(row["ticker"], as_of)
        disclosures = self.data.get_disclosures(row["ticker"], as_of)
        return score_stock(row, prices, fundamental, flow, news, disclosures, strategy)


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
    result["facts"]["risk"] = candidate.get("risk", {})
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
        "ai_review": {
            "configured": groq_configured,
            "sources": ai_sources,
        },
    }

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from ai_judge import AIJudge
from config import AppConfig
from quant_engine import calculate_indicators, score_stock
from performance_engine import PerformanceEngine
from portfolio_input import parse_holdings
from prediction_engine import build_quant_signal, forecast_returns
from risk_engine import RiskEngine
from snapshot_export import build_public_snapshot
from storage import Storage
from validation_engine import walk_forward_backtest


def synthetic_prices(rows: int = 520) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=rows)
    trend = 10000 + np.arange(rows) * 12
    cycle = np.sin(np.arange(rows) / 8) * 350
    close = trend + cycle
    open_price = close * (1 + np.sin(np.arange(rows)) * 0.001)
    volume = np.full(rows, 150_000.0)
    volume[::37] = 650_000
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": open_price,
            "High": np.maximum(open_price, close) * 1.015,
            "Low": np.minimum(open_price, close) * 0.985,
            "Close": close,
            "Volume": volume,
            "Change": pd.Series(close).pct_change().to_numpy(),
        }
    )


class QuantEngineTests(unittest.TestCase):
    def test_indicators_do_not_change_when_only_future_prices_change(self):
        prices = synthetic_prices()
        original = calculate_indicators(prices)
        changed = prices.copy()
        changed.loc[400:, "Close"] *= 3
        changed.loc[400:, "High"] *= 3
        changed.loc[400:, "Low"] *= 3
        recalculated = calculate_indicators(changed)
        for column in ["RSI14", "MACD", "ATR14", "MOMENTUM120"]:
            self.assertAlmostEqual(original.loc[350, column], recalculated.loc[350, column], places=8)

    def test_multifactor_score_marks_missing_flow_as_missing(self):
        prices = synthetic_prices()
        fundamental = {
            "status": "ok",
            "period": "2025-12-01",
            "per": 12,
            "pbr": 1.1,
            "roe": 14,
            "debt_ratio": 45,
            "operating_margin": 13,
            "revenue_growth": 9,
        }
        news = {
            "status": "ok",
            "news": [{"title": "신규 공급 계약", "url": "https://example.test/1", "published_date": "2026-08-13", "sentiment": 1}],
        }
        score = score_stock(
            {"ticker": "005930", "name": "테스트", "market": "KOSPI", "sector": "반도체"},
            prices,
            fundamental,
            {"status": "missing_configuration"},
            news,
            {"status": "missing_configuration", "items": []},
            "balanced",
        )
        self.assertTrue(score["eligible"])
        self.assertIsNone(score["flow_score"])
        self.assertGreater(score["data_completeness"], 0.5)
        self.assertTrue(any("수급 데이터 결측" in reason for reason in score["reasons"]))


class ValidationAndRiskTests(unittest.TestCase):
    def test_forecast_is_unchanged_by_prices_after_as_of(self):
        prices = synthetic_prices()
        cutoff = prices.iloc[400]["Date"]
        original = forecast_returns(prices, as_of=cutoff)
        changed = prices.copy()
        changed.loc[401:, ["Open", "High", "Low", "Close"]] *= 7
        recalculated = forecast_returns(changed, as_of=cutoff)
        self.assertEqual(original["status"], "ok")
        for horizon in ["5", "20"]:
            self.assertEqual(
                original["horizons"][horizon]["expected_return_pct"],
                recalculated["horizons"][horizon]["expected_return_pct"],
            )
            self.assertGreaterEqual(original["horizons"][horizon]["oos_sample_count"], 20)

    def test_quant_buy_requires_every_measured_gate(self):
        candidate = {
            "total_score": 75,
            "data_completeness": 0.9,
            "forecast": {
                "horizons": {
                    "5": {"status": "ok", "expected_return_pct": 2, "up_probability_pct": 62, "oos_directional_accuracy_pct": 55},
                    "20": {"status": "ok", "expected_return_pct": 4, "up_probability_pct": 60},
                }
            },
            "backtest": {"average_net_return": 1.2, "average_excess_return": 0.4},
            "risk": {"status": "ok", "stop_price": 90},
            "facts": {"current_price": 100},
        }
        signal = build_quant_signal(candidate)
        self.assertEqual(signal["action"], "BUY")
        self.assertTrue(signal["buy_gate_passed"])
        candidate["backtest"]["average_net_return"] = -0.1
        rejected = build_quant_signal(candidate)
        self.assertNotEqual(rejected["action"], "BUY")
        self.assertNotIn("BUY", rejected["allowed_ai_actions"])

    def test_walk_forward_uses_non_overlapping_trades_and_costs(self):
        prices = synthetic_prices()
        result = walk_forward_backtest(
            prices,
            prices,
            strategy="balanced",
            holding_days=5,
            commission_bps=15,
            slippage_bps=10,
        )
        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["sample_count"], 5)
        self.assertEqual(result["cost_bps"], 25)
        exits = [pd.Timestamp(item["exit_date"]) for item in result["trades"]]
        entries = [pd.Timestamp(item["entry_date"]) for item in result["trades"]]
        self.assertTrue(all(entries[index] > exits[index - 1] for index in range(1, len(entries))))

    def test_risk_budget_caps_position(self):
        config = replace(AppConfig(), account_equity=100_000_000, max_position_pct=0.15)
        risk = RiskEngine(config).assess_position(
            {
                "facts": {
                    "current_price": 50_000,
                    "atr14": 1_500,
                    "recent_low20": 47_000,
                    "avg_amount20": 10_000_000_000,
                }
            }
        )
        self.assertEqual(risk["status"], "ok")
        self.assertLessEqual(risk["position_value"], 15_000_000)
        self.assertLessEqual(risk["risk_budget"], config.account_equity * config.risk_per_trade)

    def test_ai_hard_gate_avoids_insufficient_evidence(self):
        review = AIJudge(AppConfig()).review(
            {
                "eligible": False,
                "data_completeness": 0.2,
                "backtest": {"status": "insufficient_data", "reason": "표본 없음"},
                "risk": {"status": "rejected", "reason": "ATR 없음"},
            }
        )
        self.assertEqual(review["action"], "AVOID")
        self.assertEqual(review["source"], "HARD_GATE")

    def test_holdings_parser_validates_and_normalizes(self):
        holdings, errors = parse_holdings("5930 12 71,500\n000660 3 185000")
        self.assertFalse(errors)
        self.assertEqual(holdings[0]["ticker"], "005930")
        self.assertEqual(holdings[0]["average_price"], 71500)


class StorageTests(unittest.TestCase):
    def test_price_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = Storage(Path(temp_dir) / "test.db")
            original = synthetic_prices(30)
            storage.upsert_prices("005930", original, "TEST")
            loaded = storage.load_prices("005930")
            self.assertEqual(len(loaded), 30)
            self.assertAlmostEqual(float(loaded.iloc[-1]["Close"]), float(original.iloc[-1]["Close"]))

    def test_post_evaluation_persists_realized_and_benchmark_returns(self):
        class FakeDataEngine:
            def get_prices(self, ticker, **kwargs):
                dates = pd.bdate_range("2026-01-05", periods=7)
                if ticker == "KS11":
                    close = np.array([100, 101, 102, 103, 104, 105, 106], dtype=float)
                else:
                    close = np.array([101, 102, 104, 106, 110, 111, 112], dtype=float)
                return pd.DataFrame(
                    {
                        "Date": dates,
                        "Open": close,
                        "High": close + 1,
                        "Low": close - 1,
                        "Close": close,
                        "Volume": 1000,
                        "Change": pd.Series(close).pct_change(),
                    }
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            config = replace(AppConfig(), db_path=Path(temp_dir) / "eval.db")
            storage = Storage(config.db_path)
            storage.save_recommendation(
                {
                    "run_id": "run-eval",
                    "ticker": "005930",
                    "name": "테스트",
                    "market": "KOSPI",
                    "sector": "반도체",
                    "as_of_date": "2026-01-02",
                    "strategy": "balanced",
                    "entry_price": 100,
                    "stop_price": 95,
                    "target_weight": 0.1,
                    "quantity": 10,
                    "total_score": 80,
                    "ai_decision": "BUY",
                    "ai_confidence": 60,
                    "thesis": "테스트",
                    "review_json": "{}",
                    "horizon_days": 5,
                    "benchmark_symbol": "KS11",
                    "created_at": "2026-01-02T00:00:00Z",
                }
            )
            engine = PerformanceEngine(config, storage, FakeDataEngine())
            evaluated = engine.evaluate_due(as_of=pd.Timestamp("2026-01-12").date())
            self.assertEqual(len(evaluated), 1)
            self.assertEqual(evaluated[0]["outcome"], "SUCCESS")
            self.assertGreater(evaluated[0]["net_return"], 0)
            self.assertGreater(evaluated[0]["excess_return"], 0)
            self.assertEqual(storage.history().iloc[0]["outcome"], "SUCCESS")


class SnapshotTests(unittest.TestCase):
    def test_public_snapshot_keeps_sources_and_excludes_indicator_frame(self):
        result = {
            "run_id": "verified-run",
            "as_of_date": "2026-08-18",
            "strategy": "balanced",
            "universe_count": 2713,
            "liquid_universe_count": 371,
            "filtered_universe_count": 80,
            "deep_analysis_count": 1,
            "portfolio": {
                "regime": {
                    "regime": "neutral",
                    "cash_target": 0.3,
                    "reason": "추세 조건 혼재",
                },
                "cash_weight": 1.0,
                "positions": [],
            },
            "data_status": {},
            "errors": [],
            "ranked": [
                {
                    "ticker": "005930",
                    "name": "삼성전자",
                    "market": "KOSPI",
                    "sector": "반도체",
                    "total_score": 71.2,
                    "data_completeness": 0.9,
                    "facts": {
                        "current_price": 100,
                        "price_as_of": "2026-08-18",
                        "price_source": "TEST",
                        "news_status": "ok",
                        "news_detail_coverage": {"covered": 1, "attempted": 1},
                        "news": [{"title": "검증 기사", "summary": "짧은 출처 요약"}],
                    },
                    "forecast": {"status": "ok", "horizons": {}},
                    "backtest": {"status": "ok", "sample_count": 9},
                    "risk": {"status": "ok", "stop_price": 90},
                    "trade_plan": {"order_side": "NONE"},
                    "ai_review": {"action": "WATCH", "source": "GROQ"},
                    "indicators": synthetic_prices(10),
                }
            ],
        }
        snapshot = build_public_snapshot(result)
        self.assertEqual(snapshot["run_id"], "verified-run")
        self.assertEqual(snapshot["portfolio"]["regime"], "neutral")
        self.assertEqual(snapshot["portfolio"]["regime_reason"], "추세 조건 혼재")
        self.assertEqual(snapshot["decisions"][0]["evidence"]["news"][0]["title"], "검증 기사")
        self.assertNotIn("indicators", snapshot["decisions"][0])


if __name__ == "__main__":
    unittest.main()

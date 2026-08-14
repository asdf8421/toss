"""Compatibility wrapper around the evidence-first pipeline.

The old implementation stopped at the first matching stocks and silently converted
failed KRX data to zero. This wrapper ranks the inspected universe and exposes the
same Korean column names for callers that still import ``run_stock_screener``.
"""

import pandas as pd

from pipeline import FundManagerPipeline


def run_stock_screener(target_count: int = 3, mode: str = "rebound") -> pd.DataFrame:
    strategy = "breakout" if mode == "surge" else mode
    if strategy not in {"balanced", "rebound", "breakout"}:
        strategy = "balanced"
    pipeline = FundManagerPipeline()
    result = pipeline.run(
        strategy=strategy,
        universe_limit=max(80, target_count * 20),
        deep_analysis_limit=max(10, target_count * 3),
        max_positions=target_count,
    )
    rows = []
    for candidate in result["ranked"][:target_count]:
        facts = candidate.get("facts", {})
        fundamentals = facts.get("fundamentals", {})
        review = candidate.get("ai_review", {})
        backtest = candidate.get("backtest", {})
        rows.append(
            {
                "종목코드": candidate["ticker"],
                "종목명": candidate["name"],
                "현재가": facts.get("current_price"),
                "종합점수": candidate["total_score"],
                "RSI(14)": facts.get("rsi14"),
                "PER": fundamentals.get("per"),
                "PBR": fundamentals.get("pbr"),
                "외인순매수": facts.get("foreign_net"),
                "기관순매수": facts.get("institution_net"),
                "독립표본수": backtest.get("sample_count"),
                "비용차감평균수익(%)": backtest.get("average_net_return"),
                "AI결정": review.get("decision"),
                "데이터완성도": candidate.get("data_completeness"),
                "근거": " / ".join(candidate.get("reasons", [])),
            }
        )
    return pd.DataFrame(rows)

"""Backward-compatible indicator facade.

New code should import :func:`quant_engine.calculate_indicators` directly.
"""

from data_collector import get_daily_prices
from quant_engine import calculate_indicators


def apply_quant_indicators(df):
    result = calculate_indicators(df)
    result["RSI"] = result["RSI14"]
    result["MACD_Signal"] = result["MACD_SIGNAL"]
    return result


if __name__ == "__main__":
    samsung = get_daily_prices("005930", days=300)
    analyzed = apply_quant_indicators(samsung)
    print(analyzed[["Date", "Close", "RSI", "MACD", "ATR14", "BBL", "BBU"]].tail())


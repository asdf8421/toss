from __future__ import annotations

from typing import Any


def parse_holdings(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse one holding per line: ticker, quantity, average price."""
    holdings: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for line_number, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = [part.strip().replace(",", "") for part in line.replace("\t", " ").split()]
        if len(parts) != 3:
            errors.append(f"{line_number}행: 종목코드 수량 평균단가 3개 값을 입력하세요.")
            continue
        ticker = parts[0].zfill(6)
        try:
            quantity = int(parts[1])
            average_price = float(parts[2])
        except ValueError:
            errors.append(f"{line_number}행: 수량과 평균단가는 숫자여야 합니다.")
            continue
        if not ticker.isdigit() or len(ticker) != 6:
            errors.append(f"{line_number}행: 종목코드는 6자리 숫자여야 합니다.")
        elif quantity <= 0 or average_price <= 0:
            errors.append(f"{line_number}행: 수량과 평균단가는 0보다 커야 합니다.")
        elif ticker in seen:
            errors.append(f"{line_number}행: {ticker}가 중복되었습니다.")
        else:
            seen.add(ticker)
            holdings.append(
                {"ticker": ticker, "quantity": quantity, "average_price": average_price}
            )
    return holdings, errors

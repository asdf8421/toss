from __future__ import annotations

import io
import math
import threading
import zipfile
from datetime import date, datetime, timedelta
from typing import Any
from xml.etree import ElementTree

import FinanceDataReader as fdr
import pandas as pd
import requests

from config import AppConfig
from naver_scraper import (
    get_naver_disclosures,
    get_naver_investor_flow,
    get_naver_stock_snapshot,
)
from storage import Storage, utc_now


class DataEngine:
    """Collects point-in-time-labelled facts and persists every successful fetch."""

    def __init__(self, config: AppConfig, storage: Storage):
        self.config = config
        self.storage = storage
        self._corp_codes: dict[str, str] | None = None
        self._corp_codes_lock = threading.Lock()

    def get_universe(self, as_of: date | None = None, force: bool = False) -> pd.DataFrame:
        del force  # Reserved for a future TTL cache policy.
        as_of = as_of or date.today()
        market = fdr.StockListing("KRX")
        descriptions = fdr.StockListing("KRX-DESC")

        market = market.rename(
            columns={
                "Code": "ticker",
                "Name": "name",
                "Market": "market",
                "Close": "close",
                "Volume": "volume",
                "Amount": "amount",
                "Marcap": "market_cap",
            }
        )
        descriptions = descriptions.rename(
            columns={
                "Code": "ticker",
                "Sector": "sector",
                "Industry": "industry",
            }
        )
        universe = market.merge(
            descriptions[["ticker", "sector", "industry"]],
            on="ticker",
            how="left",
        )
        keep = [
            "ticker", "name", "market", "sector", "industry", "close", "volume",
            "amount", "market_cap",
        ]
        universe = universe[keep].copy()
        universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)
        for column in ["close", "volume", "amount", "market_cap"]:
            universe[column] = pd.to_numeric(universe[column], errors="coerce")
        # KRX-DESC's Sector can be a listing department (e.g. 벤처기업부).
        # Industry is the economically meaningful concentration bucket.
        universe["industry"] = universe["industry"].fillna("미분류")
        universe["sector"] = universe["industry"].where(
            universe["industry"] != "미분류", universe["sector"].fillna("미분류")
        )
        universe = universe[universe["market"].isin(["KOSPI", "KOSDAQ"])]
        universe = universe.drop_duplicates("ticker")

        fetched_at = utc_now()
        records = []
        for row in universe.to_dict("records"):
            records.append(
                {
                    **row,
                    "source": "FinanceDataReader:KRX+KRX-DESC",
                    "as_of_date": as_of.isoformat(),
                    "fetched_at": fetched_at,
                }
            )
        self.storage.upsert_universe(records)
        return universe.sort_values(["amount", "market_cap"], ascending=False).reset_index(drop=True)

    def filter_universe(self, universe: pd.DataFrame, limit: int = 0) -> pd.DataFrame:
        result = universe.copy()
        result = result[(result["close"] > 0) & (result["volume"] > 0)]
        if self.config.min_market_cap > 0:
            result = result[result["market_cap"] >= self.config.min_market_cap]
        if self.config.min_daily_amount > 0:
            result = result[result["amount"] >= self.config.min_daily_amount]
        result = result.sort_values(["amount", "market_cap"], ascending=False)
        if limit > 0:
            result = result.head(limit)
        return result.reset_index(drop=True)

    def get_prices(
        self,
        ticker: str,
        *,
        as_of: date | None = None,
        lookback_days: int | None = None,
        force: bool = False,
    ) -> pd.DataFrame:
        as_of = as_of or date.today()
        lookback_days = lookback_days or self.config.price_lookback_days
        start = as_of - timedelta(days=lookback_days)

        if not force:
            cached = self.storage.load_prices(ticker, start.isoformat(), as_of.isoformat())
            if not cached.empty:
                latest = cached["Date"].max().date()
                if latest >= as_of - timedelta(days=4) and len(cached) >= 120:
                    return _price_columns(cached)

        df = fdr.DataReader(ticker, start.isoformat(), as_of.isoformat())
        if df.empty:
            return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume", "Change"])
        df = df.reset_index()
        if "Date" not in df.columns:
            df.rename(columns={df.columns[0]: "Date"}, inplace=True)
        df["Date"] = pd.to_datetime(df["Date"])
        for column in ["Open", "High", "Low", "Close", "Volume", "Change"]:
            if column not in df.columns:
                df[column] = pd.NA
            df[column] = pd.to_numeric(df[column], errors="coerce")
        df = df[(df["Close"] > 0) & (df["Volume"] >= 0)].sort_values("Date")
        self.storage.upsert_prices(ticker, _price_columns(df), "FinanceDataReader")
        return _price_columns(df)

    def get_benchmark(self, market: str, as_of: date | None = None) -> tuple[str, pd.DataFrame]:
        symbol = self.config.benchmark_kosdaq if market == "KOSDAQ" else self.config.benchmark_kospi
        return symbol, self.get_prices(symbol, as_of=as_of)

    def get_fundamentals(
        self, ticker: str, as_of: date | None = None, force: bool = False
    ) -> dict[str, Any]:
        as_of = as_of or date.today()
        if not force:
            cached = self.storage.cached_fundamental(ticker, date.today().isoformat())
            if cached:
                cached["error"] = None
                return cached
        result = {
            "ticker": ticker,
            "period": "",
            "as_of_date": as_of.isoformat(),
            "revenue": None,
            "operating_profit": None,
            "net_income": None,
            "operating_margin": None,
            "roe": None,
            "debt_ratio": None,
            "per": None,
            "pbr": None,
            "eps": None,
            "bps": None,
            "revenue_growth": None,
            "operating_profit_growth": None,
            "net_income_growth": None,
            "source": "FinanceDataReader:NAVER/FINSTATE-2Y",
            "status": "unavailable",
            "fetched_at": utc_now(),
            "error": None,
        }
        try:
            frame = fdr.SnapDataReader(f"NAVER/FINSTATE-2Y/{ticker}")
            if frame.empty:
                raise ValueError("empty financial statement")
            frame = frame.copy()
            frame.index = pd.to_datetime(frame.index)

            # Annual results are conservatively considered usable from April of next year.
            safe_year = as_of.year - 1 if as_of.month >= 4 else as_of.year - 2
            actual = frame[frame.index.year <= safe_year].sort_index()
            if actual.empty:
                raise ValueError("no completed fiscal year available")
            current = actual.iloc[-1]
            previous = actual.iloc[-2] if len(actual) >= 2 else None
            period = actual.index[-1].strftime("%Y-%m-%d")

            result.update(
                {
                    "period": period,
                    "revenue": _num(current.get("매출액")),
                    "operating_profit": _num(current.get("영업이익")),
                    "net_income": _num(current.get("당기순이익")),
                    "operating_margin": _num(current.get("영업이익률")),
                    "roe": _num(current.get("ROE(%)")),
                    "debt_ratio": _num(current.get("부채비율")),
                    "per": _num(current.get("PER(배)")),
                    "pbr": _num(current.get("PBR(배)")),
                    "eps": _num(current.get("EPS(원)")),
                    "bps": _num(current.get("BPS(원)")),
                    "revenue_growth": _growth(current.get("매출액"), previous.get("매출액") if previous is not None else None),
                    "operating_profit_growth": _growth(current.get("영업이익"), previous.get("영업이익") if previous is not None else None),
                    "net_income_growth": _growth(current.get("당기순이익"), previous.get("당기순이익") if previous is not None else None),
                    "status": "ok",
                }
            )
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"

        storage_values = {key: value for key, value in result.items() if key != "error"}
        if not storage_values["period"]:
            storage_values["period"] = f"unavailable-{as_of.isoformat()}"
        self.storage.upsert_fundamental(storage_values)
        return result

    def get_investor_flow(
        self, ticker: str, as_of: date | None = None, force: bool = False
    ) -> dict[str, Any]:
        as_of = as_of or date.today()
        if not force:
            cached = self.storage.cached_flow(ticker, date.today().isoformat())
            if cached:
                cached.setdefault("observations", None)
                return cached
        result = {
            "ticker": ticker,
            "date": as_of.isoformat(),
            "foreign_net": None,
            "institution_net": None,
            "source": "pykrx:KRX",
            "status": "missing_configuration",
            "error": "KRX_ID/KRX_PW가 없어 수급을 0이 아닌 결측으로 처리했습니다.",
            "fetched_at": utc_now(),
        }
        if not self.config.krx_ready:
            fallback = get_naver_investor_flow(
                ticker,
                as_of=as_of,
                timeout=self.config.request_timeout,
                verify_ssl=self.config.verify_ssl,
            )
            fallback["fetched_at"] = utc_now()
            self.storage.upsert_flow(_storage_flow(fallback))
            return fallback

        try:
            from pykrx import stock

            start = (as_of - timedelta(days=10)).strftime("%Y%m%d")
            end = as_of.strftime("%Y%m%d")
            frame = stock.get_market_trading_value_by_date(start, end, ticker)
            if frame.empty:
                raise ValueError("KRX returned an empty investor-flow frame")
            foreign_column = "외국인합계" if "외국인합계" in frame.columns else "외국인"
            result.update(
                {
                    "foreign_net": float(frame[foreign_column].sum()),
                    "institution_net": float(frame["기관합계"].sum()),
                    "status": "ok",
                    "error": None,
                }
            )
        except Exception as exc:
            result["status"] = "error"
            result["error"] = f"{type(exc).__name__}: {exc}"
        if result["status"] != "ok":
            fallback = get_naver_investor_flow(
                ticker,
                as_of=as_of,
                timeout=self.config.request_timeout,
                verify_ssl=self.config.verify_ssl,
            )
            fallback["fetched_at"] = utc_now()
            if fallback["status"] == "ok":
                fallback["error"] = f"KRX 실패 후 대체 수집: {result['error']}"
                self.storage.upsert_flow(_storage_flow(fallback))
                return fallback
        self.storage.upsert_flow(_storage_flow(result))
        return result

    def get_news(
        self, ticker: str, as_of: date | None = None, force: bool = False
    ) -> dict[str, Any]:
        if not force:
            cached = self.storage.cached_news(ticker, date.today().isoformat())
            if cached:
                detailed = sum(bool(item.get("summary")) for item in cached)
                attempted = min(len(cached), self.config.news_detail_limit)
                if detailed >= attempted:
                    return {
                        "ticker": ticker,
                        "per": None,
                        "pbr": None,
                        "news": cached,
                        "source": "SQLite daily cache",
                        "as_of_date": (as_of or date.today()).isoformat(),
                        "status": "ok",
                        "error": None,
                        "article_detail_coverage": {
                            "covered": detailed,
                            "attempted": attempted,
                        },
                    }
        snapshot = get_naver_stock_snapshot(
            ticker,
            as_of=as_of,
            timeout=self.config.request_timeout,
            verify_ssl=self.config.verify_ssl,
            detail_limit=self.config.news_detail_limit,
        )
        fetched_at = utc_now()
        for article in snapshot["news"]:
            article["fetched_at"] = fetched_at
        self.storage.upsert_news(snapshot["news"])
        return snapshot

    def get_disclosures(
        self, ticker: str, as_of: date | None = None, force: bool = False
    ) -> dict[str, Any]:
        as_of = as_of or date.today()
        if not force:
            cached = self.storage.cached_disclosures(ticker, date.today().isoformat())
            if cached:
                return {"status": "ok", "error": None, "items": cached, "source": "SQLite daily cache"}
        if not self.config.dart_api_key:
            return self._get_disclosure_fallback(ticker, as_of, "DART_API_KEY 미설정")
        try:
            corp_code = self._get_corp_codes().get(ticker)
            if not corp_code:
                raise KeyError(f"DART corporation code not found for {ticker}")
            params = {
                "crtfc_key": self.config.dart_api_key,
                "corp_code": corp_code,
                "bgn_de": (as_of - timedelta(days=45)).strftime("%Y%m%d"),
                "end_de": as_of.strftime("%Y%m%d"),
                "page_count": 20,
            }
            response = requests.get(
                "https://opendart.fss.or.kr/api/list.json",
                params=params,
                timeout=self.config.request_timeout,
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") not in {"000", "013"}:
                raise ValueError(f"OpenDART {payload.get('status')}: {payload.get('message')}")
            items = []
            fetched_at = utc_now()
            for item in payload.get("list", []):
                receipt_no = item["rcept_no"]
                items.append(
                    {
                        "ticker": ticker,
                        "receipt_no": receipt_no,
                        "receipt_date": _format_yyyymmdd(item.get("rcept_dt", "")),
                        "report_name": item.get("report_nm", ""),
                        "corp_name": item.get("corp_name", ""),
                        "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}",
                        "source": "OpenDART",
                        "fetched_at": fetched_at,
                    }
                )
            self.storage.upsert_disclosures(items)
            return {"status": "ok", "error": None, "items": items}
        except Exception as exc:
            return self._get_disclosure_fallback(
                ticker,
                as_of,
                f"OpenDART 실패: {type(exc).__name__}: {exc}",
            )

    def _get_disclosure_fallback(self, ticker: str, as_of: date, reason: str) -> dict[str, Any]:
        fallback = get_naver_disclosures(
            ticker,
            as_of=as_of,
            timeout=self.config.request_timeout,
            verify_ssl=self.config.verify_ssl,
        )
        fetched_at = utc_now()
        for item in fallback["items"]:
            item["fetched_at"] = fetched_at
        fallback["error"] = reason if fallback["status"] == "ok" else f"{reason}; {fallback.get('error')}"
        self.storage.upsert_disclosures(fallback["items"])
        return fallback

    def _get_corp_codes(self) -> dict[str, str]:
        if self._corp_codes is not None:
            return self._corp_codes
        with self._corp_codes_lock:
            if self._corp_codes is not None:
                return self._corp_codes
            response = requests.get(
                "https://opendart.fss.or.kr/api/corpCode.xml",
                params={"crtfc_key": self.config.dart_api_key},
                timeout=max(self.config.request_timeout, 30),
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                xml_name = archive.namelist()[0]
                root = ElementTree.fromstring(archive.read(xml_name))
            mapping = {}
            for item in root.findall("list"):
                stock_code = (item.findtext("stock_code") or "").strip()
                corp_code = (item.findtext("corp_code") or "").strip()
                if stock_code and corp_code:
                    mapping[stock_code.zfill(6)] = corp_code
            self._corp_codes = mapping
            return mapping


def _price_columns(df: pd.DataFrame) -> pd.DataFrame:
    columns = ["Date", "Open", "High", "Low", "Close", "Volume", "Change"]
    result = df.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA
    return result[columns].sort_values("Date").reset_index(drop=True)


def _num(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _growth(current: Any, previous: Any) -> float | None:
    current_num = _num(current)
    previous_num = _num(previous)
    if current_num is None or previous_num in (None, 0):
        return None
    return round((current_num / abs(previous_num) - 1) * 100, 3)


def _format_yyyymmdd(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError:
        return value


def _storage_flow(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: values.get(key)
        for key in [
            "ticker", "date", "foreign_net", "institution_net", "source",
            "status", "error", "fetched_at",
        ]
    }

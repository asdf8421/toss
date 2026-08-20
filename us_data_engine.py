from __future__ import annotations

import html
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
import requests

from config import AppConfig
from storage import Storage, utc_now


NAVER_WORLD_API = "https://api.stock.naver.com/stock/exchange"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

POSITIVE_WORDS = {
    "beats", "beat", "growth", "raises", "raised", "upgrade", "upgraded",
    "record", "profit", "surge", "approval", "approved", "contract", "buyback",
    "dividend", "strong", "outperform", "expands", "partnership",
}
NEGATIVE_WORDS = {
    "misses", "miss", "cuts", "cut", "downgrade", "downgraded", "loss",
    "lawsuit", "probe", "investigation", "recall", "decline", "warning",
    "weak", "layoffs", "fraud", "delay", "blocked", "risk",
}


class USDataEngine:
    """Free-source US adapter with explicit source and limitation labels."""

    market_scope = "US"
    currency = "USD"

    def __init__(self, config: AppConfig, storage: Storage):
        self.config = config
        self.storage = storage
        self._cik_by_ticker: dict[str, int] | None = None

    def get_universe(self, as_of: date | None = None, force: bool = False) -> pd.DataFrame:
        del force
        as_of = as_of or date.today()
        rows: list[dict[str, Any]] = []
        for exchange in ("NASDAQ", "NYSE", "AMEX"):
            rows.extend(self._get_exchange_listing(exchange))
        if not rows:
            raise ValueError("Naver US listing API returned no stocks")

        universe = pd.DataFrame(rows).drop_duplicates("ticker")
        universe = universe.sort_values(
            ["amount", "market_cap"], ascending=False, na_position="last"
        ).reset_index(drop=True)
        fetched_at = utc_now()
        records = [
            {
                **row,
                "source": "NAVER_WORLD:marketValue (free)",
                "as_of_date": as_of.isoformat(),
                "fetched_at": fetched_at,
            }
            for row in universe.to_dict("records")
        ]
        self.storage.upsert_universe(records)
        return universe

    def _get_exchange_listing(self, exchange: str) -> list[dict[str, Any]]:
        rows = []
        for page in range(1, self.config.us_universe_pages + 1):
            response = requests.get(
                f"{NAVER_WORLD_API}/{exchange}/marketValue",
                params={"page": page, "pageSize": 60},
                headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.8"},
                timeout=self.config.request_timeout,
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            payload = response.json()
            stocks = payload.get("stocks") or []
            if not stocks:
                break
            for item in stocks:
                ticker = str(item.get("symbolCode") or "").strip().upper()
                if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker):
                    continue
                if item.get("stockEndType") != "stock":
                    continue
                industry = item.get("industryCodeType") or {}
                market_cap = _number(item.get("marketValueRaw") or item.get("marketValue"))
                close = _number(item.get("closePriceRaw") or item.get("closePrice"))
                volume = _number(
                    item.get("accumulatedTradingVolumeRaw")
                    or item.get("accumulatedTradingVolume")
                )
                amount = _number(item.get("accumulatedTradingValueRaw"))
                if amount is None and close is not None and volume is not None:
                    amount = close * volume
                industry_code = str(industry.get("code") or "")
                rows.append(
                    {
                        "ticker": ticker,
                        "name": str(item.get("stockNameEng") or ticker),
                        "market": exchange,
                        "sector": f"US-{industry_code[:4]}" if industry_code else "US-미분류",
                        "industry": f"US-{industry_code}" if industry_code else "US-미분류",
                        "close": close,
                        "volume": volume,
                        "amount": amount,
                        "market_cap": market_cap,
                        "price_source": "FinanceDataReader:YAHOO free daily bars",
                    }
                )
        return rows

    def filter_universe(self, universe: pd.DataFrame, limit: int = 0) -> pd.DataFrame:
        result = universe.copy()
        result = result[(result["close"] > 0) & (result["volume"] > 0)]
        result = result[result["market_cap"].fillna(0) >= self.config.us_min_market_cap]
        result = result[result["amount"].fillna(0) >= self.config.us_min_daily_amount]
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
        ticker = ticker.upper()
        as_of = as_of or date.today()
        lookback_days = lookback_days or self.config.price_lookback_days
        start = as_of - timedelta(days=lookback_days)
        if not force:
            cached = self.storage.load_prices(ticker, start.isoformat(), as_of.isoformat())
            if not cached.empty:
                latest = cached["Date"].max().date()
                if latest >= as_of - timedelta(days=4) and len(cached) >= 120:
                    cached.attrs["source"] = "FinanceDataReader:YAHOO free daily bars"
                    return _price_columns(cached)

        yahoo_ticker = ticker.replace(".", "-")
        frame = fdr.DataReader(yahoo_ticker, start.isoformat(), as_of.isoformat())
        if frame.empty:
            return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume", "Change"])
        frame = frame.reset_index()
        if "Date" not in frame.columns:
            frame.rename(columns={frame.columns[0]: "Date"}, inplace=True)
        frame["Date"] = pd.to_datetime(frame["Date"])
        for column in ["Open", "High", "Low", "Close", "Volume"]:
            frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
        frame["Change"] = frame["Close"].pct_change()
        frame = frame[(frame["Close"] > 0) & (frame["Volume"] >= 0)].sort_values("Date")
        result = _price_columns(frame)
        result.attrs["source"] = "FinanceDataReader:YAHOO free daily bars"
        self.storage.upsert_prices(ticker, result, result.attrs["source"])
        return result

    def get_benchmark(self, market: str, as_of: date | None = None) -> tuple[str, pd.DataFrame]:
        del market
        return self.config.benchmark_us, self.get_prices(self.config.benchmark_us, as_of=as_of)

    def get_fundamentals(
        self, ticker: str, as_of: date | None = None, force: bool = False
    ) -> dict[str, Any]:
        ticker = ticker.upper()
        as_of = as_of or date.today()
        if not force:
            cached = self.storage.cached_fundamental(ticker, date.today().isoformat())
            if cached:
                cached["error"] = None
                return cached
        result = _empty_fundamental(ticker, as_of)
        try:
            cik = self._cik(ticker)
            if cik is None:
                raise KeyError(f"SEC CIK not found for {ticker}")
            payload = self._sec_get(SEC_COMPANY_FACTS.format(cik=cik))
            facts = payload.get("facts") or {}
            us_gaap = facts.get("us-gaap") or {}
            dei = facts.get("dei") or {}

            revenue = _annual_series(
                us_gaap,
                [
                    "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "RevenueFromContractWithCustomerIncludingAssessedTax",
                    "Revenues",
                    "SalesRevenueNet",
                ],
                as_of,
                ["USD"],
            )
            operating = _annual_series(us_gaap, ["OperatingIncomeLoss"], as_of, ["USD"])
            net_income = _annual_series(
                us_gaap,
                ["NetIncomeLoss", "ProfitLoss"],
                as_of,
                ["USD"],
            )
            equity = _annual_series(
                us_gaap,
                ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
                as_of,
                ["USD"],
            )
            liabilities = _annual_series(us_gaap, ["Liabilities"], as_of, ["USD"])
            eps = _annual_series(
                us_gaap,
                ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"],
                as_of,
                ["USD/shares"],
            )
            shares = _annual_series(
                dei,
                ["EntityCommonStockSharesOutstanding"],
                as_of,
                ["shares"],
                allow_non_fy=True,
            )
            if not revenue and not net_income:
                raise ValueError("SEC annual financial facts unavailable")

            current_revenue, previous_revenue = _latest_pair(revenue)
            current_operating, previous_operating = _latest_pair(operating)
            current_net, previous_net = _latest_pair(net_income)
            current_equity, _ = _latest_pair(equity)
            current_liabilities, _ = _latest_pair(liabilities)
            current_eps, _ = _latest_pair(eps)
            current_shares, _ = _latest_pair(shares)
            prices = self.get_prices(ticker, as_of=as_of)
            price = float(prices.iloc[-1]["Close"]) if not prices.empty else None
            bps = _safe_div(current_equity, current_shares)
            period = (
                (revenue[-1]["end"] if revenue else None)
                or (net_income[-1]["end"] if net_income else None)
                or as_of.isoformat()
            )
            result.update(
                {
                    "period": period,
                    "revenue": current_revenue,
                    "operating_profit": current_operating,
                    "net_income": current_net,
                    "operating_margin": _pct(current_operating, current_revenue),
                    "roe": _pct(current_net, current_equity),
                    "debt_ratio": _pct(current_liabilities, current_equity),
                    "per": _safe_div(price, current_eps) if current_eps and current_eps > 0 else None,
                    "pbr": _safe_div(price, bps) if bps and bps > 0 else None,
                    "eps": current_eps,
                    "bps": bps,
                    "revenue_growth": _growth(current_revenue, previous_revenue),
                    "operating_profit_growth": _growth(current_operating, previous_operating),
                    "net_income_growth": _growth(current_net, previous_net),
                    "status": "ok",
                    "error": None,
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
        ticker = ticker.upper()
        as_of = as_of or date.today()
        if not force:
            cached = self.storage.cached_flow(ticker, date.today().isoformat())
            if cached and cached.get("direct_score") is not None:
                cached.setdefault("observations", 10)
                return cached
        result = {
            "ticker": ticker,
            "date": as_of.isoformat(),
            "foreign_net": None,
            "institution_net": None,
            "direct_score": None,
            "method": "10-day signed dollar-volume pressure; not institutional ownership flow",
            "source": "YAHOO daily bars via FinanceDataReader (free volume-flow proxy)",
            "status": "unavailable",
            "error": None,
            "observations": 0,
            "fetched_at": utc_now(),
        }
        try:
            prices = self.get_prices(ticker, as_of=as_of)
            recent = prices.tail(11).copy()
            if len(recent) < 11:
                raise ValueError("fewer than 10 return observations")
            close = pd.to_numeric(recent["Close"], errors="coerce")
            volume = pd.to_numeric(recent["Volume"], errors="coerce")
            signed_value = np.sign(close.pct_change()) * close * volume
            average_value = (close * volume).iloc[1:].mean()
            normalized = float(signed_value.iloc[1:].sum() / average_value) if average_value > 0 else math.nan
            if not math.isfinite(normalized):
                raise ValueError("invalid dollar-volume pressure")
            result.update(
                {
                    "direct_score": round(float(np.clip(50 + normalized * 12.5, 0, 100)), 2),
                    "status": "ok",
                    "observations": 10,
                }
            )
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        self.storage.upsert_flow(result)
        return result

    def get_news(
        self, ticker: str, as_of: date | None = None, force: bool = False
    ) -> dict[str, Any]:
        ticker = ticker.upper()
        as_of = as_of or date.today()
        if not force:
            cached = self.storage.cached_news(ticker, date.today().isoformat())
            if cached:
                return {
                    "ticker": ticker,
                    "news": cached,
                    "source": "SQLite daily cache:Google News RSS",
                    "as_of_date": as_of.isoformat(),
                    "status": "partial",
                    "error": None,
                    "article_detail_coverage": {"covered": 0, "attempted": len(cached)},
                }
        result = {
            "ticker": ticker,
            "news": [],
            "source": "Google News RSS (free headlines)",
            "as_of_date": as_of.isoformat(),
            "status": "unavailable",
            "error": None,
            "article_detail_coverage": {"covered": 0, "attempted": 0},
        }
        try:
            response = requests.get(
                GOOGLE_NEWS_RSS,
                params={
                    "q": f'"{ticker}" stock when:7d',
                    "hl": "en-US",
                    "gl": "US",
                    "ceid": "US:en",
                },
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=self.config.request_timeout,
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
            fetched_at = utc_now()
            articles = []
            for item in root.findall(".//item")[:10]:
                title = " ".join((item.findtext("title") or "").split())
                link = item.findtext("link") or ""
                if not title or not link:
                    continue
                published = _rss_date(item.findtext("pubDate"), as_of)
                if published > as_of:
                    continue
                source_node = item.find("source")
                publisher = source_node.text if source_node is not None else "Google News RSS"
                articles.append(
                    {
                        "ticker": ticker,
                        "published_date": published.isoformat(),
                        "title": title,
                        "url": link,
                        "publisher": publisher,
                        "published_at": item.findtext("pubDate"),
                        "summary": None,
                        "content_source": link,
                        "detail_status": "headline_only",
                        "sentiment": _headline_sentiment(title),
                        "source": "GOOGLE_NEWS_RSS",
                        "fetched_at": fetched_at,
                    }
                )
            result["news"] = articles
            result["article_detail_coverage"] = {"covered": 0, "attempted": len(articles)}
            result["status"] = "partial" if articles else "unavailable"
            self.storage.upsert_news(articles)
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    def get_disclosures(
        self, ticker: str, as_of: date | None = None, force: bool = False
    ) -> dict[str, Any]:
        ticker = ticker.upper()
        as_of = as_of or date.today()
        if not force:
            cached = self.storage.cached_disclosures(ticker, date.today().isoformat())
            if cached:
                return {
                    "status": "ok",
                    "error": None,
                    "items": cached,
                    "source": "SQLite daily cache:SEC EDGAR",
                }
        result = {"status": "unavailable", "error": None, "items": [], "source": "SEC EDGAR submissions API"}
        try:
            cik = self._cik(ticker)
            if cik is None:
                raise KeyError(f"SEC CIK not found for {ticker}")
            payload = self._sec_get(SEC_SUBMISSIONS.format(cik=cik))
            recent = ((payload.get("filings") or {}).get("recent") or {})
            forms = recent.get("form") or []
            start = as_of - timedelta(days=45)
            accepted_forms = {"8-K", "10-Q", "10-K", "4", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}
            items = []
            fetched_at = utc_now()
            for index, form in enumerate(forms):
                if form not in accepted_forms:
                    continue
                filing_date = date.fromisoformat(recent["filingDate"][index])
                if filing_date < start or filing_date > as_of:
                    continue
                accession = recent["accessionNumber"][index]
                accession_path = accession.replace("-", "")
                primary = recent["primaryDocument"][index]
                items.append(
                    {
                        "ticker": ticker,
                        "receipt_no": f"SEC-{accession}",
                        "receipt_date": filing_date.isoformat(),
                        "report_name": f"SEC {form} · {recent['primaryDocDescription'][index] or primary}",
                        "corp_name": str(payload.get("name") or ticker),
                        "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/{primary}",
                        "source": "SEC EDGAR",
                        "fetched_at": fetched_at,
                    }
                )
                if len(items) >= 20:
                    break
            self.storage.upsert_disclosures(items)
            result.update({"status": "ok", "items": items})
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    def _cik(self, ticker: str) -> int | None:
        if self._cik_by_ticker is None:
            payload = self._sec_get(SEC_TICKERS_URL)
            self._cik_by_ticker = {
                str(item.get("ticker") or "").upper(): int(item["cik_str"])
                for item in payload.values()
                if item.get("ticker") and item.get("cik_str") is not None
            }
        return self._cik_by_ticker.get(ticker.replace("-", ".")) or self._cik_by_ticker.get(ticker)

    def _sec_get(self, url: str) -> dict[str, Any]:
        response = requests.get(
            url,
            headers={
                "User-Agent": self.config.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=max(self.config.request_timeout, 20),
            verify=self.config.verify_ssl,
        )
        response.raise_for_status()
        return response.json()


def _empty_fundamental(ticker: str, as_of: date) -> dict[str, Any]:
    return {
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
        "source": "SEC EDGAR companyfacts (free official)",
        "status": "unavailable",
        "fetched_at": utc_now(),
        "error": None,
    }


def _annual_series(
    namespace: dict[str, Any],
    tags: list[str],
    as_of: date,
    unit_priority: list[str],
    *,
    allow_non_fy: bool = False,
) -> list[dict[str, Any]]:
    candidates: list[list[dict[str, Any]]] = []
    for tag in tags:
        units = ((namespace.get(tag) or {}).get("units") or {})
        records: list[dict[str, Any]] = []
        for unit in unit_priority:
            records = units.get(unit) or []
            if records:
                break
        filtered = []
        for item in records:
            try:
                filed = date.fromisoformat(item["filed"])
                end = date.fromisoformat(item["end"])
                value = float(item["val"])
            except (KeyError, TypeError, ValueError):
                continue
            if filed > as_of or end > as_of:
                continue
            if item.get("form") not in {"10-K", "10-K/A"}:
                continue
            if not allow_non_fy and item.get("fp") != "FY":
                continue
            filtered.append({"end": end.isoformat(), "filed": filed.isoformat(), "value": value})
        if not filtered:
            continue
        by_end: dict[str, dict[str, Any]] = {}
        for item in filtered:
            current = by_end.get(item["end"])
            if current is None or item["filed"] > current["filed"]:
                by_end[item["end"]] = item
        candidates.append(sorted(by_end.values(), key=lambda item: item["end"]))
    if not candidates:
        return []
    return max(candidates, key=lambda series: (series[-1]["end"], len(series)))


def _latest_pair(series: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    if not series:
        return None, None
    current = _number(series[-1].get("value"))
    previous = _number(series[-2].get("value")) if len(series) >= 2 else None
    return current, previous


def _price_columns(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["Date", "Open", "High", "Low", "Close", "Volume", "Change"]
    result = frame.copy()
    source = frame.attrs.get("source")
    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA
    result = result[columns].sort_values("Date").reset_index(drop=True)
    if source:
        result.attrs["source"] = source
    return result


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).replace(",", ""))
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    value = numerator / denominator
    return value if math.isfinite(value) else None


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    value = _safe_div(numerator, denominator)
    return value * 100 if value is not None else None


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current / abs(previous) - 1) * 100


def _rss_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).date()
    except (TypeError, ValueError):
        return fallback


def _headline_sentiment(title: str) -> float:
    words = set(re.findall(r"[a-z]+", html.unescape(title).lower()))
    positive = len(words & POSITIVE_WORDS)
    negative = len(words & NEGATIVE_WORDS)
    if positive + negative == 0:
        return 0.0
    return round((positive - negative) / (positive + negative), 3)

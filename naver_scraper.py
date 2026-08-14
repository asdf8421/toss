from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import AppConfig


NAVER_FINANCE = "https://finance.naver.com"
POSITIVE_WORDS = {
    "호실적", "상향", "수주", "흑자", "성장", "돌파", "급등", "최대", "개선",
    "증가", "강세", "신고가", "배당", "자사주", "승인", "계약", "공급",
}
NEGATIVE_WORDS = {
    "적자", "하향", "급락", "감소", "부진", "손실", "소송", "제재", "리콜",
    "유상증자", "횡령", "배임", "약세", "중단", "취소", "경고", "압수수색",
}


def headline_sentiment(title: str) -> float:
    """Transparent lexical sentiment in [-1, 1]; no LLM-generated numbers."""
    positive = sum(word in title for word in POSITIVE_WORDS)
    negative = sum(word in title for word in NEGATIVE_WORDS)
    if positive + negative == 0:
        return 0.0
    return round((positive - negative) / (positive + negative), 3)


def _parse_mmdd(text: str, as_of: date) -> str:
    match = re.search(r"(\d{2})/(\d{2})", text)
    if not match:
        return as_of.isoformat()
    month, day = map(int, match.groups())
    year = as_of.year
    try:
        candidate = date(year, month, day)
        if candidate > as_of:
            candidate = date(year - 1, month, day)
        return candidate.isoformat()
    except ValueError:
        return as_of.isoformat()


def get_naver_stock_snapshot(
    ticker: str,
    *,
    as_of: date | None = None,
    timeout: int = 10,
    verify_ssl: bool = True,
) -> dict:
    as_of = as_of or datetime.now().date()
    url = f"{NAVER_FINANCE}/item/main.naver?code={ticker}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
    }
    result = {
        "ticker": ticker,
        "per": None,
        "pbr": None,
        "news": [],
        "source": url,
        "as_of_date": as_of.isoformat(),
        "status": "unavailable",
        "error": None,
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            verify=verify_ssl,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        per_tag = soup.select_one("#_per")
        pbr_tag = soup.select_one("#_pbr")
        result["per"] = _parse_number(per_tag.get_text(strip=True) if per_tag else None)
        result["pbr"] = _parse_number(pbr_tag.get_text(strip=True) if pbr_tag else None)

        articles = []
        seen_urls = set()
        for item in soup.select(".sub_section.news_section ul li")[:10]:
            anchor = item.select_one("a[href]")
            if not anchor:
                continue
            title = " ".join(anchor.get_text(" ", strip=True).split())
            article_url = urljoin(NAVER_FINANCE, anchor.get("href", ""))
            if not title or not article_url or article_url in seen_urls:
                continue
            seen_urls.add(article_url)
            articles.append(
                {
                    "ticker": ticker,
                    "published_date": _parse_mmdd(item.get_text(" ", strip=True), as_of),
                    "title": title,
                    "url": article_url,
                    "publisher": "네이버 금융 연결 기사",
                    "sentiment": headline_sentiment(title),
                    "source": "NAVER_FINANCE",
                }
            )
        result["news"] = articles
        result["status"] = "ok" if (result["per"] is not None or articles) else "partial"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def get_naver_investor_flow(
    ticker: str,
    *,
    as_of: date | None = None,
    days: int = 10,
    timeout: int = 10,
    verify_ssl: bool = True,
) -> dict:
    """Collect institution/foreign net shares and estimate net value at daily close.

    Naver exposes net share counts, not official KRX net trading value. The returned
    monetary figures are therefore explicitly labelled estimates (shares * close).
    """
    as_of = as_of or datetime.now().date()
    url = f"{NAVER_FINANCE}/item/frgn.naver?code={ticker}&page=1"
    result = {
        "ticker": ticker,
        "date": as_of.isoformat(),
        "foreign_net": None,
        "institution_net": None,
        "foreign_net_shares": None,
        "institution_net_shares": None,
        "source": "NAVER_FINANCE:frgn (estimated value = net shares x daily close)",
        "status": "unavailable",
        "error": None,
        "observations": 0,
    }
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=timeout,
            verify=verify_ssl,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        target = None
        for table in soup.select("table.type2"):
            if "기관" in table.get_text(" ", strip=True) and "외국인" in table.get_text(" ", strip=True):
                target = table
                break
        if target is None:
            raise ValueError("investor flow table not found")

        start = as_of.fromordinal(as_of.toordinal() - days)
        institution_value = foreign_value = 0.0
        institution_shares = foreign_shares = 0.0
        observations = 0
        latest_observation = None
        for row in target.select("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
            if len(cells) < 7 or not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", cells[0]):
                continue
            row_date = datetime.strptime(cells[0], "%Y.%m.%d").date()
            if row_date > as_of or row_date < start:
                continue
            close = _parse_signed_number(cells[1])
            institution = _parse_signed_number(cells[5])
            foreign = _parse_signed_number(cells[6])
            if close is None or institution is None or foreign is None:
                continue
            institution_value += institution * close
            foreign_value += foreign * close
            institution_shares += institution
            foreign_shares += foreign
            observations += 1
            latest_observation = max(latest_observation, row_date) if latest_observation else row_date
        if observations == 0:
            raise ValueError("no investor rows in requested date window")
        result.update(
            {
                "date": latest_observation.isoformat(),
                "foreign_net": round(foreign_value, 2),
                "institution_net": round(institution_value, 2),
                "foreign_net_shares": round(foreign_shares, 2),
                "institution_net_shares": round(institution_shares, 2),
                "status": "ok",
                "observations": observations,
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def get_naver_disclosures(
    ticker: str,
    *,
    as_of: date | None = None,
    days: int = 45,
    timeout: int = 10,
    verify_ssl: bool = True,
) -> dict:
    """Collect KOSCOM-supplied disclosure notices surfaced by Naver Finance."""
    as_of = as_of or datetime.now().date()
    url = f"{NAVER_FINANCE}/item/news_notice.naver?code={ticker}&page=1"
    result = {"status": "unavailable", "error": None, "items": [], "source": url}
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=timeout,
            verify=verify_ssl,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        start = as_of.fromordinal(as_of.toordinal() - days)
        items = []
        for row in soup.select("table.type6 tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
            anchor = row.select_one("a[href]")
            if len(cells) < 3 or anchor is None:
                continue
            try:
                receipt_date = datetime.strptime(cells[-1], "%Y.%m.%d").date()
            except ValueError:
                continue
            if receipt_date > as_of or receipt_date < start:
                continue
            item_url = urljoin(NAVER_FINANCE, anchor.get("href", ""))
            match = re.search(r"(?:\?|&)no=(\d+)", item_url)
            receipt_no = f"NAVER-{match.group(1)}" if match else f"NAVER-{ticker}-{receipt_date}-{len(items)}"
            items.append(
                {
                    "ticker": ticker,
                    "receipt_no": receipt_no,
                    "receipt_date": receipt_date.isoformat(),
                    "report_name": cells[0],
                    "corp_name": "",
                    "url": item_url,
                    "source": f"NAVER_FINANCE:{cells[1] or 'KOSCOM'}",
                }
            )
        result["items"] = items
        result["status"] = "ok" if items else "partial"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def get_naver_finance_info(ticker: str) -> dict:
    """Backward-compatible facade for the old screener module."""
    config = AppConfig()
    snapshot = get_naver_stock_snapshot(
        ticker,
        timeout=config.request_timeout,
        verify_ssl=config.verify_ssl,
    )
    news_text = "\n".join(f"- {item['title']}" for item in snapshot["news"])
    if not news_text:
        news_text = "최근 주요 뉴스가 없습니다."
    return {
        "PER": snapshot["per"] if snapshot["per"] is not None else "N/A",
        "PBR": snapshot["pbr"] if snapshot["pbr"] is not None else "N/A",
        "News": news_text,
    }


def _parse_number(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _parse_signed_number(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace(",", "").replace("+", "").strip()
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


SCHEMA = """
CREATE TABLE IF NOT EXISTS universe (
    ticker TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT,
    sector TEXT,
    industry TEXT,
    close REAL,
    volume REAL,
    amount REAL,
    market_cap REAL,
    source TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    change REAL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker TEXT NOT NULL,
    period TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    revenue REAL,
    operating_profit REAL,
    net_income REAL,
    operating_margin REAL,
    roe REAL,
    debt_ratio REAL,
    per REAL,
    pbr REAL,
    eps REAL,
    bps REAL,
    revenue_growth REAL,
    operating_profit_growth REAL,
    net_income_growth REAL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (ticker, period, source)
);

CREATE TABLE IF NOT EXISTS investor_flows (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    foreign_net REAL,
    institution_net REAL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (ticker, date, source)
);

CREATE TABLE IF NOT EXISTS news (
    ticker TEXT NOT NULL,
    published_date TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    publisher TEXT,
    published_at TEXT,
    summary TEXT,
    content_source TEXT,
    detail_status TEXT,
    sentiment REAL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (ticker, url)
);

CREATE TABLE IF NOT EXISTS disclosures (
    ticker TEXT NOT NULL,
    receipt_no TEXT NOT NULL,
    receipt_date TEXT NOT NULL,
    report_name TEXT NOT NULL,
    corp_name TEXT,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (receipt_no)
);

CREATE TABLE IF NOT EXISTS scan_runs (
    run_id TEXT PRIMARY KEY,
    as_of_date TEXT NOT NULL,
    strategy TEXT NOT NULL,
    universe_count INTEGER NOT NULL,
    eligible_count INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS factor_scores (
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    total_score REAL NOT NULL,
    value_score REAL,
    momentum_score REAL,
    flow_score REAL,
    quality_score REAL,
    volatility_score REAL,
    news_score REAL,
    data_completeness REAL NOT NULL,
    eligible INTEGER NOT NULL,
    reasons_json TEXT NOT NULL,
    facts_json TEXT NOT NULL,
    PRIMARY KEY (run_id, ticker)
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    market TEXT,
    sector TEXT,
    as_of_date TEXT NOT NULL,
    strategy TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL,
    target_weight REAL,
    quantity INTEGER,
    total_score REAL NOT NULL,
    ai_decision TEXT NOT NULL,
    ai_confidence REAL,
    thesis TEXT,
    review_json TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    benchmark_symbol TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, ticker)
);

CREATE TABLE IF NOT EXISTS evaluations (
    recommendation_id INTEGER PRIMARY KEY,
    evaluation_date TEXT NOT NULL,
    exit_price REAL NOT NULL,
    gross_return REAL NOT NULL,
    net_return REAL NOT NULL,
    benchmark_return REAL,
    excess_return REAL,
    stop_hit INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    failure_reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(recommendation_id) REFERENCES recommendations(id)
);

CREATE TABLE IF NOT EXISTS batch_jobs (
    job_id TEXT PRIMARY KEY,
    as_of_date TEXT NOT NULL,
    strategy TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    current_count INTEGER NOT NULL,
    total_count INTEGER NOT NULL,
    message TEXT,
    result_run_id TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Storage:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            existing = {
                row["name"] for row in conn.execute("PRAGMA table_info(news)").fetchall()
            }
            additions = {
                "published_at": "TEXT",
                "summary": "TEXT",
                "content_source": "TEXT",
                "detail_status": "TEXT",
            }
            for column, column_type in additions.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE news ADD COLUMN {column} {column_type}")

    def upsert_universe(self, rows: Iterable[dict[str, Any]]) -> None:
        sql = """
        INSERT INTO universe (
            ticker,name,market,sector,industry,close,volume,amount,market_cap,
            source,as_of_date,fetched_at
        ) VALUES (
            :ticker,:name,:market,:sector,:industry,:close,:volume,:amount,:market_cap,
            :source,:as_of_date,:fetched_at
        ) ON CONFLICT(ticker) DO UPDATE SET
            name=excluded.name, market=excluded.market, sector=excluded.sector,
            industry=excluded.industry, close=excluded.close, volume=excluded.volume,
            amount=excluded.amount, market_cap=excluded.market_cap,
            source=excluded.source, as_of_date=excluded.as_of_date,
            fetched_at=excluded.fetched_at
        """
        with self.connect() as conn:
            conn.executemany(sql, list(rows))

    def upsert_prices(self, ticker: str, df: pd.DataFrame, source: str) -> None:
        if df.empty:
            return
        fetched_at = utc_now()
        rows = []
        for row in df.itertuples(index=False):
            rows.append(
                (
                    ticker,
                    pd.Timestamp(row.Date).strftime("%Y-%m-%d"),
                    _number(row.Open),
                    _number(row.High),
                    _number(row.Low),
                    _number(row.Close),
                    _number(row.Volume),
                    _number(getattr(row, "Change", None)),
                    source,
                    fetched_at,
                )
            )
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(ticker,date) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume,
                    change=excluded.change, source=excluded.source,
                    fetched_at=excluded.fetched_at
                """,
                rows,
            )

    def load_prices(
        self, ticker: str, start: str | None = None, end: str | None = None
    ) -> pd.DataFrame:
        where = ["ticker = ?"]
        params: list[Any] = [ticker]
        if start:
            where.append("date >= ?")
            params.append(start)
        if end:
            where.append("date <= ?")
            params.append(end)
        query = f"SELECT * FROM prices WHERE {' AND '.join(where)} ORDER BY date"
        with self.connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        if not df.empty:
            df["Date"] = pd.to_datetime(df.pop("date"))
            df.rename(
                columns={
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                    "change": "Change",
                },
                inplace=True,
            )
        return df

    def upsert_fundamental(self, values: dict[str, Any]) -> None:
        columns = [
            "ticker", "period", "as_of_date", "revenue", "operating_profit",
            "net_income", "operating_margin", "roe", "debt_ratio", "per", "pbr",
            "eps", "bps", "revenue_growth", "operating_profit_growth",
            "net_income_growth", "source", "status", "fetched_at",
        ]
        params = {column: values.get(column) for column in columns}
        placeholders = ",".join(f":{column}" for column in columns)
        with self.connect() as conn:
            conn.execute(
                f"""
                INSERT INTO fundamentals ({','.join(columns)}) VALUES ({placeholders})
                ON CONFLICT(ticker,period,source) DO UPDATE SET
                    as_of_date=excluded.as_of_date, revenue=excluded.revenue,
                    operating_profit=excluded.operating_profit,
                    net_income=excluded.net_income,
                    operating_margin=excluded.operating_margin, roe=excluded.roe,
                    debt_ratio=excluded.debt_ratio, per=excluded.per, pbr=excluded.pbr,
                    eps=excluded.eps, bps=excluded.bps,
                    revenue_growth=excluded.revenue_growth,
                    operating_profit_growth=excluded.operating_profit_growth,
                    net_income_growth=excluded.net_income_growth,
                    status=excluded.status, fetched_at=excluded.fetched_at
                """,
                params,
            )

    def cached_fundamental(self, ticker: str, fetched_on: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM fundamentals
                WHERE ticker=? AND status='ok' AND date(fetched_at,'+9 hours')=?
                ORDER BY period DESC, fetched_at DESC LIMIT 1
                """,
                (ticker, fetched_on),
            ).fetchone()
        return dict(row) if row else None

    def upsert_flow(self, values: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO investor_flows (
                    ticker,date,foreign_net,institution_net,source,status,error,fetched_at
                ) VALUES (
                    :ticker,:date,:foreign_net,:institution_net,:source,:status,:error,:fetched_at
                ) ON CONFLICT(ticker,date,source) DO UPDATE SET
                    foreign_net=excluded.foreign_net,
                    institution_net=excluded.institution_net,
                    status=excluded.status,error=excluded.error,fetched_at=excluded.fetched_at
                """,
                values,
            )

    def cached_flow(self, ticker: str, fetched_on: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM investor_flows
                WHERE ticker=? AND status='ok' AND date(fetched_at,'+9 hours')=?
                ORDER BY fetched_at DESC LIMIT 1
                """,
                (ticker, fetched_on),
            ).fetchone()
        return dict(row) if row else None

    def upsert_news(self, rows: Iterable[dict[str, Any]]) -> None:
        rows = list(rows)
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO news (
                    ticker,published_date,title,url,publisher,published_at,summary,
                    content_source,detail_status,sentiment,source,fetched_at
                ) VALUES (
                    :ticker,:published_date,:title,:url,:publisher,:published_at,:summary,
                    :content_source,:detail_status,:sentiment,:source,:fetched_at
                ) ON CONFLICT(ticker,url) DO UPDATE SET
                    published_date=excluded.published_date,title=excluded.title,
                    publisher=excluded.publisher,published_at=excluded.published_at,
                    summary=excluded.summary,content_source=excluded.content_source,
                    detail_status=excluded.detail_status,sentiment=excluded.sentiment,
                    fetched_at=excluded.fetched_at
                """,
                [
                    {
                        **row,
                        "published_at": row.get("published_at"),
                        "summary": row.get("summary"),
                        "content_source": row.get("content_source"),
                        "detail_status": row.get("detail_status"),
                    }
                    for row in rows
                ],
            )

    def cached_news(self, ticker: str, fetched_on: str, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM news
                WHERE ticker=? AND date(fetched_at,'+9 hours')=?
                ORDER BY published_date DESC LIMIT ?
                """,
                (ticker, fetched_on, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_disclosures(self, rows: Iterable[dict[str, Any]]) -> None:
        rows = list(rows)
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO disclosures (
                    ticker,receipt_no,receipt_date,report_name,corp_name,url,source,fetched_at
                ) VALUES (
                    :ticker,:receipt_no,:receipt_date,:report_name,:corp_name,:url,:source,:fetched_at
                ) ON CONFLICT(receipt_no) DO UPDATE SET
                    report_name=excluded.report_name,receipt_date=excluded.receipt_date,
                    fetched_at=excluded.fetched_at
                """,
                rows,
            )

    def cached_disclosures(
        self, ticker: str, fetched_on: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM disclosures
                WHERE ticker=? AND date(fetched_at,'+9 hours')=?
                ORDER BY receipt_date DESC LIMIT ?
                """,
                (ticker, fetched_on, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def start_batch_job(self, job_id: str, as_of_date: str, strategy: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO batch_jobs (
                    job_id,as_of_date,strategy,status,stage,current_count,total_count,
                    message,result_run_id,started_at,updated_at,finished_at
                ) VALUES (?,?,?,'running','starting',0,0,NULL,NULL,?,?,NULL)
                ON CONFLICT(job_id) DO UPDATE SET
                    status='running',stage='resuming',message='캐시에서 재개',
                    updated_at=excluded.updated_at,finished_at=NULL
                """,
                (job_id, as_of_date, strategy, now, now),
            )

    def update_batch_job(
        self,
        job_id: str,
        *,
        status: str,
        stage: str,
        current: int,
        total: int,
        message: str,
        result_run_id: str | None = None,
    ) -> None:
        now = utc_now()
        finished_at = now if status in {"complete", "failed"} else None
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE batch_jobs SET status=?,stage=?,current_count=?,total_count=?,
                    message=?,result_run_id=COALESCE(?,result_run_id),updated_at=?,finished_at=?
                WHERE job_id=?
                """,
                (
                    status, stage, current, total, message, result_run_id,
                    now, finished_at, job_id,
                ),
            )

    def batch_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM batch_jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def latest_batch_job(self, full_only: bool = True) -> dict[str, Any] | None:
        where = "WHERE job_id LIKE 'full-%'" if full_only else ""
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT * FROM batch_jobs {where} ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def factor_ranking(self, run_id: str) -> pd.DataFrame:
        with self.connect() as conn:
            df = pd.read_sql_query(
                """
                SELECT f.*, u.name, u.market, u.sector, u.industry
                FROM factor_scores f
                LEFT JOIN universe u ON u.ticker=f.ticker
                WHERE f.run_id=?
                ORDER BY f.total_score DESC
                """,
                conn,
                params=[run_id],
            )
        if df.empty:
            return df
        details = df["facts_json"].map(lambda text: json.loads(text or "{}"))
        df["sample_count"] = details.map(lambda item: item.get("backtest", {}).get("sample_count"))
        df["average_net_return"] = details.map(
            lambda item: item.get("backtest", {}).get("average_net_return")
        )
        df["average_excess_return"] = details.map(
            lambda item: item.get("backtest", {}).get("average_excess_return")
        )
        df["risk_status"] = details.map(lambda item: item.get("risk", {}).get("status"))
        return df

    def save_scan_run(
        self,
        run_id: str,
        as_of_date: str,
        strategy: str,
        universe_count: int,
        eligible_count: int,
        config: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO scan_runs VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    as_of_date,
                    strategy,
                    universe_count,
                    eligible_count,
                    json.dumps(config, ensure_ascii=False, default=str),
                    utc_now(),
                ),
            )

    def save_factor_scores(self, run_id: str, rows: Iterable[dict[str, Any]]) -> None:
        payload = []
        for row in rows:
            payload.append(
                (
                    run_id,
                    row["ticker"],
                    row["total_score"],
                    row.get("value_score"),
                    row.get("momentum_score"),
                    row.get("flow_score"),
                    row.get("quality_score"),
                    row.get("volatility_score"),
                    row.get("news_score"),
                    row["data_completeness"],
                    int(row["eligible"]),
                    json.dumps(row.get("reasons", []), ensure_ascii=False, default=str),
                    json.dumps(row.get("facts", {}), ensure_ascii=False, default=str),
                )
            )
        if not payload:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO factor_scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id,ticker) DO UPDATE SET
                    total_score=excluded.total_score,value_score=excluded.value_score,
                    momentum_score=excluded.momentum_score,flow_score=excluded.flow_score,
                    quality_score=excluded.quality_score,
                    volatility_score=excluded.volatility_score,
                    news_score=excluded.news_score,
                    data_completeness=excluded.data_completeness,
                    eligible=excluded.eligible,reasons_json=excluded.reasons_json,
                    facts_json=excluded.facts_json
                """,
                payload,
            )

    def save_recommendation(self, values: dict[str, Any]) -> int:
        columns = [
            "run_id", "ticker", "name", "market", "sector", "as_of_date",
            "strategy", "entry_price", "stop_price", "target_weight", "quantity",
            "total_score", "ai_decision", "ai_confidence", "thesis", "review_json",
            "horizon_days", "benchmark_symbol", "created_at",
        ]
        params = {column: values.get(column) for column in columns}
        with self.connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO recommendations ({','.join(columns)}) "
                f"VALUES ({','.join(':'+c for c in columns)})",
                params,
            )
            row = conn.execute(
                "SELECT id FROM recommendations WHERE run_id=? AND ticker=?",
                (values["run_id"], values["ticker"]),
            ).fetchone()
        return int(row["id"])

    def pending_recommendations(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.* FROM recommendations r
                LEFT JOIN evaluations e ON e.recommendation_id=r.id
                WHERE e.recommendation_id IS NULL
                  AND r.ai_decision IN ('BUY', 'HOLD')
                ORDER BY r.as_of_date
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def save_evaluation(self, values: dict[str, Any]) -> None:
        columns = [
            "recommendation_id", "evaluation_date", "exit_price", "gross_return",
            "net_return", "benchmark_return", "excess_return", "stop_hit", "outcome",
            "failure_reason", "created_at",
        ]
        with self.connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO evaluations ({','.join(columns)}) "
                f"VALUES ({','.join(':'+c for c in columns)})",
                {column: values.get(column) for column in columns},
            )

    def history(self, limit: int = 200) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql_query(
                """
                SELECT r.*, e.evaluation_date, e.net_return, e.benchmark_return,
                       e.excess_return, e.stop_hit, e.outcome, e.failure_reason
                FROM recommendations r
                LEFT JOIN evaluations e ON e.recommendation_id=r.id
                ORDER BY r.created_at DESC LIMIT ?
                """,
                conn,
                params=[limit],
            )


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

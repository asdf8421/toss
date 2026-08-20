"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type Horizon = {
  status?: string;
  expected_return_pct?: number;
  up_probability_pct?: number;
};

type MarketRegime =
  | string
  | {
      regime?: string;
      cash_target?: number;
      reason?: string;
    };

type MarketScope = "KR" | "US";

type Decision = {
  ticker: string;
  name: string;
  market?: string;
  sector?: string;
  action: string;
  confidence?: number;
  score?: number;
  data_completeness?: number;
  factors?: Record<string, number | null>;
  price?: { current?: number; as_of?: string; source?: string };
  forecast?: { status?: string; horizons?: Record<string, Horizon> };
  backtest?: Record<string, unknown>;
  risk?: Record<string, unknown>;
  trade_plan?: Record<string, unknown>;
  ai_review?: Record<string, unknown>;
  evidence?: {
    fundamental_status?: string;
    fundamental_source?: string;
    fundamental_period?: string;
    fundamentals?: Record<string, unknown>;
    flow_status?: string;
    flow_source?: string;
    flow_observations?: number;
    flow_method?: string;
    news_status?: string;
    news_source?: string;
    news_detail_coverage?: { covered?: number; attempted?: number };
    news?: Array<Record<string, unknown>>;
    disclosure_status?: string;
    disclosure_source?: string;
    disclosures?: Array<Record<string, unknown>>;
  };
};

type Snapshot = {
  schema_version: number;
  market_scope?: MarketScope;
  currency?: "KRW" | "USD";
  run_id: string;
  as_of_date: string;
  generated_at: string;
  market_data_mode: string;
  market_data_notice: string;
  strategy: string;
  coverage: {
    universe?: number;
    liquid_universe?: number;
    price_screened?: number;
    deep_analyzed?: number;
  };
  data_status?: Record<string, unknown>;
  portfolio?: {
    regime?: MarketRegime;
    regime_reason?: string;
    invested_weight?: number;
    cash_weight?: number;
    capital_at_risk_pct?: number;
  };
  decisions: Decision[];
  errors?: string[];
};

type ActionDirective = {
  tone: "go" | "wait" | "stop";
  badge: string;
  headline: string;
  summary: string;
  steps: [string, string, string];
};

type AnalysisState = {
  request_id?: string;
  status: "idle" | "queued" | "complete" | "failed" | "cooldown";
  requested_at?: string;
  completed_at?: string;
  completed_run_id?: string;
  message?: string;
  retry_after_seconds?: number;
};

const actionNames: Record<string, string> = {
  BUY: "매수",
  WATCH: "관찰",
  AVOID: "매수 제외",
  HOLD: "보유",
  REDUCE: "비중 축소",
  SELL: "매도",
  NO_ACTION: "판단 중단",
};

export default function Home() {
  const [marketScope, setMarketScope] = useState<MarketScope>("KR");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "empty" | "error">("loading");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [analysisState, setAnalysisState] = useState<AnalysisState>({ status: "idle" });
  const [analysisRequesting, setAnalysisRequesting] = useState(false);
  const [cooldownSeconds, setCooldownSeconds] = useState(0);

  const loadSnapshot = useCallback(async () => {
    setStatus((current) => (current === "ready" ? current : "loading"));
    try {
      const response = await fetch(`/api/snapshot?market=${marketScope}`, { cache: "no-store" });
      if (response.status === 404) {
        setSnapshot(null);
        setStatus("empty");
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const next = (await response.json()) as Snapshot;
      setSnapshot(next);
      setSelectedTicker(next.decisions?.[0]?.ticker ?? null);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, [marketScope]);

  const loadAnalysisState = useCallback(async () => {
    try {
      const response = await fetch(`/api/analyze?market=${marketScope}`, { cache: "no-store" });
      if (!response.ok) return;
      const next = (await response.json()) as AnalysisState;
      const retryAfter = Math.max(0, Number(next.retry_after_seconds ?? 0));
      setCooldownSeconds(retryAfter);
      setAnalysisState(
        next.status === "complete" && retryAfter > 0
          ? { ...next, status: "cooldown" }
          : next,
      );
      if (next.status === "complete") void loadSnapshot();
    } catch {
      // Snapshot display remains usable even when the trigger status endpoint is unavailable.
    }
  }, [loadSnapshot, marketScope]);

  const startAnalysis = useCallback(async () => {
    setAnalysisRequesting(true);
    try {
      const response = await fetch(`/api/analyze?market=${marketScope}`, { method: "POST", cache: "no-store" });
      const next = (await response.json()) as AnalysisState;
      const retryAfter = Math.max(0, Number(next.retry_after_seconds ?? 0));
      if (response.status === 429 && retryAfter > 0) {
        setCooldownSeconds(retryAfter);
        setAnalysisState({ ...next, status: "cooldown" });
        return;
      }
      setCooldownSeconds(0);
      setAnalysisState(next);
      if (!response.ok && !next.status) {
        setAnalysisState({ status: "failed", message: "분석 실행 요청을 시작하지 못했습니다." });
      }
    } catch {
      setAnalysisState({ status: "failed", message: "분석 실행 서버에 연결하지 못했습니다." });
    } finally {
      setAnalysisRequesting(false);
    }
  }, [marketScope]);

  const switchMarket = useCallback((next: MarketScope) => {
    if (next === marketScope) return;
    const url = new URL(window.location.href);
    url.searchParams.set("market", next);
    window.history.replaceState({}, "", url);
    setSnapshot(null);
    setSelectedTicker(null);
    setStatus("loading");
    setAnalysisState({ status: "idle" });
    setCooldownSeconds(0);
    setMarketScope(next);
  }, [marketScope]);

  useEffect(() => {
    const requested = new URL(window.location.href).searchParams.get("market")?.toUpperCase();
    if (requested === "US") setMarketScope("US");
  }, []);

  useEffect(() => {
    void loadSnapshot();
    const timer = window.setInterval(() => void loadSnapshot(), 300_000);
    return () => window.clearInterval(timer);
  }, [loadSnapshot]);

  useEffect(() => {
    void loadAnalysisState();
  }, [loadAnalysisState]);

  useEffect(() => {
    if (analysisState.status !== "queued") return;
    const timer = window.setInterval(() => void loadAnalysisState(), 10_000);
    return () => window.clearInterval(timer);
  }, [analysisState.status, loadAnalysisState]);

  useEffect(() => {
    if (cooldownSeconds <= 0) return;
    const timer = window.setInterval(() => {
      setCooldownSeconds((current) => {
        const next = Math.max(0, current - 1);
        if (next === 0) {
          setAnalysisState((state) => state.status === "cooldown"
            ? { ...state, status: "complete", retry_after_seconds: 0 }
            : state);
        }
        return next;
      });
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [cooldownSeconds > 0]);

  const selected = useMemo(
    () => snapshot?.decisions.find((item) => item.ticker === selectedTicker) ?? snapshot?.decisions[0],
    [snapshot, selectedTicker],
  );

  const counts = useMemo(() => {
    const rows = snapshot?.decisions ?? [];
    return {
      buy: rows.filter((item) => item.action === "BUY").length,
      watch: rows.filter((item) => ["WATCH", "HOLD"].includes(item.action)).length,
      avoid: rows.filter((item) => ["AVOID", "REDUCE", "SELL", "NO_ACTION"].includes(item.action)).length,
    };
  }, [snapshot]);

  const directive = useMemo(() => snapshot ? buildActionDirective(snapshot) : null, [snapshot]);

  return (
    <main className="app-shell">
      <aside className="side-nav">
        <a className="brand" href="#top" aria-label="AI Fund Manager 홈">
          <span className="brand-symbol">FM</span>
          <span><strong>AI Fund Manager</strong><small>Evidence First</small></span>
        </a>
        <nav aria-label="대시보드 메뉴">
          <a className="active" href="#today-action"><span>01</span> 오늘 할 일</a>
          <a href="#decision"><span>02</span> 종목별 판단</a>
          <a href="#evidence"><span>03</span> 근거 확인</a>
          <a href="#method"><span>04</span> 검증 기준</a>
        </nav>
        <div className="side-status">
          <span className={`status-dot ${status}`} />
          <div>
            <strong>{status === "ready" ? "최신 분석 연결" : "분석 데이터 확인 중"}</strong>
            <small>{snapshot ? `Run ${snapshot.run_id.slice(0, 10)}` : "정적 추천값 없음"}</small>
          </div>
        </div>
        <a className="repo-link" href="https://github.com/asdf8421/toss" target="_blank" rel="noreferrer">
          분석 코드 보기 <span>↗</span>
        </a>
      </aside>

      <div className="workspace" id="top">
        <div className="market-tabs" role="tablist" aria-label="분석 시장 선택">
          <button type="button" role="tab" aria-selected={marketScope === "KR"} className={marketScope === "KR" ? "active" : ""} onClick={() => switchMarket("KR")}>
            <span>KR</span><strong>한국 증시</strong><small>KOSPI · KOSDAQ</small>
          </button>
          <button type="button" role="tab" aria-selected={marketScope === "US"} className={marketScope === "US" ? "active" : ""} onClick={() => switchMarket("US")}>
            <span>US</span><strong>미국 증시</strong><small>NASDAQ · NYSE · AMEX</small>
          </button>
        </div>
        <header className="topbar">
          <div>
            <p className="eyebrow">LATEST VERIFIED DECISION</p>
            <h1>{marketScope === "US" ? "미국 증시에서 오늘 무엇을 해야 하는가" : "한국 증시에서 오늘 무엇을 해야 하는가"}</h1>
            <p className="subtitle">{marketScope === "US" ? "무료 미국 시세·SEC 재무·공시·뉴스를 수집한 뒤 정량 검증과 Groq 심사를 거친 행동만 보여줍니다." : "검증된 수치와 Groq 심사를 바탕으로 매수·매도·관찰·현금 유지 중 하나를 먼저 보여줍니다."}</p>
          </div>
          <div className="report-meta">
            <span>최종 갱신</span>
            <strong>{snapshot ? formatDateTime(snapshot.generated_at) : "확인 중"}</strong>
            <button
              type="button"
              className="analysis-button"
              onClick={() => void startAnalysis()}
              disabled={analysisRequesting || analysisState.status === "queued" || cooldownSeconds > 0}
            >
              {marketScope === "US" ? `미국 ${analysisButtonText(analysisState.status, analysisRequesting, cooldownSeconds)}` : analysisButtonText(analysisState.status, analysisRequesting, cooldownSeconds)}
            </button>
            <button type="button" className="refresh-button" onClick={() => void loadSnapshot()}>화면만 새로고침</button>
          </div>
        </header>

        <section className="freshness-banner" aria-live="polite">
          <strong>{marketScope === "US" ? "무료 데이터 · 실시간 통합호가 아님" : "실시간 호가 아님"}</strong>
          <span>{snapshot?.market_data_notice ?? "저장된 추천값을 표시하지 않고 최신 분석 스냅샷을 기다리고 있습니다."}</span>
        </section>

        {analysisState.status !== "idle" && (
          <section className={`analysis-progress ${analysisState.status}`} aria-live="polite">
            <div>
              <strong>{analysisStatusTitle(analysisState.status)}</strong>
              <span>{analysisState.status === "cooldown"
                ? `최신 분석이 반영됐습니다. ${formatCooldown(cooldownSeconds)} 후 다시 실행할 수 있습니다.`
                : analysisState.message ?? "분석 상태를 확인하고 있습니다."}</span>
            </div>
            {analysisState.status === "queued" && <div className="progress-track"><i /></div>}
            {analysisState.requested_at && <small>요청 시각 {formatDateTime(analysisState.requested_at)}</small>}
          </section>
        )}

        {status !== "ready" || !snapshot ? (
          <section className="panel live-empty">
            <p className="eyebrow">LIVE ANALYSIS STATUS</p>
            <h2>{status === "error" ? "분석 서버 연결을 확인할 수 없습니다" : status === "empty" ? "아직 게시된 분석이 없습니다" : "최신 분석을 불러오는 중입니다"}</h2>
            <p>{marketScope === "US" ? "화면에 임의 종목이나 예측 숫자를 채우지 않습니다. 미국 무료 데이터 수집과 Groq 심사가 끝난 결과만 여기에 나타납니다." : "화면에 임의 종목이나 예측 숫자를 채우지 않습니다. 데이터 수집과 Groq 심사가 끝난 결과만 여기에 나타납니다."}</p>
            {status === "empty" ? <button type="button" className="primary-button" onClick={() => void startAnalysis()}>{marketScope === "US" ? "미국 증시 첫 분석 실행" : "첫 분석 실행"}</button> : <button type="button" className="primary-button" onClick={() => void loadSnapshot()}>다시 확인</button>}
          </section>
        ) : (
          <>
            {directive && (
              <section className={`action-directive ${directive.tone}`} id="today-action" aria-labelledby="today-action-title">
                <div className="directive-main">
                  <div className="directive-label"><span>오늘의 행동</span><strong>{directive.badge}</strong></div>
                  <h2 id="today-action-title">{directive.headline}</h2>
                  <p>{directive.summary}</p>
                </div>
                <ol className="directive-steps" aria-label="오늘의 실행 순서">
                  {directive.steps.map((step, index) => (
                    <li key={step}><span>{index + 1}</span><strong>{step}</strong></li>
                  ))}
                </ol>
                <div className="directive-allocation" aria-label="권장 자본 상태">
                  <div><span>투자 예정</span><strong>{percent((snapshot.portfolio?.invested_weight ?? 0) * 100)}</strong></div>
                  <div><span>현금 유지</span><strong>{percent((snapshot.portfolio?.cash_weight ?? 1) * 100)}</strong></div>
                  <div><span>손절 기준 총위험</span><strong>{percent(snapshot.portfolio?.capital_at_risk_pct)}</strong></div>
                </div>
              </section>
            )}

            <section className="run-context" aria-label="분석 실행 정보">
              <div><span>기준일</span><strong>{snapshot.as_of_date}</strong></div>
              <div><span>가격 검사</span><strong>{number(snapshot.coverage.price_screened)} / {number(snapshot.coverage.liquid_universe)}</strong></div>
              <div><span>심층 분석</span><strong>{number(snapshot.coverage.deep_analyzed)}종목</strong></div>
              <div><span>전략</span><strong>{strategyName(snapshot.strategy)}</strong></div>
            </section>

            <section className="summary-grid" aria-label="판단 요약">
              <article><span>신규 매수</span><strong className="positive">{counts.buy}</strong><small>정량 관문과 AI 통과</small></article>
              <article><span>관찰·보유</span><strong className="caution">{counts.watch}</strong><small>조건 변화 추적</small></article>
              <article><span>축소·제외</span><strong className="negative">{counts.avoid}</strong><small>신규 자본 미배치</small></article>
              <article><span>계획 투자 비중</span><strong>{percent((snapshot.portfolio?.invested_weight ?? 0) * 100)}</strong><small>현금 {percent((snapshot.portfolio?.cash_weight ?? 1) * 100)}</small></article>
            </section>

            <div className="content-grid" id="decision">
              <section className="panel decision-list">
                <div className="panel-head">
                  <div><p>PRIORITY ACTIONS</p><h2>종목별 최종 판단</h2></div>
                  <span className="verified"><i /> 저장된 실제 실행 결과</span>
                </div>
                {snapshot.decisions.map((item) => {
                  const short = item.forecast?.horizons?.["5"];
                  const medium = item.forecast?.horizons?.["20"];
                  const plan = item.trade_plan ?? {};
                  return (
                    <button
                      type="button"
                      className={`decision-row ${item.action.toLowerCase()} ${selected?.ticker === item.ticker ? "selected" : ""}`}
                      key={item.ticker}
                      onClick={() => setSelectedTicker(item.ticker)}
                    >
                      <div className="company">
                        <span className={`action ${item.action.toLowerCase()}`}>{actionNames[item.action] ?? item.action}</span>
                        <div><h3>{item.name}</h3><small>{item.ticker} · 팩터 {decimal(item.score)}</small></div>
                      </div>
                      <div className="decision-values">
                        <div><span>5일 예상</span><strong>{signedPercent(short?.expected_return_pct)}</strong></div>
                        <div><span>상승확률</span><strong>{percent(short?.up_probability_pct)}</strong></div>
                        <div><span>20일 예상</span><strong>{signedPercent(medium?.expected_return_pct)}</strong></div>
                        <div><span>AI 확신도</span><strong>{percent(item.confidence)}</strong></div>
                      </div>
                      <p>{String(item.ai_review?.thesis ?? "AI 근거가 제공되지 않았습니다.")}</p>
                      <div className="order-line">
                        <span>기준가 <b>{money(item.price?.current, snapshot.currency)}</b></span>
                        <span>손절 <b>{money(numberValue(item.risk?.stop_price), snapshot.currency)}</b></span>
                        <strong>{orderText(plan)}</strong>
                      </div>
                    </button>
                  );
                })}
              </section>

              <aside className="right-column">
                <section className="panel allocation-card">
                  <div className="panel-head compact"><div><p>RISK ALLOCATION</p><h2>자본 배분</h2></div></div>
                  <div className="allocation-total"><span>투자 예정</span><strong>{percent((snapshot.portfolio?.invested_weight ?? 0) * 100)}</strong></div>
                  <div className="allocation-bar"><i style={{ width: `${Math.min(100, (snapshot.portfolio?.invested_weight ?? 0) * 100)}%` }} /></div>
                  <div className="allocation-legend"><span><i className="invested" />투자</span><span><i className="cash" />현금 {percent((snapshot.portfolio?.cash_weight ?? 1) * 100)}</span></div>
                  <dl>
                    <div><dt>시장 국면</dt><dd>{regimeText(snapshot.portfolio?.regime, snapshot.portfolio?.regime_reason)}</dd></div>
                    <div><dt>손절 기준 총위험</dt><dd>{percent(snapshot.portfolio?.capital_at_risk_pct)}</dd></div>
                    <div><dt>오류 수</dt><dd>{snapshot.errors?.length ?? 0}건</dd></div>
                  </dl>
                </section>
                <section className="panel trust-card">
                  <p>DECISION CONTROL</p><h2>AI가 숫자를 만들지 않습니다</h2>
                  <ul>
                    <li><span>1</span>예상수익·확률은 정량 계산</li>
                    <li><span>2</span>손절·수량은 리스크 계산</li>
                    <li><span>3</span>AI는 허용된 행동만 선택</li>
                    <li><span>4</span>API 실패 시 판단 중단</li>
                  </ul>
                </section>
              </aside>
            </div>

            <section className="panel comparison" id="compare">
              <div className="panel-head"><div><p>CANDIDATE COMPARISON</p><h2>후보 비교</h2></div><span className="table-note">예상값은 수익을 보장하지 않습니다</span></div>
              <div className="table-wrap"><table><thead><tr><th>판단</th><th>종목</th><th>점수</th><th>5일 예상</th><th>상승확률</th><th>가격 기준일</th><th>데이터 완성도</th><th>주문</th></tr></thead><tbody>
                {snapshot.decisions.map((item) => {
                  const short = item.forecast?.horizons?.["5"];
                  return <tr key={item.ticker} onClick={() => setSelectedTicker(item.ticker)}><td><span className={`action ${item.action.toLowerCase()}`}>{actionNames[item.action] ?? item.action}</span></td><td><strong>{item.name}</strong><small>{item.ticker}</small></td><td>{decimal(item.score)}</td><td>{signedPercent(short?.expected_return_pct)}</td><td>{percent(short?.up_probability_pct)}</td><td>{item.price?.as_of ?? "-"}</td><td>{percent((item.data_completeness ?? 0) * 100)}</td><td><strong>{orderText(item.trade_plan ?? {})}</strong></td></tr>;
                })}
              </tbody></table></div>
            </section>

            {selected && <EvidencePanel decision={selected} marketScope={marketScope} />}

            <section className="method" id="method">
              <div><p className="eyebrow">HOW THE DECISION IS MADE</p><h2>판단이 만들어지는 순서</h2><p>각 단계의 데이터 상태가 기록되고 필수 관문을 통과한 경우에만 신규 매수가 가능합니다.</p></div>
              <div className="process-grid">
                <article><span>01</span><h3>최신 스냅샷 수집</h3><p>가격·거래량·재무·수급·뉴스·공시의 기준일과 출처를 저장합니다.</p></article>
                <article><span>02</span><h3>예측과 검증</h3><p>미래 누출을 차단한 워크포워드 결과와 거래비용을 계산합니다.</p></article>
                <article><span>03</span><h3>위험 산정</h3><p>ATR 손절, 비중·업종·총위험 한도로 주문 가능 수량을 정합니다.</p></article>
                <article><span>04</span><h3>Groq 최종 심사</h3><p>이미 계산된 근거와 반대 논리만 검토하고 숫자는 새로 만들지 않습니다.</p></article>
              </div>
            </section>
          </>
        )}

        <footer><div><strong>AI Fund Manager</strong><span>증거 기반 의사결정 지원</span></div><p>자동 주문 기능 없음 · 투자 권유 아님 · 실시간 호가 사용 안 함</p><span>© 2026</span></footer>
      </div>
    </main>
  );
}

function EvidencePanel({ decision, marketScope }: { decision: Decision; marketScope: MarketScope }) {
  const evidence = decision.evidence ?? {};
  const news = evidence.news ?? [];
  const disclosures = evidence.disclosures ?? [];
  return (
    <section className="lower-grid" id="evidence">
      <div className="panel source-panel">
        <div className="panel-head compact"><div><p>DATA PROVENANCE</p><h2>{decision.name} 데이터 출처</h2></div></div>
        <div className="source-table">
          <SourceRow label="가격·거래량" source={decision.price?.source ?? "-"} detail={decision.price?.as_of ?? "-"} ok={Boolean(decision.price?.current)} />
          <SourceRow label="재무" source={evidence.fundamental_source ?? (marketScope === "US" ? "SEC EDGAR companyfacts" : "NAVER/FINSTATE")} detail={evidence.fundamental_period ?? "기간 없음"} ok={evidence.fundamental_status === "ok"} />
          <SourceRow label={marketScope === "US" ? "거래량 수급 대용치" : "수급"} source={evidence.flow_source ?? "-"} detail={marketScope === "US" ? (evidence.flow_method ?? `${evidence.flow_observations ?? 0}거래일`) : `${evidence.flow_observations ?? 0}거래일`} ok={evidence.flow_status === "ok"} />
          <SourceRow label="뉴스" source={evidence.news_source ?? (marketScope === "US" ? "Google News RSS" : "NAVER 연결 언론사")} detail={marketScope === "US" ? `무료 헤드라인 ${news.length}건` : `본문 요약 ${evidence.news_detail_coverage?.covered ?? 0}/${evidence.news_detail_coverage?.attempted ?? 0}`} ok={evidence.news_status === "ok" || evidence.news_status === "partial"} />
          <SourceRow label="공시" source={evidence.disclosure_source ?? (marketScope === "US" ? "SEC EDGAR" : "OpenDART 또는 KOSCOM")} detail={`${disclosures.length}건`} ok={evidence.disclosure_status === "ok"} />
        </div>
      </div>
      <div className="panel audit-panel">
        <div className="panel-head compact"><div><p>AI REVIEW</p><h2>근거와 반대 논리</h2></div></div>
        <p><strong>판단 근거</strong><br />{String(decision.ai_review?.thesis ?? "-")}</p>
        <p><strong>반대 논리</strong><br />{String(decision.ai_review?.counter_thesis ?? "-")}</p>
        <p><strong>AI 분석원</strong><br />{String(decision.ai_review?.source ?? "-")}</p>
      </div>
      <div className="panel evidence-feed">
        <div className="panel-head compact"><div><p>NEWS & DISCLOSURES</p><h2>주가 영향 근거</h2></div></div>
        {news.length === 0 ? <p className="muted">수집된 뉴스가 없습니다.</p> : news.slice(0, 5).map((item, index) => (
          <a key={`${String(item.url)}-${index}`} href={String(item.url)} target="_blank" rel="noreferrer" className="evidence-item">
            <span>뉴스 · {String(item.publisher ?? "출처 확인")}</span>
            <strong>{String(item.title ?? "제목 없음")}</strong>
            {item.summary ? <small>{String(item.summary)}</small> : <small>기사 본문 요약 미수집</small>}
          </a>
        ))}
        {disclosures.slice(0, 3).map((item, index) => (
          <a key={`${String(item.url)}-${index}`} href={String(item.url)} target="_blank" rel="noreferrer" className="evidence-item disclosure">
            <span>공시 · {String(item.receipt_date ?? "날짜 없음")}</span>
            <strong>{String(item.report_name ?? "공시명 없음")}</strong>
          </a>
        ))}
      </div>
    </section>
  );
}

function SourceRow({ label, source, detail, ok }: { label: string; source: string; detail: string; ok: boolean }) {
  return <div><strong>{label}</strong><span>{source}</span><small>{detail}</small><em className={ok ? "ok" : "fallback"}>{ok ? "정상" : "제한"}</em></div>;
}

function number(value?: number) { return typeof value === "number" ? value.toLocaleString("ko-KR") : "-"; }
function decimal(value?: number) { return typeof value === "number" ? value.toFixed(2) : "-"; }
function percent(value?: number) { return typeof value === "number" ? `${value.toFixed(1)}%` : "-"; }
function signedPercent(value?: number) { return typeof value === "number" ? `${value >= 0 ? "+" : ""}${value.toFixed(2)}%` : "-"; }
function money(value?: number, currency: "KRW" | "USD" = "KRW") {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return currency === "USD"
    ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value)
    : `${Math.round(value).toLocaleString("ko-KR")}원`;
}
function numberValue(value: unknown) { return typeof value === "number" ? value : undefined; }
function strategyName(value: string) { return ({ balanced: "균형", rebound: "반등", breakout: "돌파" } as Record<string, string>)[value] ?? value; }
function analysisButtonText(status: AnalysisState["status"], requesting: boolean, cooldownSeconds: number) {
  if (requesting) return "분석 요청 보내는 중...";
  if (status === "queued") return "지금 최신 데이터 분석 중...";
  if (cooldownSeconds > 0) return `${formatCooldown(cooldownSeconds)} 후 다시 분석`;
  if (status === "failed") return "지금 다시 분석 재시도";
  return "지금 시간 기준으로 다시 분석";
}
function analysisStatusTitle(status: AnalysisState["status"]) {
  return ({ queued: "새 분석을 실행하고 있습니다", complete: "새 분석이 완료됐습니다", failed: "분석 실행을 완료하지 못했습니다", cooldown: "최신 분석 반영 완료", idle: "분석 대기" } as Record<AnalysisState["status"], string>)[status];
}
function formatCooldown(seconds: number) {
  const safe = Math.max(0, Math.ceil(seconds));
  const minutes = Math.floor(safe / 60);
  const remainder = safe % 60;
  return minutes > 0 ? `${minutes}분 ${remainder}초` : `${remainder}초`;
}
function buildActionDirective(snapshot: Snapshot): ActionDirective {
  const rows = snapshot.decisions ?? [];
  const exits = rows.filter((item) => ["SELL", "REDUCE"].includes(item.action));
  const buys = rows.filter((item) => item.action === "BUY");
  const holds = rows.filter((item) => item.action === "HOLD");
  const watches = rows.filter((item) => item.action === "WATCH");
  const cash = percent((snapshot.portfolio?.cash_weight ?? 1) * 100);

  if (exits.length > 0) {
    const names = decisionNames(exits);
    return {
      tone: "stop",
      badge: "매도·축소 우선",
      headline: `${names} 비중을 줄이거나 매도하세요`,
      summary: "신규 매수보다 기존 위험을 먼저 낮추라는 판단입니다. 주문 수량과 손절 기준을 종목 카드에서 확인하세요.",
      steps: [`${names} 주문 계획 확인`, "보유 수량과 손절가 대조", `남은 자금 ${cash} 현금 유지`],
    };
  }
  if (buys.length > 0) {
    const names = decisionNames(buys);
    return {
      tone: "go",
      badge: "매수 검토 가능",
      headline: `${names} 매수를 검토하세요`,
      summary: "정량 관문과 AI 심사를 모두 통과한 후보입니다. 표시된 주문 수량과 손절가를 지킬 수 있을 때만 실행하세요.",
      steps: [`${names} 주문 수량 확인`, "기준가와 현재가 비교", "손절가를 주문 전에 기록"],
    };
  }
  if (holds.length > 0) {
    const names = decisionNames(holds);
    return {
      tone: "wait",
      badge: "기존 보유 유지",
      headline: `${names}은 보유하되 신규 매수는 기다리세요`,
      summary: "현재 포지션은 유지할 수 있지만 추가 자본을 넣을 근거는 부족합니다. 손절 기준을 먼저 확인하세요.",
      steps: [`${names} 보유 수량 유지`, "손절가 이탈 여부 확인", `신규 자금 ${cash} 현금 유지`],
    };
  }
  if (watches.length > 0) {
    const names = decisionNames(watches);
    return {
      tone: "wait",
      badge: "관찰·대기",
      headline: "오늘은 신규 매수하지 말고 관찰하세요",
      summary: `${names}은 아직 매수 조건을 충족하지 못했습니다. 조건이 바뀔 때까지 주문하지 않고 현금을 유지합니다.`,
      steps: ["신규 매수 주문 보류", `${names} 조건 변화 관찰`, `가용 자금 ${cash} 현금 유지`],
    };
  }
  return {
    tone: "stop",
    badge: "매수 보류",
    headline: "오늘은 신규 매수하지 마세요",
    summary: "검증 관문을 통과한 종목이 없습니다. 임의로 종목을 고르지 말고 다음 분석까지 현금을 유지합니다.",
    steps: ["신규 주문 생성 금지", "매수 제외 사유 확인", `가용 자금 ${cash} 현금 유지`],
  };
}
function decisionNames(rows: Decision[]) {
  const names = rows.slice(0, 2).map((item) => item.name).join("·");
  return rows.length > 2 ? `${names} 외 ${rows.length - 2}종목` : names;
}
function regimeText(value?: MarketRegime, fallbackReason?: string) {
  const code = typeof value === "string" ? value : value?.regime;
  const reason = typeof value === "object" && value ? value.reason : fallbackReason;
  if (!code) return "확인 불가";
  const label = ({ bull: "강세", neutral: "중립", bear: "약세", unknown: "판단 보류" } as Record<string, string>)[code.toLowerCase()] ?? code;
  return reason ? `${label} · ${reason}` : label;
}
function formatDateTime(value: string) { try { return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(value)); } catch { return value; } }
function orderText(plan: Record<string, unknown>) { const side = String(plan.order_side ?? "NONE"); const qty = Number(plan.order_quantity ?? 0); return side === "BUY" && qty > 0 ? `${qty.toLocaleString("ko-KR")}주 매수` : side === "SELL" && qty > 0 ? `${qty.toLocaleString("ko-KR")}주 매도` : "주문 없음"; }

const rankings = [
  { rank: 1, ticker: "092730", name: "네오팜", market: "KOSDAQ", score: 77.89, decision: "WATCH" },
  { rank: 2, ticker: "000240", name: "한국앤컴퍼니", market: "KOSPI", score: 74.68, decision: "REJECT" },
  { rank: 3, ticker: "008490", name: "서흥", market: "KOSPI", score: 74.23, decision: "REJECT" },
  { rank: 4, ticker: "053800", name: "안랩", market: "KOSDAQ", score: 73.12, decision: "REJECT" },
  { rank: 5, ticker: "025560", name: "미래산업", market: "KOSPI", score: 72.88, decision: "WATCH" },
  { rank: 6, ticker: "052460", name: "아이크래프트", market: "KOSDAQ", score: 72.76, decision: "REJECT" },
  { rank: 7, ticker: "204620", name: "글로벌텍스프리", market: "KOSDAQ", score: 72.6, decision: "WATCH" },
  { rank: 8, ticker: "044820", name: "코스맥스비티아이", market: "KOSPI", score: 71.93, decision: "REJECT" },
  { rank: 9, ticker: "037460", name: "삼지전자", market: "KOSDAQ", score: 71.75, decision: "REJECT" },
  { rank: 10, ticker: "007340", name: "DN오토모티브", market: "KOSPI", score: 71.66, decision: "WATCH" },
];

const watchlist = [
  {
    ticker: "092730",
    name: "네오팜",
    score: "77.89",
    note: "팩터 우위는 확인됐지만 워크포워드 성과가 안정적이지 않아 관찰만 유지합니다.",
  },
  {
    ticker: "025560",
    name: "미래산업",
    score: "72.88",
    note: "밸류 지표는 낮지만 가격 상승 이후 변동성과 재현성을 추가 확인해야 합니다.",
  },
  {
    ticker: "204620",
    name: "글로벌텍스프리",
    score: "72.60",
    note: "모멘텀과 밸류의 균형은 양호하나 검증 표본이 투자 승인을 뒷받침하지 못했습니다.",
  },
  {
    ticker: "007340",
    name: "DN오토모티브",
    score: "71.66",
    note: "상승 추세는 유효하지만 워크포워드 승률과 손절 위험을 더 관찰합니다.",
  },
];

const engines = [
  ["01", "데이터 엔진", "가격·거래량·재무·수급·공시·뉴스를 날짜와 출처와 함께 저장"],
  ["02", "퀀트 엔진", "가치·모멘텀·수급·품질·변동성·뉴스를 계산해 전 종목 순위화"],
  ["03", "검증 엔진", "미래 데이터 누출을 차단하고 비용·슬리피지·벤치마크를 반영"],
  ["04", "리스크 엔진", "ATR 손절, 종목·업종 한도, 현금 비중과 최대 손실을 통제"],
  ["05", "AI 심사위원", "계산된 사실만 검토하고 근거가 부족하면 추천을 거부"],
  ["06", "사후평가 엔진", "추천과 실제 성과를 연결해 적중률과 실패 원인을 누적"],
];

export default function Home() {
  return (
    <main>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="Evidence First 홈">
          <span className="brand-mark">EF</span>
          <span>Evidence First</span>
        </a>
        <nav aria-label="주요 메뉴">
          <a href="#snapshot">스냅샷</a>
          <a href="#watchlist">관찰 종목</a>
          <a href="#ranking">팩터 순위</a>
          <a href="#method">방법론</a>
        </nav>
        <span className="as-of">DATA · 2026.08.13</span>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow"><span /> EVIDENCE-BOUND INVESTING</p>
          <h1>추천하지 않는 능력까지<br />설계했습니다.</h1>
          <p className="hero-intro">
            숫자는 퀀트 엔진이 계산하고 AI는 반대편에서 심사합니다.
            근거가 충분하지 않으면 가장 정확한 결정은 <strong>현금</strong>입니다.
          </p>
          <div className="hero-actions">
            <a className="button primary" href="#snapshot">검증 결과 보기</a>
            <a className="button ghost" href="https://github.com/asdf8421/toss" target="_blank" rel="noreferrer">소스 코드 ↗</a>
          </div>
        </div>
        <div className="decision-card" aria-label="최종 자산배분">
          <div className="decision-topline">
            <span>FINAL ALLOCATION</span>
            <span className="live-dot">VERIFIED</span>
          </div>
          <div className="allocation-ring">
            <div><strong>100%</strong><span>CASH</span></div>
          </div>
          <div className="decision-grid">
            <div><span>시장 국면</span><strong>NEUTRAL</strong></div>
            <div><span>투자 비중</span><strong>0.0%</strong></div>
            <div><span>손절 총위험</span><strong>0.00%</strong></div>
            <div><span>AI 승인</span><strong>0 / 10</strong></div>
          </div>
          <p className="decision-note">승인 종목이 없어 자본을 배치하지 않았습니다.</p>
        </div>
      </section>

      <section className="ticker-strip" aria-label="분석 요약">
        <div><span>KRX UNIVERSE</span><strong>2,713</strong></div>
        <div><span>LIQUID ELIGIBLE</span><strong>617</strong></div>
        <div><span>FULL ANALYSIS</span><strong>602</strong></div>
        <div><span>GROQ REVIEW</span><strong>10 / 10</strong></div>
        <div><span>BATCH ERRORS</span><strong>0</strong></div>
      </section>

      <section className="section snapshot" id="snapshot">
        <div className="section-heading">
          <div><p className="kicker">01 / MARKET SNAPSHOT</p><h2>전체시장 검증 결과</h2></div>
          <p>2,713개 상장종목을 출발점으로 유동성과 데이터 품질을 통과한 602개 종목을 동일한 규칙으로 검증했습니다.</p>
        </div>
        <div className="pipeline-card">
          <div className="pipeline-flow" aria-label="분석 종목 필터링 과정">
            <div><strong>2,713</strong><span>KRX 전체</span></div><i>→</i>
            <div><strong>617</strong><span>유동성 적격</span></div><i>→</i>
            <div><strong>602</strong><span>심층 분석</span></div><i>→</i>
            <div className="accent"><strong>10</strong><span>AI 최종 심사</span></div>
          </div>
          <div className="coverage-grid">
            <div><span>재무 데이터</span><strong>602 / 602</strong><em className="ok">COMPLETE</em></div>
            <div><span>수급 데이터</span><strong>602 / 602</strong><em className="warn">ESTIMATED</em></div>
            <div><span>뉴스 데이터</span><strong>602 / 602</strong><em className="ok">COMPLETE</em></div>
            <div><span>공시 데이터</span><strong>530 / 602</strong><em className="warn">72 PARTIAL</em></div>
            <div><span>워크포워드</span><strong>582 / 602</strong><em className="warn">20 INSUFFICIENT</em></div>
            <div><span>리스크 산정</span><strong>602 / 602</strong><em className="ok">COMPLETE</em></div>
          </div>
        </div>
      </section>

      <section className="section watch-section" id="watchlist">
        <div className="section-heading inverted">
          <div><p className="kicker">02 / AI RISK COMMITTEE</p><h2>매수가 아닌 관찰 목록</h2></div>
          <p>WATCH는 투자 허가가 아닙니다. 네 종목 모두 추가 검증 전까지 목표 비중 0%를 유지합니다.</p>
        </div>
        <div className="watch-grid">
          {watchlist.map((item, index) => (
            <article className="watch-card" key={item.ticker}>
              <div className="watch-card-top"><span>0{index + 1}</span><span className="badge watch">WATCH</span></div>
              <p className="ticker">{item.ticker}</p>
              <h3>{item.name}</h3>
              <div className="score-line"><span>QUANT SCORE</span><strong>{item.score}</strong></div>
              <p>{item.note}</p>
              <div className="zero-weight"><span>TARGET WEIGHT</span><strong>0.00%</strong></div>
            </article>
          ))}
        </div>
      </section>

      <section className="section" id="ranking">
        <div className="section-heading">
          <div><p className="kicker">03 / FACTOR RANKING</p><h2>상위 10개 심사 기록</h2></div>
          <p>높은 팩터 점수만으로 투자하지 않습니다. 백테스트와 리스크, AI 반대심사를 모두 통과해야 APPROVE가 됩니다.</p>
        </div>
        <div className="ranking-table" role="table" aria-label="팩터 상위 종목">
          <div className="ranking-row ranking-head" role="row">
            <span>순위</span><span>종목</span><span>시장</span><span>팩터 점수</span><span>AI 판정</span>
          </div>
          {rankings.map((item) => (
            <div className="ranking-row" role="row" key={item.ticker}>
              <span className="rank">{String(item.rank).padStart(2, "0")}</span>
              <span className="company"><strong>{item.name}</strong><small>{item.ticker}</small></span>
              <span>{item.market}</span>
              <span className="score-cell"><i style={{ width: `${item.score}%` }} /><strong>{item.score.toFixed(2)}</strong></span>
              <span><em className={`badge ${item.decision.toLowerCase()}`}>{item.decision}</em></span>
            </div>
          ))}
        </div>
      </section>

      <section className="section method" id="method">
        <div className="section-heading">
          <div><p className="kicker">04 / SYSTEM DESIGN</p><h2>숫자와 판단의 분리</h2></div>
          <p>AI는 종목을 발명하거나 수치를 계산하지 않습니다. 이미 측정된 증거를 비판적으로 읽고 승인·관찰·거부만 결정합니다.</p>
        </div>
        <div className="engine-grid">
          {engines.map(([num, title, copy]) => (
            <article key={num}><span>{num}</span><h3>{title}</h3><p>{copy}</p></article>
          ))}
        </div>
      </section>

      <section className="audit-band">
        <div><p className="kicker">AUDIT TRAIL</p><h2>모든 결론에는 출처와 거부 사유가 남습니다.</h2></div>
        <div className="audit-meta">
          <p><span>RUN ID</span><code>c95aedf589184079bd3f9e82edaf0a55</code></p>
          <p><span>STRATEGY</span><strong>BALANCED</strong></p>
          <p><span>AI SOURCE</span><strong>GROQ · 10/10</strong></p>
          <p><span>TRANSACTION COST</span><strong>25 BPS</strong></p>
        </div>
      </section>

      <section className="disclosure">
        <strong>읽기 전용 검증 스냅샷</strong>
        <p>2026년 8월 13일 저장 결과입니다. 실시간 시세가 아니며 투자 권유 또는 자동 주문 기능을 제공하지 않습니다. 수급은 네이버 순매수 수량×종가 추정치이고, 일부 공시·백테스트 데이터는 불충분 상태로 표시됩니다.</p>
      </section>

      <footer>
        <div className="brand"><span className="brand-mark">EF</span><span>Evidence First</span></div>
        <p>Measure first. Challenge second. Allocate last.</p>
        <span>© 2026 · RESEARCH SYSTEM</span>
      </footer>
    </main>
  );
}

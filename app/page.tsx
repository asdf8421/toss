const decisions = [
  {
    ticker: "066570",
    name: "LG전자",
    action: "BUY",
    score: 60.88,
    forecast5: "+8.52%",
    probability5: "76.0%",
    forecast20: "+20.04%",
    confidence: "78%",
    note: "정량 매수 관문을 모두 통과한 뒤 Groq가 BUY로 확정했습니다.",
    order: "24주 · 기준가 215,000원",
  },
  {
    ticker: "005935",
    name: "삼성전자우",
    action: "WATCH",
    score: 61.1,
    forecast5: "+0.05%",
    probability5: "52.9%",
    forecast20: "+7.03%",
    confidence: "68%",
    note: "중기 추정은 양수지만 단기 기대수익이 비용·안전마진 기준을 넘지 못했습니다.",
    order: "주문 없음",
  },
  {
    ticker: "009150",
    name: "삼성전기",
    action: "AVOID",
    score: 57.67,
    forecast5: "−5.52%",
    probability5: "47.9%",
    forecast20: "−6.20%",
    confidence: "78%",
    note: "5일·20일 기대수익이 모두 음수라 신규 매수를 회피했습니다.",
    order: "주문 없음",
  },
  {
    ticker: "017670",
    name: "SK텔레콤",
    action: "AVOID",
    score: 50.98,
    forecast5: "−2.80%",
    probability5: "44.1%",
    forecast20: "−5.43%",
    confidence: "78%",
    note: "단기·중기 추정과 팩터 검증이 신규 자본 배치 기준에 미달했습니다.",
    order: "주문 없음",
  },
];

const engines = [
  ["01", "데이터 엔진", "가격·거래량·재무·수급·공시·뉴스를 기준일과 출처까지 SQLite에 저장"],
  ["02", "퀀트 엔진", "가치·모멘텀·수급·품질·변동성·뉴스를 계산해 전 종목 순위화"],
  ["03", "예측·검증 엔진", "5·20일 수익률과 상승확률을 누출 없는 워크포워드 방식으로 추정"],
  ["04", "리스크 엔진", "ATR 손절, 종목·업종 한도, 보유 노출과 현금 비중을 함께 통제"],
  ["05", "Groq 분석가", "허용된 BUY/HOLD/REDUCE/SELL/WATCH/AVOID 중 증거에 맞는 행동을 선택"],
  ["06", "사후평가 엔진", "BUY/HOLD 판단을 실제 수익·비용·벤치마크와 연결해 실패 원인을 누적"],
];

export default function Home() {
  return (
    <main>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="AI Fund Manager 홈">
          <span className="brand-mark">FM</span><span>AI Fund Manager</span>
        </a>
        <nav aria-label="주요 메뉴">
          <a href="#snapshot">검증 실행</a><a href="#actions">행동 판단</a><a href="#ranking">예측표</a><a href="#method">설계</a>
        </nav>
        <span className="as-of">VERIFIED · 2026.08.18</span>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow"><span /> QUANT FORECAST × GROQ ANALYSIS</p>
          <h1>예측하고,<br />분석하고,<br />행동으로.</h1>
          <p className="hero-intro">
            퀀트가 5일·20일 기대수익과 상승확률을 계산하고, Groq가 재무·수급·뉴스·공시와 반대 논리를 함께 읽어 <strong>매수·보유·축소·매도</strong>를 결정합니다.
          </p>
          <div className="hero-actions">
            <a className="button primary" href="#actions">실제 검증 결과</a>
            <a className="button ghost" href="https://github.com/asdf8421/toss" target="_blank" rel="noreferrer">소스 코드 ↗</a>
          </div>
        </div>
        <div className="decision-card" aria-label="소규모 검증 실행 자산배분">
          <div className="decision-topline"><span>VALIDATED SAMPLE RUN</span><span className="live-dot">GROQ 4 / 4</span></div>
          <div className="allocation-ring" style={{ background: "conic-gradient(var(--signal) 0 5.16%, #313a34 5.16% 100%)" }}>
            <div><strong>5.2%</strong><span>INVESTED</span></div>
          </div>
          <div className="decision-grid">
            <div><span>매수</span><strong>1 종목</strong></div>
            <div><span>관찰</span><strong>1 종목</strong></div>
            <div><span>회피</span><strong>2 종목</strong></div>
            <div><span>현금</span><strong>94.8%</strong></div>
          </div>
          <p className="decision-note">10종목 검사 · 5종목 심층분석 · 4종목 Groq 최종 판단</p>
        </div>
      </section>

      <section className="ticker-strip" aria-label="검증 요약">
        <div><span>KRX UNIVERSE</span><strong>2,713</strong></div>
        <div><span>LIQUID ELIGIBLE</span><strong>803</strong></div>
        <div><span>DEEP ANALYSIS</span><strong>5</strong></div>
        <div><span>GROQ SOURCE</span><strong>4 / 4</strong></div>
        <div><span>UNIT TESTS</span><strong>10 / 10</strong></div>
      </section>

      <section className="section snapshot" id="snapshot">
        <div className="section-heading">
          <div><p className="kicker">01 / END-TO-END VERIFICATION</p><h2>말이 아니라 실제 실행</h2></div>
          <p>저장된 Groq 토큰으로 현재 권장 모델을 직접 호출하고, 시장 데이터 수집부터 예측·백테스트·행동 판단·수량 산정까지 한 번에 실행했습니다.</p>
        </div>
        <div className="pipeline-card">
          <div className="pipeline-flow" aria-label="분석 파이프라인">
            <div><strong>2,713</strong><span>KRX 전체</span></div><i>→</i>
            <div><strong>10</strong><span>가격 검사</span></div><i>→</i>
            <div><strong>5</strong><span>예측·검증</span></div><i>→</i>
            <div className="accent"><strong>4</strong><span>Groq 판단</span></div>
          </div>
          <div className="coverage-grid">
            <div><span>예측 지평</span><strong>5D / 20D</strong><em className="ok">OOS</em></div>
            <div><span>미래 누출 검사</span><strong>PASS</strong><em className="ok">STRICT</em></div>
            <div><span>실제 AI 원천</span><strong>GROQ</strong><em className="ok">4 / 4</em></div>
            <div><span>거래비용</span><strong>25 BPS</strong><em className="ok">APPLIED</em></div>
            <div><span>구조화 출력</span><strong>JSON SCHEMA</strong><em className="ok">STRICT</em></div>
            <div><span>AI 실패 정책</span><strong>NO ACTION</strong><em className="warn">FAIL CLOSED</em></div>
          </div>
        </div>
      </section>

      <section className="section watch-section" id="actions">
        <div className="section-heading inverted">
          <div><p className="kicker">02 / ACTION ENGINE</p><h2>실제로 나온 행동 판단</h2></div>
          <p>아래 값은 2026-08-18 소규모 검증 실행 결과입니다. 정적 검증 스냅샷이며 실시간 투자 권유가 아닙니다.</p>
        </div>
        <div className="watch-grid">
          {decisions.map((item, index) => (
            <article className="watch-card" key={item.ticker}>
              <div className="watch-card-top"><span>0{index + 1}</span><span className={`badge ${item.action.toLowerCase()}`}>{item.action}</span></div>
              <p className="ticker">{item.ticker}</p><h3>{item.name}</h3>
              <div className="score-line"><span>5D FORECAST / UP</span><strong>{item.forecast5} / {item.probability5}</strong></div>
              <p>{item.note}</p>
              <div className="zero-weight"><span>ORDER PLAN</span><strong>{item.order}</strong></div>
            </article>
          ))}
        </div>
      </section>

      <section className="section" id="ranking">
        <div className="section-heading">
          <div><p className="kicker">03 / FORECAST TABLE</p><h2>예측과 AI 결론을 한 줄에</h2></div>
          <p>예상수익만 보지 않습니다. 상승확률, 워크포워드 정확도, 비용차감 백테스트, 위험 한도를 통과해야 BUY가 AI 선택지에 들어갑니다.</p>
        </div>
        <div className="ranking-table" role="table" aria-label="예측과 행동 판단">
          <div className="ranking-row ranking-head" role="row"><span>순위</span><span>종목</span><span>행동</span><span>5일 / 상승확률</span><span>20일</span></div>
          {decisions.map((item, index) => (
            <div className="ranking-row" role="row" key={item.ticker}>
              <span className="rank">{String(index + 1).padStart(2, "0")}</span>
              <span className="company"><strong>{item.name}</strong><small>{item.ticker}</small></span>
              <span><em className={`badge ${item.action.toLowerCase()}`}>{item.action}</em></span>
              <span className="score-cell"><i style={{ width: `${Math.max(4, Number(item.probability5.replace("%", "")))}%` }} /><strong>{item.forecast5} / {item.probability5}</strong></span>
              <span><strong>{item.forecast20}</strong></span>
            </div>
          ))}
        </div>
      </section>

      <section className="section method" id="method">
        <div className="section-heading">
          <div><p className="kicker">04 / SYSTEM DESIGN</p><h2>숫자, 판단, 행동의 분리</h2></div>
          <p>AI는 가격과 수량을 발명하지 않습니다. 정량 엔진이 행동 경계를 만들고 Groq는 허용된 선택지 안에서 근거와 반대 논리를 종합합니다.</p>
        </div>
        <div className="engine-grid">
          {engines.map(([num, title, copy]) => <article key={num}><span>{num}</span><h3>{title}</h3><p>{copy}</p></article>)}
        </div>
      </section>

      <section className="audit-band">
        <div><p className="kicker">AUDIT TRAIL</p><h2>API가 실패하면 판단도 멈춥니다.</h2></div>
        <div className="audit-meta">
          <p><span>RUN ID</span><code>ffc9dd1ad3264a0dbfecf872e4fafa49</code></p>
          <p><span>AI MODEL</span><strong>openai/gpt-oss-120b</strong></p>
          <p><span>AI SOURCE</span><strong>GROQ · 4/4</strong></p>
          <p><span>BUY CONTROL</span><strong>QUANT GATE → GROQ</strong></p>
        </div>
      </section>

      <section className="disclosure">
        <strong>읽기 전용 검증 스냅샷</strong>
        <p>이 페이지는 기능과 소규모 실행 결과를 보여주는 정적 사이트입니다. 실제 대시보드는 로컬 Streamlit 앱에서 보유 종목과 운용자금을 입력해 실행합니다. 예측은 확률적 추정이며 수익을 보장하지 않고 주문은 자동 전송되지 않습니다.</p>
      </section>
      <footer><div className="brand"><span className="brand-mark">FM</span><span>AI Fund Manager</span></div><p>Forecast. Challenge. Act.</p><span>© 2026 · RESEARCH SYSTEM</span></footer>
    </main>
  );
}

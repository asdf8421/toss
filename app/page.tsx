const decisions = [
  { ticker: "066570", name: "LG전자", action: "BUY", actionKo: "매수", score: 60.88, f5: "+8.52%", up: "76.0%", f20: "+20.04%", confidence: "78%", price: "215,000원", stop: "184,451원", order: "24주 매수", reason: "예측·백테스트·데이터 완성도·리스크 관문을 모두 통과했습니다." },
  { ticker: "005935", name: "삼성전자우", action: "WATCH", actionKo: "관찰", score: 61.10, f5: "+0.05%", up: "52.9%", f20: "+7.03%", confidence: "68%", price: "209,200원", stop: "167,354원", order: "주문 없음", reason: "중기 추정은 양수지만 단기 기대수익이 비용과 안전마진을 넘지 못했습니다." },
  { ticker: "009150", name: "삼성전기", action: "AVOID", actionKo: "매수 제외", score: 57.67, f5: "−5.52%", up: "47.9%", f20: "−6.20%", confidence: "78%", price: "1,610,000원", stop: "1,239,666원", order: "주문 없음", reason: "5일·20일 기대수익이 모두 음수라 신규 자본을 배치하지 않습니다." },
  { ticker: "017670", name: "SK텔레콤", action: "AVOID", actionKo: "매수 제외", score: 50.98, f5: "−2.80%", up: "44.1%", f20: "−5.43%", confidence: "78%", price: "103,700원", stop: "86,666원", order: "주문 없음", reason: "단기·중기 예측과 팩터 검증이 신규 매수 기준에 미달했습니다." },
];

const sourceRows = [
  ["가격·거래량", "FinanceDataReader", "기준일 저장", "정상"],
  ["재무", "네이버 금융", "최근 완료 회계기간", "정상"],
  ["투자자 수급", "네이버 추정", "순매수 수량 × 종가", "대체"],
  ["기업 공시", "KOSCOM", "OpenDART 미연결", "대체"],
  ["AI 분석", "Groq", "openai/gpt-oss-120b", "정상"],
];

const process = [
  ["01", "데이터 수집", "가격·재무·수급·뉴스·공시의 기준일과 출처 저장"],
  ["02", "예측·검증", "5일·20일 추정과 누출 없는 워크포워드 성과 계산"],
  ["03", "리스크 산정", "ATR 손절, 종목·업종 한도와 주문 가능 수량 계산"],
  ["04", "AI 최종 판단", "허용된 행동 안에서 근거와 반대 논리를 종합"],
];

export default function Home() {
  return (
    <main className="app-shell">
      <aside className="side-nav">
        <a className="brand" href="#top" aria-label="AI Fund Manager 홈"><span className="brand-symbol">FM</span><span><strong>AI Fund Manager</strong><small>Decision Support</small></span></a>
        <nav aria-label="대시보드 메뉴">
          <a className="active" href="#decision"><span>01</span> 투자 판단</a>
          <a href="#compare"><span>02</span> 후보 비교</a>
          <a href="#evidence"><span>03</span> 데이터 출처</a>
          <a href="#method"><span>04</span> 검증 기준</a>
        </nav>
        <div className="side-status"><span className="status-dot" /><div><strong>분석 시스템 정상</strong><small>Groq 4 / 4 응답</small></div></div>
        <a className="repo-link" href="https://github.com/asdf8421/toss" target="_blank" rel="noreferrer">GitHub 소스 보기 <span>↗</span></a>
      </aside>

      <div className="workspace" id="top">
        <header className="topbar">
          <div><p className="eyebrow">DAILY DECISION REPORT</p><h1>오늘의 투자 판단</h1><p className="subtitle">예측 수치, 주문 계획, 반대 논리와 데이터 출처를 함께 확인합니다.</p></div>
          <div className="report-meta"><span>기준일</span><strong>2026.08.18</strong><small>읽기 전용 검증 스냅샷</small></div>
        </header>

        <section className="run-context" aria-label="분석 실행 정보">
          <div><span>실행 범위</span><strong>가격 10 · 심층 5 · AI 4</strong></div>
          <div><span>전략</span><strong>균형형 멀티팩터</strong></div>
          <div><span>AI 원천</span><strong>Groq · 실제 호출</strong></div>
          <div><span>거래 비용</span><strong>왕복 25bp 반영</strong></div>
        </section>

        <section className="summary-grid" aria-label="판단 요약">
          <article><span>신규 매수</span><strong className="positive">1</strong><small>정량 관문 + AI 통과</small></article>
          <article><span>관찰</span><strong className="caution">1</strong><small>주문 없이 조건 확인</small></article>
          <article><span>매수 제외</span><strong className="negative">2</strong><small>예측·검증 기준 미달</small></article>
          <article><span>계획 투자 비중</span><strong>5.16%</strong><small>현금 94.84%</small></article>
        </section>

        <div className="content-grid" id="decision">
          <section className="panel decision-list">
            <div className="panel-head"><div><p>PRIORITY ACTIONS</p><h2>종목별 최종 판단</h2></div><span className="verified"><i /> AI 응답 검증됨</span></div>
            {decisions.map((item) => (
              <article className={`decision-row ${item.action.toLowerCase()}`} key={item.ticker}>
                <div className="company"><span className={`action ${item.action.toLowerCase()}`}>{item.actionKo}</span><div><h3>{item.name}</h3><small>{item.ticker} · 팩터 {item.score.toFixed(2)}</small></div></div>
                <div className="decision-values"><div><span>5일 예상</span><strong>{item.f5}</strong></div><div><span>상승확률</span><strong>{item.up}</strong></div><div><span>20일 예상</span><strong>{item.f20}</strong></div><div><span>AI 확신도</span><strong>{item.confidence}</strong></div></div>
                <p>{item.reason}</p>
                <div className="order-line"><span>기준가 <b>{item.price}</b></span><span>손절 <b>{item.stop}</b></span><strong>{item.order}</strong></div>
              </article>
            ))}
          </section>

          <aside className="right-column">
            <section className="panel allocation-card">
              <div className="panel-head compact"><div><p>RISK ALLOCATION</p><h2>자본 배분</h2></div></div>
              <div className="allocation-total"><span>투자 예정</span><strong>5.16%</strong></div>
              <div className="allocation-bar"><i /></div>
              <div className="allocation-legend"><span><i className="invested" />투자 5.16%</span><span><i className="cash" />현금 94.84%</span></div>
              <dl><div><dt>신규 주문금액</dt><dd>5,160,000원</dd></div><div><dt>손절 기준 총위험</dt><dd>0.73%</dd></div><div><dt>종목당 최대 비중</dt><dd>15.00%</dd></div><div><dt>시장 국면</dt><dd>시스템 산정</dd></div></dl>
            </section>
            <section className="panel trust-card">
              <p>DECISION CONTROL</p><h2>AI가 숫자를 만들지 않습니다</h2>
              <ul><li><span>1</span>예상수익·확률은 퀀트 계산</li><li><span>2</span>손절·수량은 리스크 계산</li><li><span>3</span>AI는 허용 행동만 선택</li><li><span>4</span>API 실패 시 판단 중단</li></ul>
            </section>
          </aside>
        </div>

        <section className="panel comparison" id="compare">
          <div className="panel-head"><div><p>CANDIDATE COMPARISON</p><h2>후보 비교</h2></div><span className="table-note">예측값은 수익을 보장하지 않습니다</span></div>
          <div className="table-wrap"><table><thead><tr><th>최종 판단</th><th>종목</th><th>종합점수</th><th>5일 예상</th><th>상승확률</th><th>20일 예상</th><th>기준가</th><th>주문</th></tr></thead><tbody>
            {decisions.map(item => <tr key={item.ticker}><td><span className={`action ${item.action.toLowerCase()}`}>{item.actionKo}</span></td><td><strong>{item.name}</strong><small>{item.ticker}</small></td><td>{item.score.toFixed(2)}</td><td className={item.f5.includes("−") ? "down" : "up"}>{item.f5}</td><td>{item.up}</td><td className={item.f20.includes("−") ? "down" : "up"}>{item.f20}</td><td>{item.price}</td><td><strong>{item.order}</strong></td></tr>)}
          </tbody></table></div>
        </section>

        <section className="lower-grid" id="evidence">
          <div className="panel source-panel"><div className="panel-head compact"><div><p>DATA PROVENANCE</p><h2>데이터 출처</h2></div></div><div className="source-table">
            {sourceRows.map(([data, source, method, status]) => <div key={data}><strong>{data}</strong><span>{source}</span><small>{method}</small><em className={status === "정상" ? "ok" : "fallback"}>{status}</em></div>)}
          </div></div>
          <div className="panel audit-panel"><div className="panel-head compact"><div><p>AUDIT TRAIL</p><h2>실행 검증</h2></div></div><dl><div><dt>실행번호</dt><dd>ffc9dd1ad3</dd></div><div><dt>전체 KRX</dt><dd>2,713 종목</dd></div><div><dt>유동성 적격</dt><dd>803 종목</dd></div><div><dt>Python 테스트</dt><dd>10 / 10 통과</dd></div><div><dt>AI 구조화 출력</dt><dd>Strict JSON Schema</dd></div></dl></div>
        </section>

        <section className="method" id="method"><div><p className="eyebrow">HOW THE DECISION IS MADE</p><h2>판단이 만들어지는 순서</h2><p>모든 단계가 통과된 뒤에만 신규 매수가 가능합니다.</p></div><div className="process-grid">{process.map(([num,title,copy]) => <article key={num}><span>{num}</span><h3>{title}</h3><p>{copy}</p></article>)}</div></section>

        <footer><div><strong>AI Fund Manager</strong><span>연구·의사결정 지원 시스템</span></div><p>자동 주문 기능 없음 · 투자 권유 아님 · 실제 투자 전 원문 데이터와 공시 확인 필요</p><span>© 2026</span></footer>
      </div>
    </main>
  );
}

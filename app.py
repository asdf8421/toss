from __future__ import annotations

from dataclasses import replace

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import AppConfig
from performance_engine import PerformanceEngine
from pipeline import FundManagerPipeline


st.set_page_config(page_title="Evidence-First AI Fund Manager", layout="wide")


STRATEGIES = {
    "balanced": "균형형 멀티팩터",
    "rebound": "과매도 반등",
    "breakout": "거래량 돌파",
}


def main() -> None:
    st.title("Evidence-First AI Fund Manager")
    st.caption("숫자는 퀀트 엔진이 계산하고, AI는 근거를 심사합니다. 데이터가 부족하면 추천하지 않습니다.")

    base_config = AppConfig()
    with st.sidebar:
        st.header("분석 정책")
        strategy = st.selectbox(
            "전략",
            list(STRATEGIES),
            format_func=lambda key: STRATEGIES[key],
        )
        universe_limit = int(
            st.number_input(
                "가격 심층검사 종목 수",
                min_value=20,
                max_value=2800,
                value=80,
                step=20,
                help="KRX 전체 종목에 유동성 필터를 적용한 뒤 검사할 수입니다. 2800은 사실상 전체 검사이며 오래 걸립니다.",
            )
        )
        deep_limit = int(
            st.number_input(
                "재무·뉴스 심층분석 수",
                min_value=5,
                max_value=2800,
                value=min(20, universe_limit),
                step=5,
                help=(
                    "전체 팩터 순위가 필요하면 가격 심층검사 수와 동일하게 설정하세요. "
                    "종목마다 재무·뉴스 요청이 발생하므로 최초 전체 실행은 매우 오래 걸릴 수 있습니다."
                ),
            )
        )
        deep_limit = min(deep_limit, universe_limit)
        max_positions = int(st.slider("최대 보유 종목", 1, 10, 5))
        full_market = st.checkbox(
            "유동성 적격 전체시장 배치",
            value=False,
            help="오늘 기준 유동성 적격 종목 전체에 가격·재무·수급·뉴스·공시·워크포워드를 적용합니다.",
        )
        if full_market:
            st.warning(
                "전체 배치는 첫 실행에 오래 걸립니다. 브라우저를 닫을 가능성이 있다면 "
                "터미널에서 batch_runner.py를 실행하는 편이 안전합니다."
            )
        account_equity = float(
            st.number_input(
                "운용자금(원)",
                min_value=1_000_000,
                value=int(base_config.account_equity),
                step=10_000_000,
            )
        )

        st.divider()
        st.subheader("연결 상태")
        st.write(f"Groq 심사: {'연결됨' if base_config.groq_api_key else '규칙 심사로 대체'}")
        st.write(f"수급: {'KRX 공식값' if base_config.krx_ready else '네이버 순매매량 추정 대체'}")
        st.write(f"공시: {'OpenDART 공식값' if base_config.dart_api_key else 'KOSCOM 공시목록 대체'}")
        st.caption("키 값은 화면과 로그에 표시하지 않습니다.")

        run_clicked = st.button("전체 파이프라인 실행", type="primary", use_container_width=True)
        evaluate_clicked = st.button("지난 추천 사후평가", use_container_width=True)

    config = replace(base_config, account_equity=account_equity)

    if run_clicked:
        pipeline = FundManagerPipeline(config)
        progress_bar = st.progress(0.0)
        status_box = st.empty()
        stage_ranges = {
            "universe": (0.00, 0.08),
            "prices": (0.08, 0.46),
            "enrich": (0.46, 0.70),
            "validate": (0.70, 0.88),
            "judge": (0.88, 1.00),
        }

        def update_progress(stage: str, current: int, total: int, message: str) -> None:
            start, end = stage_ranges.get(stage, (0.0, 1.0))
            fraction = current / total if total else 1.0
            progress_bar.progress(min(1.0, start + (end - start) * fraction))
            status_box.info(message)

        try:
            result = pipeline.run(
                strategy=strategy,
                universe_limit=0 if full_market else universe_limit,
                deep_analysis_limit=0 if full_market else deep_limit,
                max_positions=max_positions,
                progress=update_progress,
            )
            st.session_state["fund_manager_result"] = result
            progress_bar.progress(1.0)
            status_box.success(f"분석 완료 · 실행 ID {result['run_id'][:10]}")
        except Exception as exc:
            status_box.error(f"파이프라인 중단: {type(exc).__name__}: {exc}")

    if evaluate_clicked:
        pipeline = FundManagerPipeline(config)
        engine = PerformanceEngine(config, pipeline.storage, pipeline.data)
        with st.spinner("만기가 지난 추천을 실제 가격과 비교합니다."):
            evaluations = engine.evaluate_due()
        if evaluations:
            st.success(f"{len(evaluations)}개 추천을 사후평가했습니다.")
        else:
            st.info("아직 평가 기한이 지난 추천이 없거나 가격 데이터가 부족합니다.")

    result = st.session_state.get("fund_manager_result")
    tab_portfolio, tab_ranking, tab_detail, tab_history, tab_policy = st.tabs(
        ["포트폴리오", "팩터 순위", "근거 감사", "사후평가", "방법론"]
    )

    with tab_portfolio:
        if not result:
            st.info("사이드바에서 파이프라인을 실행하면 위험 한도가 적용된 포트폴리오가 표시됩니다.")
        else:
            render_portfolio(result, config)

    with tab_ranking:
        if result:
            render_ranking(result)
        else:
            st.info("아직 실행 결과가 없습니다.")
        render_saved_batch(config)

    with tab_detail:
        if result and result["ranked"]:
            render_candidate_detail(result)
        else:
            st.info("심사된 후보가 없습니다.")

    with tab_history:
        pipeline = FundManagerPipeline(config)
        history = pipeline.storage.history()
        render_history(history)

    with tab_policy:
        render_methodology(config)

    st.divider()
    st.caption(
        "이 프로그램은 연구·의사결정 지원 도구이며 수익을 보장하지 않습니다. "
        "주문을 자동 전송하지 않으며 실제 투자 전 데이터 원문과 공시를 확인해야 합니다."
    )


def render_portfolio(result: dict, config: AppConfig) -> None:
    portfolio = result["portfolio"]
    regime = portfolio["regime"]
    a, b, c, d = st.columns(4)
    a.metric("시장 국면", regime["regime"].upper())
    b.metric("투자 비중", f"{portfolio['invested_weight'] * 100:.1f}%")
    c.metric("현금 비중", f"{portfolio['cash_weight'] * 100:.1f}%")
    d.metric("손절 기준 총위험", f"{portfolio['portfolio_stop_risk_pct']:.2f}%")
    st.caption(f"시장국면 근거: {regime['reason']}")

    coverage_rows = []
    status = result.get("data_status", {})
    labels = {
        "universe_scope": "유동성 적격 시장 검사",
        "fundamentals": "재무",
        "investor_flow": "수급",
        "news": "뉴스",
        "disclosures": "공시",
    }
    for key, label in labels.items():
        item = status.get(key, {})
        covered, total = item.get("covered", 0), item.get("total", 0)
        coverage_rows.append(
            {
                "데이터": label,
                "커버리지": f"{covered:,}/{total:,}",
                "상태": item.get("status") or ("완료" if total and covered == total else "부분"),
                "공급원": item.get("primary", ""),
            }
        )
    st.dataframe(pd.DataFrame(coverage_rows), width="stretch", hide_index=True)
    ai_status = status.get("ai_review", {})
    st.caption(f"AI 심사 실행 경로: {ai_status.get('sources', {})}")

    positions = pd.DataFrame(portfolio["positions"])
    if positions.empty:
        st.warning(
            "AI가 APPROVE한 종목이 없어 현금 100%로 결정했습니다. "
            "WATCH 종목은 관찰목록이며 자본을 배정하지 않습니다."
        )
    else:
        display = positions.rename(
            columns={
                "ticker": "종목코드",
                "name": "종목명",
                "sector": "업종",
                "total_score": "종합점수",
                "entry_price": "기준가",
                "stop_price": "손절가",
                "quantity": "수량",
                "target_weight": "비중",
                "capital_at_risk_pct": "손절위험(%)",
            }
        )
        display["비중"] = display["비중"].map(lambda value: f"{value * 100:.2f}%")
        st.dataframe(display, width="stretch", hide_index=True)
        st.caption(f"운용자금 {config.account_equity:,.0f}원 기준이며 실제 주문은 생성하지 않습니다.")

    if result["errors"]:
        with st.expander(f"수집 오류 {len(result['errors'])}건"):
            st.code("\n".join(result["errors"][:100]))


def render_ranking(result: dict) -> None:
    rows = []
    for rank, item in enumerate(result["ranked"], start=1):
        review = item.get("ai_review", {})
        backtest = item.get("backtest", {})
        rows.append(
            {
                "순위": rank,
                "종목코드": item["ticker"],
                "종목명": item["name"],
                "시장": item["market"],
                "업종": item["sector"],
                "종합": item["total_score"],
                "가치": item["value_score"],
                "모멘텀": item["momentum_score"],
                "수급": item["flow_score"],
                "품질": item["quality_score"],
                "저변동성": item["volatility_score"],
                "뉴스": item["news_score"],
                "데이터완성도": f"{item['data_completeness'] * 100:.0f}%",
                "독립표본": backtest.get("sample_count"),
                "평균순수익(%)": backtest.get("average_net_return"),
                "평균초과수익(%)": backtest.get("average_excess_return"),
                "심사": review.get("decision", "미심사"),
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption(
        f"KRX {result['universe_count']:,}개 → 유동성 적격 {result.get('liquid_universe_count', 0):,}개 "
        f"→ 이번 가격검사 {result['filtered_universe_count']:,}개 "
        f"→ 심층 데이터 {result['deep_analysis_count']:,}개. 결측 팩터는 0으로 위장하지 않습니다."
    )


def render_candidate_detail(result: dict) -> None:
    options = {f"{item['name']} ({item['ticker']})": item for item in result["ranked"]}
    selected = st.selectbox("감사할 후보", list(options))
    candidate = options[selected]
    review = candidate.get("ai_review", {})
    backtest = candidate.get("backtest", {})
    risk = candidate.get("risk", {})
    facts = candidate.get("facts", {})

    a, b, c, d = st.columns(4)
    a.metric("종합점수", f"{candidate['total_score']:.1f}")
    b.metric("AI 결정", review.get("decision", "미심사"))
    c.metric("독립 표본", backtest.get("sample_count", 0))
    d.metric("손절 거리", f"{risk.get('stop_distance_pct', 0):.2f}%")

    factor_names = ["가치", "모멘텀", "수급", "품질", "저변동성", "뉴스"]
    factor_values = [
        candidate.get("value_score"), candidate.get("momentum_score"),
        candidate.get("flow_score"), candidate.get("quality_score"),
        candidate.get("volatility_score"), candidate.get("news_score"),
    ]
    fig = go.Figure(
        go.Bar(
            x=factor_names,
            y=[value if value is not None else 0 for value in factor_values],
            marker_color=["#2563eb" if value is not None else "#d1d5db" for value in factor_values],
            text=[f"{value:.1f}" if value is not None else "결측" for value in factor_values],
            textposition="auto",
        )
    )
    fig.update_layout(height=300, yaxis_range=[0, 100], margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig, width="stretch")

    left, right = st.columns(2)
    with left:
        st.subheader("AI 위험심사")
        st.write(review.get("thesis", ""))
        st.warning(review.get("counter_thesis", ""))
        if review.get("data_gaps"):
            st.write("데이터 한계")
            st.write(review["data_gaps"])
        st.caption(f"심사 방식: {review.get('source', '미상')} · 신뢰도는 수익확률이 아님")
    with right:
        st.subheader("위험 산정")
        st.json(risk, expanded=True)

    st.subheader("워크포워드 검증")
    metrics = {
        key: backtest.get(key)
        for key in [
            "status", "sample_count", "win_rate", "average_net_return",
            "average_excess_return", "profit_factor", "worst_trade",
            "stop_hit_rate", "positive_fold_ratio", "cost_bps",
        ]
    }
    st.json(metrics, expanded=True)
    if backtest.get("folds"):
        st.dataframe(pd.DataFrame(backtest["folds"]), width="stretch", hide_index=True)
    st.caption(backtest.get("limitations", ""))

    st.subheader("측정 사실과 출처")
    scalar_facts = {key: value for key, value in facts.items() if key not in {"news", "disclosures"}}
    st.json(scalar_facts, expanded=False)
    for article in facts.get("news", []):
        st.markdown(
            f"- [{article['title']}]({article['url']}) · {article['published_date']} · "
            f"규칙 감성 {article['sentiment']:+.2f}"
        )
    for disclosure in facts.get("disclosures", []):
        st.markdown(
            f"- [공시: {disclosure['report_name']}]({disclosure['url']}) · {disclosure['receipt_date']}"
        )


def render_saved_batch(config: AppConfig) -> None:
    pipeline = FundManagerPipeline(config)
    job = pipeline.storage.latest_batch_job(full_only=True)
    st.divider()
    st.subheader("저장된 전체시장 일일 배치")
    if not job:
        st.info("아직 전체시장 배치 기록이 없습니다. batch_runner.py 실행 후 여기에 표시됩니다.")
        return
    st.write(
        f"작업 `{job['job_id']}` · 상태 **{job['status']}** · 단계 `{job['stage']}` · "
        f"{job['current_count']:,}/{job['total_count']:,}"
    )
    st.caption(job.get("message") or "")
    if not job.get("result_run_id"):
        return
    ranking = pipeline.storage.factor_ranking(job["result_run_id"])
    if ranking.empty:
        st.warning("배치 완료 기록은 있지만 팩터 순위 데이터가 없습니다.")
        return
    columns = {
        "ticker": "종목코드",
        "name": "종목명",
        "market": "시장",
        "sector": "업종",
        "total_score": "종합",
        "value_score": "가치",
        "momentum_score": "모멘텀",
        "flow_score": "수급",
        "quality_score": "품질",
        "volatility_score": "저변동성",
        "news_score": "뉴스",
        "data_completeness": "데이터완성도",
        "sample_count": "독립표본",
        "average_net_return": "평균순수익(%)",
        "average_excess_return": "평균초과수익(%)",
        "risk_status": "위험검증",
    }
    display = ranking[[key for key in columns if key in ranking]].rename(columns=columns)
    st.dataframe(display, width="stretch", hide_index=True)
    st.caption(f"저장된 전체 팩터 순위 {len(display):,}개 · run_id {job['result_run_id']}")


def render_history(history: pd.DataFrame) -> None:
    if history.empty:
        st.info("저장된 추천 및 사후평가가 없습니다.")
        return
    display = history.copy()
    for column in ["net_return", "benchmark_return", "excess_return"]:
        if column in display:
            display[column] = pd.to_numeric(display[column], errors="coerce") * 100
    columns = [
        "as_of_date", "ticker", "name", "strategy", "total_score", "ai_decision",
        "target_weight", "evaluation_date", "net_return", "benchmark_return",
        "excess_return", "outcome", "failure_reason",
    ]
    st.dataframe(display[[column for column in columns if column in display]], width="stretch", hide_index=True)
    evaluated = display[display["outcome"].notna()] if "outcome" in display else pd.DataFrame()
    if not evaluated.empty:
        a, b, c = st.columns(3)
        a.metric("평가 완료", len(evaluated))
        b.metric("성공률", f"{(evaluated['outcome'] == 'SUCCESS').mean() * 100:.1f}%")
        c.metric("평균 초과수익", f"{evaluated['excess_return'].mean():.2f}%")


def render_methodology(config: AppConfig) -> None:
    st.markdown(
        f"""
### 계산 순서

1. KRX 전체 {STRATEGIES.get('balanced')} 대상에서 거래정지·저유동성·저시가총액 종목을 제거합니다.
2. 가격 데이터만으로 1차 기술 순위를 만들고 상위 후보에 재무·수급·뉴스·공시를 결합합니다.
3. 사용 가능한 팩터만 재가중하되 데이터 완성도 패널티를 적용합니다.
4. 신호일 종가까지의 정보만 사용하고 다음 거래일 진입으로 워크포워드 검증합니다.
5. 왕복 비용 {config.commission_bps + config.slippage_bps:.0f}bp와 ATR 손절을 반영합니다.
6. 종목당 위험 {config.risk_per_trade * 100:.2f}%, 최대 비중 {config.max_position_pct * 100:.0f}%,
   업종 최대 {config.max_sector_pct * 100:.0f}%, 포트폴리오 손절 위험 {config.max_portfolio_risk * 100:.0f}%를 넘지 않습니다.
7. AI는 계산된 값만 심사하며 필수 데이터나 독립 표본이 부족하면 LLM 호출 전에 거부합니다.
8. 추천 후 {config.holding_days}거래일이 지나면 실제 수익·벤치마크·손절 여부를 저장합니다.

### 의도적인 제한

- 현재 네이버 재무 스냅샷의 미래 추정 연도는 사용하지 않습니다.
- 과거 시점 재무·수급·뉴스 데이터가 없으므로 백테스트에는 가격으로 재현 가능한 신호만 사용합니다.
- 수급이나 공시 API가 연결되지 않으면 0점이 아니라 결측으로 기록합니다.
- 뉴스 점수는 제목의 공개된 긍·부정 단어 규칙이며, AI가 임의의 수치를 만들지 않습니다.
"""
    )


if __name__ == "__main__":
    main()

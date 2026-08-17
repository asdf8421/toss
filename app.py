from __future__ import annotations

from dataclasses import replace

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ai_judge import AIUnavailableError
from config import AppConfig
from performance_engine import PerformanceEngine
from pipeline import FundManagerPipeline
from portfolio_input import parse_holdings


st.set_page_config(page_title="AI Fund Manager", page_icon="📈", layout="wide")

STRATEGIES = {
    "balanced": "균형형 멀티팩터",
    "rebound": "과매도 반등",
    "breakout": "거래량 돌파",
}
ACTION_KO = {
    "BUY": "매수",
    "HOLD": "보유",
    "REDUCE": "축소",
    "SELL": "매도",
    "WATCH": "관찰",
    "AVOID": "회피",
    "NO_ACTION": "판단 없음",
}


def main() -> None:
    st.title("AI Fund Manager")
    st.caption("워크포워드 수익률 예측 → 퀀트 행동 기준 → Groq 근거 분석 → 위험 한도와 주문 계획")

    base_config = AppConfig()
    with st.sidebar:
        st.header("분석 설정")
        strategy = st.selectbox("전략", list(STRATEGIES), format_func=lambda key: STRATEGIES[key])
        universe_limit = int(st.number_input("1차 가격 검사 종목 수", 20, 2800, 80, 20))
        deep_limit = int(st.number_input("심층 분석 종목 수", 5, 2800, min(20, universe_limit), 5))
        deep_limit = min(deep_limit, universe_limit)
        max_positions = int(st.slider("최대 보유 종목", 1, 10, 5))
        full_market = st.checkbox("유동성 적격 전체시장 분석", value=False)
        account_equity = float(
            st.number_input("총 운용자금(원)", min_value=1_000_000, value=int(base_config.account_equity), step=10_000_000)
        )

        st.subheader("현재 보유 종목")
        holdings_text = st.text_area(
            "종목코드 수량 평균단가",
            placeholder="005930 20 72000\n000660 5 185000",
            help="한 줄에 한 종목씩 공백으로 구분합니다. 보유 종목은 순위와 무관하게 매도·축소·보유 분석에 포함됩니다.",
        )
        holdings, holding_errors = parse_holdings(holdings_text)
        for error in holding_errors:
            st.error(error)

        st.divider()
        st.subheader("실제 연결 상태")
        if base_config.groq_api_key:
            st.success(f"Groq 연결 키 확인 · 모델 {base_config.groq_model}")
        else:
            st.error("Groq 키 없음 · AI 분석과 매매 판단 실행 차단")
        st.write(f"수급: {'KRX 공식값' if base_config.krx_ready else '네이버 추정값(표시됨)'}")
        st.write(f"공시: {'OpenDART 공식값' if base_config.dart_api_key else 'KOSCOM 대체값(표시됨)'}")
        st.caption("키 값 자체는 화면이나 로그에 출력하지 않습니다.")

        run_clicked = st.button(
            "예측·AI 분석 실행",
            type="primary",
            width="stretch",
            disabled=bool(holding_errors) or not bool(base_config.groq_api_key),
        )
        evaluate_clicked = st.button("지난 BUY/HOLD 사후평가", width="stretch")

    config = replace(base_config, account_equity=account_equity)
    if run_clicked:
        _run_pipeline(
            config,
            strategy=strategy,
            universe_limit=0 if full_market else universe_limit,
            deep_limit=0 if full_market else deep_limit,
            max_positions=max_positions,
            holdings=holdings,
        )
    if evaluate_clicked:
        pipeline = FundManagerPipeline(config)
        with st.spinner("만기가 지난 BUY/HOLD 판단을 실제 가격과 비교합니다."):
            evaluated = PerformanceEngine(config, pipeline.storage, pipeline.data).evaluate_due()
        if evaluated:
            st.success(f"{len(evaluated)}건 사후평가 완료")
        else:
            st.info("평가 기한이 지난 판단이 없습니다.")

    result = st.session_state.get("fund_manager_result")
    tabs = st.tabs(["오늘의 행동", "예측·팩터 순위", "AI 분석 원문", "사후평가", "산출 방식"])
    with tabs[0]:
        if result:
            render_actions(result, config)
        else:
            st.info("왼쪽에서 예측·AI 분석을 실행하세요.")
    with tabs[1]:
        if result:
            render_ranking(result)
        else:
            st.info("아직 실행 결과가 없습니다.")
    with tabs[2]:
        if result and result.get("ranked"):
            render_detail(result)
        else:
            st.info("분석 결과가 없습니다.")
    with tabs[3]:
        render_history(FundManagerPipeline(config).storage.history())
    with tabs[4]:
        render_methodology(config)

    st.divider()
    st.caption("통계적 예측과 AI 분석은 수익을 보장하지 않습니다. 이 앱은 주문 계획만 만들며 증권사에 자동 주문을 전송하지 않습니다.")


def _run_pipeline(config: AppConfig, **kwargs) -> None:
    pipeline = FundManagerPipeline(config)
    progress_bar = st.progress(0.0)
    status_box = st.empty()
    ranges = {
        "universe": (0.00, 0.06),
        "prices": (0.06, 0.38),
        "enrich": (0.38, 0.64),
        "validate": (0.64, 0.85),
        "judge": (0.85, 1.00),
    }

    def progress(stage: str, current: int, total: int, message: str) -> None:
        start, end = ranges.get(stage, (0.0, 1.0))
        progress_bar.progress(min(1.0, start + (end - start) * (current / total if total else 1)))
        status_box.info(message)

    try:
        result = pipeline.run(require_ai=True, progress=progress, **kwargs)
        st.session_state["fund_manager_result"] = result
        progress_bar.progress(1.0)
        status_box.success(f"예측과 Groq 분석 완료 · 실행 ID {result['run_id'][:10]}")
    except AIUnavailableError as exc:
        status_box.error(f"AI 분석 실패로 매매 판단을 생성하지 않았습니다: {exc}")
    except Exception as exc:
        status_box.error(f"파이프라인 중단: {type(exc).__name__}: {exc}")


def render_actions(result: dict, config: AppConfig) -> None:
    portfolio = result["portfolio"]
    actions = [item.get("ai_review", {}).get("action", "NO_ACTION") for item in result["ranked"]]
    cols = st.columns(6)
    for col, action in zip(cols[:4], ["BUY", "HOLD", "REDUCE", "SELL"]):
        col.metric(ACTION_KO[action], actions.count(action))
    cols[4].metric("투자 비중", f"{portfolio['invested_weight'] * 100:.1f}%")
    cols[5].metric("현금 비중", f"{portfolio['cash_weight'] * 100:.1f}%")
    st.caption(
        f"시장 {portfolio['regime']['regime'].upper()} · {portfolio['regime']['reason']} · "
        f"손절 기준 총위험 {portfolio['portfolio_stop_risk_pct']:.2f}%"
    )

    rows = []
    for item in result["ranked"]:
        review = item.get("ai_review", {})
        plan = item.get("trade_plan", {})
        forecast = item.get("forecast", {}).get("horizons", {})
        f5, f20 = forecast.get("5", {}), forecast.get("20", {})
        rows.append(
            {
                "행동": ACTION_KO.get(review.get("action"), review.get("action")),
                "종목": f"{item['name']} ({item['ticker']})",
                "보유수량": int((item.get("holding") or {}).get("quantity") or 0),
                "5일 예상수익": _pct(f5.get("expected_return_pct")),
                "5일 상승확률": _pct(f5.get("up_probability_pct")),
                "20일 예상수익": _pct(f20.get("expected_return_pct")),
                "현재가": _won(plan.get("reference_price")),
                "진입구간": f"{_won(plan.get('entry_zone_low'))} ~ {_won(plan.get('entry_zone_high'))}",
                "손절가": _won(plan.get("stop_price")),
                "5일 목표": _won(plan.get("target_5d")),
                "20일 목표": _won(plan.get("target_20d")),
                "주문": f"{plan.get('order_side', 'NONE')} {int(plan.get('order_quantity') or 0)}주",
                "AI 확신도": f"{review.get('confidence', 0)}%",
            }
        )
    st.subheader("오늘의 매매 계획")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    actionable = [item for item in result["ranked"] if item.get("ai_review", {}).get("action") in {"BUY", "HOLD", "REDUCE", "SELL"}]
    for item in actionable:
        review = item["ai_review"]
        with st.expander(f"{ACTION_KO[review['action']]} · {item['name']} ({item['ticker']})", expanded=review["action"] in {"BUY", "SELL"}):
            st.write(review.get("forecast_summary"))
            st.write("판단 근거:", review.get("thesis"))
            st.write("반대 논리:", review.get("counter_thesis"))
            if review.get("risks"):
                st.write("위험:", " · ".join(review["risks"]))

    coverage = result["data_status"]
    st.subheader("데이터·모델 실행 확인")
    st.json(coverage, expanded=False)
    if result.get("errors"):
        st.warning(f"수집 오류 {len(result['errors'])}건: " + " / ".join(result["errors"][:5]))


def render_ranking(result: dict) -> None:
    rows = []
    for rank, item in enumerate(result["ranked"], start=1):
        h5 = item.get("forecast", {}).get("horizons", {}).get("5", {})
        h20 = item.get("forecast", {}).get("horizons", {}).get("20", {})
        rows.append(
            {
                "순위": rank,
                "종목코드": item["ticker"],
                "종목명": item["name"],
                "종합점수": item["total_score"],
                "가치": item.get("value_score"),
                "모멘텀": item.get("momentum_score"),
                "수급": item.get("flow_score"),
                "품질": item.get("quality_score"),
                "변동성": item.get("volatility_score"),
                "뉴스": item.get("news_score"),
                "5일예측%": h5.get("expected_return_pct"),
                "5일상승확률%": h5.get("up_probability_pct"),
                "20일예측%": h20.get("expected_return_pct"),
                "OOS정확도%": h5.get("oos_directional_accuracy_pct"),
                "AI 행동": ACTION_KO.get(item.get("ai_review", {}).get("action"), "판단 없음"),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render_detail(result: dict) -> None:
    options = {f"{item['ticker']} · {item['name']}": item for item in result["ranked"]}
    candidate = options[st.selectbox("종목", list(options))]
    review = candidate.get("ai_review", {})
    forecast = candidate.get("forecast", {})
    left, right = st.columns([1, 1])
    with left:
        st.subheader(f"{ACTION_KO.get(review.get('action'), review.get('action'))} · 확신도 {review.get('confidence', 0)}%")
        st.write(review.get("forecast_summary"))
        st.markdown("**핵심 논리**")
        st.write(review.get("thesis"))
        st.markdown("**가장 강한 반대 논리**")
        st.write(review.get("counter_thesis"))
        for label, key in [("촉매", "catalysts"), ("위험", "risks"), ("데이터 한계", "data_gaps"), ("무효화 조건", "invalidation")]:
            values = review.get(key) or []
            if values:
                st.markdown(f"**{label}**")
                st.write("\n".join(f"- {value}" for value in values))
        st.caption(f"실제 분석원: {review.get('source')} · 허용 행동: {', '.join(candidate.get('quant_signal', {}).get('allowed_ai_actions', []))}")
    with right:
        st.subheader("워크포워드 예측 진단")
        st.json(forecast, expanded=True)

    scores = {label: candidate.get(key) for label, key in [("가치", "value_score"), ("모멘텀", "momentum_score"), ("수급", "flow_score"), ("품질", "quality_score"), ("변동성", "volatility_score"), ("뉴스", "news_score")]}
    labels = [key for key, value in scores.items() if value is not None]
    values = [scores[key] for key in labels]
    if labels:
        figure = go.Figure(go.Scatterpolar(r=values + [values[0]], theta=labels + [labels[0]], fill="toself"))
        figure.update_layout(height=360, margin=dict(l=30, r=30, t=30, b=30), polar=dict(radialaxis=dict(range=[0, 100])))
        st.plotly_chart(figure, width="stretch")
    with st.expander("정량 입력·위험·백테스트 원문"):
        st.json({"facts": candidate.get("facts"), "backtest": candidate.get("backtest"), "risk": candidate.get("risk"), "trade_plan": candidate.get("trade_plan")}, expanded=False)


def render_history(history: pd.DataFrame) -> None:
    if history.empty:
        st.info("저장된 판단이 없습니다.")
        return
    columns = [column for column in ["as_of_date", "ticker", "name", "strategy", "ai_decision", "ai_confidence", "entry_price", "stop_price", "quantity", "net_return", "excess_return", "outcome", "failure_reason"] if column in history]
    st.dataframe(history[columns], hide_index=True, width="stretch")


def render_methodology(config: AppConfig) -> None:
    st.markdown(
        f"""
### 1. 데이터 엔진
가격·거래량·재무·수급·뉴스·공시를 원천, 기준일, 상태와 함께 SQLite에 저장합니다.

### 2. 퀀트와 예측 엔진
가치·모멘텀·수급·품질·변동성·뉴스 점수를 전 종목에 계산합니다. 5일·20일 수익률은 15개 가격·거래량 특징을 사용한 확장형 워크포워드 ridge 모델과 과거 유사 국면 중앙값을 결합해 추정합니다. 각 시점에서 목표 수익률이 이미 확정된 표본만 학습합니다.

### 3. 검증 엔진
다음 거래일 진입, {config.holding_days}거래일 보유, 왕복 비용 {config.commission_bps + config.slippage_bps:.0f}bp, ATR 손절과 벤치마크 초과수익을 반영합니다.

### 4. 행동·리스크 엔진
미보유 종목은 BUY/WATCH/AVOID, 보유 종목은 HOLD/REDUCE/SELL 중에서 판단합니다. BUY는 예측·확률·OOS 정확도·백테스트·완성도·리스크 기준을 모두 통과해야 AI의 선택지에 들어갑니다. 종목당 {config.max_position_pct:.0%}, 업종 {config.max_sector_pct:.0%}, 거래당 위험 {config.risk_per_trade:.2%}, 총위험 {config.max_portfolio_risk:.1%}를 제한합니다.

### 5. Groq AI 분석가
AI는 계산된 수치, 뉴스·공시 목록, 예측 진단과 반대 논리를 종합합니다. 숫자를 새로 만들 수 없고 허용된 행동만 고릅니다. API 실패 시 규칙 결과를 AI 결과로 위장하지 않고 전체 판단을 중단합니다.

### 6. 사후평가
BUY/HOLD 판단을 이후 실제 수익률·비용·벤치마크와 비교해 성공 여부와 실패 원인을 저장합니다.
"""
    )


def _pct(value) -> str:
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "-"


def _won(value) -> str:
    try:
        return f"{float(value):,.0f}원"
    except (TypeError, ValueError):
        return "-"


if __name__ == "__main__":
    main()

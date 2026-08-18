from __future__ import annotations

import html as html_lib
from dataclasses import replace

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ai_judge import AIUnavailableError
from config import AppConfig
from performance_engine import PerformanceEngine
from pipeline import FundManagerPipeline
from portfolio_input import parse_holdings


st.set_page_config(page_title="AI Fund Manager", page_icon="📊", layout="wide")

STRATEGIES = {
    "balanced": "균형형 멀티팩터",
    "rebound": "과매도 반등",
    "breakout": "거래량 돌파",
}
ACTION_KO = {
    "BUY": "매수",
    "HOLD": "보유",
    "REDUCE": "비중 축소",
    "SELL": "매도",
    "WATCH": "관찰",
    "AVOID": "매수 제외",
    "NO_ACTION": "판단 없음",
}
ACTION_PRIORITY = {"SELL": 0, "REDUCE": 1, "BUY": 2, "HOLD": 3, "WATCH": 4, "AVOID": 5, "NO_ACTION": 6}


def main() -> None:
    apply_theme()
    st.markdown(
        """
        <div class="product-header">
          <div>
            <div class="product-kicker">QUANTITATIVE DECISION SUPPORT</div>
            <h1>오늘의 투자 판단</h1>
            <p>수익률 예측, 검증, 리스크 한도와 AI 근거 분석을 한 화면에서 확인합니다.</p>
          </div>
          <div class="trust-mark"><span></span> 계산 엔진과 AI 판단 분리</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    base_config = AppConfig()
    with st.sidebar:
        st.markdown("## 운용 조건")
        st.caption("판단 전에 투자 범위와 보유 현황을 먼저 입력하세요.")
        strategy = st.selectbox("전략", list(STRATEGIES), format_func=lambda key: STRATEGIES[key])
        account_equity = float(
            st.number_input(
                "총 운용자금",
                min_value=1_000_000,
                value=int(base_config.account_equity),
                step=10_000_000,
                help="보유자산과 신규 주문을 합산해 위험 한도를 계산합니다.",
            )
        )
        max_positions = int(st.slider("최대 보유 종목", 1, 10, 5))

        with st.expander("분석 범위", expanded=True):
            universe_limit = int(st.number_input("1차 가격 검사", 20, 2800, 80, 20))
            deep_limit = int(st.number_input("심층 분석", 5, 2800, min(20, universe_limit), 5))
            deep_limit = min(deep_limit, universe_limit)
            full_market = st.checkbox("유동성 적격 전체시장", value=False)
            st.caption("전체시장 분석은 최초 실행 시간이 길 수 있습니다.")

        st.markdown("### 현재 보유 종목")
        holdings_text = st.text_area(
            "종목코드  수량  평균단가",
            placeholder="005930  20  72000\n000660  5  185000",
            help="한 줄에 한 종목씩 입력합니다. 보유 종목은 순위와 관계없이 보유·축소·매도 판단에 포함됩니다.",
        )
        holdings, holding_errors = parse_holdings(holdings_text)
        for error in holding_errors:
            st.error(error)

        st.markdown("### 데이터 연결")
        _connection_row("Groq 분석", bool(base_config.groq_api_key), base_config.groq_model if base_config.groq_api_key else "연결 필요")
        _connection_row("투자자 수급", base_config.krx_ready, "KRX 공식" if base_config.krx_ready else "네이버 추정")
        _connection_row("기업 공시", bool(base_config.dart_api_key), "OpenDART" if base_config.dart_api_key else "KOSCOM 대체")
        st.caption("대체 데이터는 결과 화면에 출처와 함께 표시됩니다.")

        run_clicked = st.button(
            "오늘의 판단 생성",
            type="primary",
            width="stretch",
            disabled=bool(holding_errors) or not bool(base_config.groq_api_key),
        )
        evaluate_clicked = st.button("지난 판단 성과 업데이트", width="stretch")

    config = replace(base_config, account_equity=account_equity)
    if run_clicked:
        _run_pipeline(
            config,
            strategy=strategy,
            universe_limit=0 if full_market else universe_limit,
            deep_analysis_limit=0 if full_market else deep_limit,
            max_positions=max_positions,
            holdings=holdings,
        )
    if evaluate_clicked:
        pipeline = FundManagerPipeline(config)
        with st.spinner("만기가 지난 판단을 실제 가격과 비교하고 있습니다."):
            evaluated = PerformanceEngine(config, pipeline.storage, pipeline.data).evaluate_due()
        if evaluated:
            st.success(f"성과 평가 {len(evaluated)}건을 업데이트했습니다.")
        else:
            st.info("새로 평가할 BUY/HOLD 판단이 없습니다.")

    result = st.session_state.get("fund_manager_result")
    tabs = st.tabs(["투자 판단", "후보 비교", "종목 리포트", "성과 추적", "검증 기준"])
    with tabs[0]:
        if result:
            render_actions(result)
        else:
            render_empty_state()
    with tabs[1]:
        if result:
            render_ranking(result)
        else:
            st.info("판단을 실행하면 전 종목 후보 비교표가 표시됩니다.")
    with tabs[2]:
        if result and result.get("ranked"):
            render_detail(result)
        else:
            st.info("종목별 상세 리포트가 아직 없습니다.")
    with tabs[3]:
        render_history(FundManagerPipeline(config).storage.history())
    with tabs[4]:
        render_methodology(config)

    st.markdown(
        "<div class='legal-note'>통계적 예측과 AI 분석은 수익을 보장하지 않습니다. 주문 계획만 생성하며 증권사 주문은 자동 전송하지 않습니다.</div>",
        unsafe_allow_html=True,
    )


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        :root { --navy:#14213d; --blue:#2457d6; --line:#dfe4ec; --muted:#667085; --bg:#f5f7fa; --green:#067647; --red:#b42318; --amber:#b54708; }
        html, body, [class*="css"] { font-family:"Pretendard Variable","Pretendard","Noto Sans KR","Apple SD Gothic Neo","Malgun Gothic","Segoe UI",sans-serif; }
        .stApp { background:var(--bg); color:#182230; }
        .block-container { max-width:1480px; padding-top:2.2rem; padding-bottom:3rem; }
        [data-testid="stSidebar"] { background:#fff; border-right:1px solid var(--line); }
        [data-testid="stSidebar"] .block-container { padding-top:1.5rem; }
        h1,h2,h3 { color:var(--navy); letter-spacing:-.025em; }
        .product-header { display:flex; align-items:flex-end; justify-content:space-between; gap:24px; margin:0 0 26px; }
        .product-header h1 { margin:7px 0 8px; font-size:2.15rem; line-height:1.2; font-weight:750; }
        .product-header p { margin:0; color:var(--muted); font-size:.98rem; }
        .product-kicker { color:var(--blue); font-size:.72rem; font-weight:800; letter-spacing:.12em; }
        .trust-mark { background:#fff; border:1px solid var(--line); border-radius:8px; padding:10px 13px; color:#475467; font-size:.78rem; font-weight:650; white-space:nowrap; }
        .trust-mark span { display:inline-block; width:7px; height:7px; margin-right:7px; border-radius:50%; background:var(--green); }
        [data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:10px; padding:17px 18px; box-shadow:0 1px 2px rgba(16,24,40,.03); }
        [data-testid="stMetricLabel"] { color:var(--muted); font-size:.79rem; }
        [data-testid="stMetricValue"] { color:var(--navy); font-weight:750; font-variant-numeric:tabular-nums; }
        [data-testid="stTabs"] [role="tablist"] { gap:24px; border-bottom:1px solid var(--line); }
        [data-testid="stTabs"] button { padding:.8rem .15rem; font-weight:650; color:#667085; }
        [data-testid="stTabs"] button[aria-selected="true"] { color:var(--blue); }
        [data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:10px; overflow:hidden; }
        .section-head { display:flex; align-items:flex-end; justify-content:space-between; margin:28px 0 13px; gap:16px; }
        .section-head h2 { margin:0; font-size:1.12rem; }
        .section-head p { margin:0; color:var(--muted); font-size:.8rem; }
        .run-strip { display:flex; flex-wrap:wrap; gap:8px 18px; margin:2px 0 18px; padding:12px 15px; background:#eef4ff; border:1px solid #d7e4ff; border-radius:8px; color:#344054; font-size:.79rem; }
        .run-strip strong { color:var(--navy); }
        .decision-panel { background:#fff; border:1px solid var(--line); border-left:4px solid var(--blue); border-radius:10px; padding:18px 20px; margin:10px 0; box-shadow:0 1px 3px rgba(16,24,40,.04); }
        .decision-panel.buy,.decision-panel.hold { border-left-color:var(--green); }
        .decision-panel.sell,.decision-panel.avoid { border-left-color:var(--red); }
        .decision-panel.reduce,.decision-panel.watch { border-left-color:var(--amber); }
        .decision-title { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }
        .decision-title h3 { margin:0 0 3px; font-size:1.08rem; }
        .decision-title small { color:var(--muted); font-variant-numeric:tabular-nums; }
        .action-pill { display:inline-flex; min-width:72px; justify-content:center; padding:6px 10px; border-radius:6px; font-size:.76rem; font-weight:800; }
        .action-pill.buy,.action-pill.hold { color:#05603a; background:#ecfdf3; }
        .action-pill.sell,.action-pill.avoid { color:#912018; background:#fef3f2; }
        .action-pill.reduce,.action-pill.watch { color:#93370d; background:#fffaeb; }
        .action-pill.no_action { color:#475467; background:#f2f4f7; }
        .decision-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:14px; margin:17px 0 12px; }
        .decision-grid div { padding-right:12px; border-right:1px solid #eaecf0; }
        .decision-grid div:last-child { border-right:0; }
        .decision-grid span { display:block; color:var(--muted); font-size:.72rem; margin-bottom:5px; }
        .decision-grid strong { color:var(--navy); font-size:.92rem; font-variant-numeric:tabular-nums; }
        .decision-summary { margin:0; color:#475467; font-size:.84rem; line-height:1.65; }
        .source-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:8px; margin-top:10px; }
        .source-item { background:#fff; border:1px solid var(--line); border-radius:8px; padding:12px; }
        .source-item span { display:block; color:var(--muted); font-size:.7rem; }
        .source-item strong { display:block; margin-top:5px; color:var(--navy); font-size:.86rem; }
        .empty-card { background:#fff; border:1px solid var(--line); border-radius:12px; padding:54px 32px; text-align:center; }
        .empty-card h2 { margin:0 0 10px; font-size:1.3rem; }
        .empty-card p { margin:0 auto; max-width:620px; color:var(--muted); line-height:1.7; }
        .process-row { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; max-width:780px; margin:28px auto 0; text-align:left; }
        .process-row div { border-top:2px solid #d0d5dd; padding-top:9px; color:#475467; font-size:.78rem; }
        .process-row b { color:var(--blue); margin-right:4px; }
        .legal-note { margin-top:34px; padding-top:16px; border-top:1px solid var(--line); color:#667085; font-size:.74rem; line-height:1.6; }
        .stButton>button[kind="primary"] { background:var(--blue); border-color:var(--blue); border-radius:7px; font-weight:700; }
        .stButton>button { border-radius:7px; font-weight:650; }
        code, [data-testid="stMetricValue"], .num { font-variant-numeric:tabular-nums; }
        @media(max-width:900px){ .product-header{align-items:flex-start;flex-direction:column}.decision-grid{grid-template-columns:repeat(2,1fr)}.decision-grid div{border-right:0}.source-grid{grid-template-columns:repeat(2,1fr)}.process-row{grid-template-columns:1fr 1fr} }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _connection_row(label: str, primary: bool, value: str) -> None:
    color = "#067647" if primary else "#b54708"
    st.markdown(
        f"<div style='display:flex;justify-content:space-between;gap:12px;margin:7px 0;font-size:.78rem'>"
        f"<span style='color:#667085'>{html_lib.escape(label)}</span>"
        f"<strong style='color:{color};font-weight:700'>{html_lib.escape(value)}</strong></div>",
        unsafe_allow_html=True,
    )


def _run_pipeline(config: AppConfig, **kwargs) -> None:
    pipeline = FundManagerPipeline(config)
    progress_bar = st.progress(0.0)
    status_box = st.empty()
    ranges = {"universe": (0.00, 0.06), "prices": (0.06, 0.38), "enrich": (0.38, 0.64), "validate": (0.64, 0.85), "judge": (0.85, 1.00)}

    def progress(stage: str, current: int, total: int, message: str) -> None:
        start, end = ranges.get(stage, (0.0, 1.0))
        progress_bar.progress(min(1.0, start + (end - start) * (current / total if total else 1)))
        status_box.info(message)

    try:
        result = pipeline.run(require_ai=True, progress=progress, **kwargs)
        st.session_state["fund_manager_result"] = result
        progress_bar.progress(1.0)
        status_box.success(f"판단 생성 완료 · 실행번호 {result['run_id'][:10]}")
    except AIUnavailableError as exc:
        status_box.error(f"AI 분석이 완료되지 않아 판단을 생성하지 않았습니다: {exc}")
    except Exception as exc:
        status_box.error(f"분석 중단: {type(exc).__name__}: {exc}")


def render_empty_state() -> None:
    st.markdown(
        """
        <div class="empty-card">
          <h2>아직 생성된 투자 판단이 없습니다</h2>
          <p>왼쪽에서 운용자금과 보유 종목을 확인한 뒤 ‘오늘의 판단 생성’을 누르세요. 계산된 수치가 충분한 후보만 Groq 분석 단계로 전달됩니다.</p>
          <div class="process-row"><div><b>01</b> 데이터 수집</div><div><b>02</b> 수익률 예측</div><div><b>03</b> 리스크 산정</div><div><b>04</b> AI 최종 판단</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_actions(result: dict) -> None:
    portfolio = result["portfolio"]
    ranked = sorted(result["ranked"], key=lambda item: ACTION_PRIORITY.get(item.get("ai_review", {}).get("action", "NO_ACTION"), 99))
    actions = [item.get("ai_review", {}).get("action", "NO_ACTION") for item in ranked]
    st.markdown(
        f"<div class='run-strip'><span>기준일 <strong>{html_lib.escape(result['as_of_date'])}</strong></span>"
        f"<span>검사 <strong>{result['filtered_universe_count']:,}종목</strong></span>"
        f"<span>심층분석 <strong>{result['deep_analysis_count']:,}종목</strong></span>"
        f"<span>AI 원천 <strong>Groq</strong></span><span>실행번호 <strong>{html_lib.escape(result['run_id'][:10])}</strong></span></div>",
        unsafe_allow_html=True,
    )
    cols = st.columns(6)
    cols[0].metric("매수", actions.count("BUY"))
    cols[1].metric("보유", actions.count("HOLD"))
    cols[2].metric("축소·매도", actions.count("REDUCE") + actions.count("SELL"))
    cols[3].metric("관찰·제외", actions.count("WATCH") + actions.count("AVOID"))
    cols[4].metric("투자 비중", f"{portfolio['invested_weight'] * 100:.1f}%")
    cols[5].metric("손절 총위험", f"{portfolio['portfolio_stop_risk_pct']:.2f}%")
    st.caption(f"현금 {portfolio['cash_weight'] * 100:.1f}% · 시장 {portfolio['regime']['regime'].upper()} · {portfolio['regime']['reason']}")

    st.markdown("<div class='section-head'><h2>우선 확인할 판단</h2><p>주문이 있거나 현재 보유 중인 종목을 먼저 표시합니다.</p></div>", unsafe_allow_html=True)
    primary = [item for item in ranked if item.get("ai_review", {}).get("action") in {"BUY", "HOLD", "REDUCE", "SELL"}]
    if not primary:
        st.info("실행 또는 보유 판단이 없습니다. 모든 후보는 관찰 또는 매수 제외 상태입니다.")
    for item in primary:
        _decision_card(item)
        review = item.get("ai_review", {})
        with st.expander(f"{item['name']} 근거와 반대 논리"):
            st.markdown("**AI 판단 근거**")
            st.write(review.get("thesis"))
            st.markdown("**반대 논리**")
            st.write(review.get("counter_thesis"))
            if review.get("risks"):
                st.markdown("**핵심 위험**")
                st.write("\n".join(f"- {value}" for value in review["risks"]))

    st.markdown("<div class='section-head'><h2>전체 판단표</h2><p>예측과 주문 계획을 동일한 기준으로 비교합니다.</p></div>", unsafe_allow_html=True)
    st.dataframe(
        _action_frame(ranked),
        hide_index=True,
        width="stretch",
        column_config={
            "5일 예상": st.column_config.NumberColumn(format="%+.2f%%"),
            "상승확률": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
            "20일 예상": st.column_config.NumberColumn(format="%+.2f%%"),
            "현재가": st.column_config.NumberColumn(format="%,.0f원"),
            "손절가": st.column_config.NumberColumn(format="%,.0f원"),
            "AI 확신도": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
        },
    )

    st.markdown("<div class='section-head'><h2>근거 데이터 상태</h2><p>추정·대체 데이터는 공식 데이터와 구분합니다.</p></div>", unsafe_allow_html=True)
    _render_source_status(result["data_status"])
    if result.get("errors"):
        st.warning(f"수집 오류 {len(result['errors'])}건 · " + " / ".join(result["errors"][:5]))


def _decision_card(item: dict) -> None:
    review = item.get("ai_review", {})
    plan = item.get("trade_plan", {})
    horizons = item.get("forecast", {}).get("horizons", {})
    f5, f20 = horizons.get("5", {}), horizons.get("20", {})
    action = review.get("action", "NO_ACTION")
    action_class = action.lower()
    summary = html_lib.escape(str(review.get("forecast_summary") or review.get("thesis") or "근거 없음"))
    order_text = "주문 없음"
    if plan.get("order_side") in {"BUY", "SELL"} and int(plan.get("order_quantity") or 0) > 0:
        order_text = f"{plan['order_side']} {int(plan['order_quantity']):,}주"
    st.markdown(
        f"""
        <div class="decision-panel {action_class}">
          <div class="decision-title"><div><h3>{html_lib.escape(item['name'])}</h3><small>{html_lib.escape(item['ticker'])} · {html_lib.escape(item.get('sector') or '업종 미분류')}</small></div><span class="action-pill {action_class}">{html_lib.escape(ACTION_KO.get(action, action))}</span></div>
          <div class="decision-grid">
            <div><span>현재가</span><strong>{_won(plan.get('reference_price'))}</strong></div>
            <div><span>5일 예상 / 상승확률</span><strong>{_pct(f5.get('expected_return_pct'))} / {_plain_pct(f5.get('up_probability_pct'))}</strong></div>
            <div><span>20일 예상</span><strong>{_pct(f20.get('expected_return_pct'))}</strong></div>
            <div><span>손절 기준</span><strong>{_won(plan.get('stop_price'))}</strong></div>
            <div><span>실행 계획</span><strong>{html_lib.escape(order_text)}</strong></div>
          </div>
          <p class="decision-summary">{summary}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _action_frame(items: list[dict]) -> pd.DataFrame:
    rows = []
    for item in items:
        review = item.get("ai_review", {})
        plan = item.get("trade_plan", {})
        horizons = item.get("forecast", {}).get("horizons", {})
        f5, f20 = horizons.get("5", {}), horizons.get("20", {})
        order = "-"
        if plan.get("order_side") in {"BUY", "SELL"} and int(plan.get("order_quantity") or 0) > 0:
            order = f"{plan['order_side']} {int(plan['order_quantity']):,}주"
        rows.append({
            "판단": ACTION_KO.get(review.get("action"), review.get("action")),
            "종목": f"{item['name']} · {item['ticker']}",
            "5일 예상": f5.get("expected_return_pct"),
            "상승확률": f5.get("up_probability_pct"),
            "20일 예상": f20.get("expected_return_pct"),
            "현재가": plan.get("reference_price"),
            "손절가": plan.get("stop_price"),
            "주문": order,
            "AI 확신도": review.get("confidence", 0),
        })
    return pd.DataFrame(rows)


def _render_source_status(status: dict) -> None:
    sources = [
        ("가격·유동성", status.get("universe_scope", {}), "시장 전체 대비 검사 범위"),
        ("재무", status.get("fundamentals", {}), "기업 재무지표"),
        ("수급", status.get("investor_flow", {}), status.get("investor_flow", {}).get("primary", "-")),
        ("뉴스", status.get("news", {}), "구조화 뉴스"),
        ("공시", status.get("disclosures", {}), status.get("disclosures", {}).get("primary", "-")),
    ]
    html = "<div class='source-grid'>"
    for label, item, description in sources:
        covered, total = item.get("covered", 0), item.get("total", 0)
        html += f"<div class='source-item'><span>{html_lib.escape(label)}</span><strong>{covered:,} / {total:,}</strong><span>{html_lib.escape(str(description))}</span></div>"
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_ranking(result: dict) -> None:
    rows = []
    for rank, item in enumerate(result["ranked"], start=1):
        h5 = item.get("forecast", {}).get("horizons", {}).get("5", {})
        h20 = item.get("forecast", {}).get("horizons", {}).get("20", {})
        rows.append({
            "순위": rank, "종목": item["name"], "코드": item["ticker"], "종합점수": item["total_score"],
            "가치": item.get("value_score"), "모멘텀": item.get("momentum_score"), "수급": item.get("flow_score"),
            "품질": item.get("quality_score"), "변동성": item.get("volatility_score"), "뉴스": item.get("news_score"),
            "5일 예상": h5.get("expected_return_pct"), "상승확률": h5.get("up_probability_pct"),
            "20일 예상": h20.get("expected_return_pct"), "OOS 정확도": h5.get("oos_directional_accuracy_pct"),
            "최종 판단": ACTION_KO.get(item.get("ai_review", {}).get("action"), "판단 없음"),
        })
    st.markdown("<div class='section-head'><h2>후보 비교</h2><p>팩터 점수와 예측 검증을 함께 확인하세요.</p></div>", unsafe_allow_html=True)
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, width="stretch",
        column_config={
            "5일 예상": st.column_config.NumberColumn(format="%+.2f%%"), "20일 예상": st.column_config.NumberColumn(format="%+.2f%%"),
            "상승확률": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
            "OOS 정확도": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
        },
    )


def render_detail(result: dict) -> None:
    options = {f"{item['name']} · {item['ticker']}": item for item in result["ranked"]}
    candidate = options[st.selectbox("리포트 종목", list(options))]
    review = candidate.get("ai_review", {})
    plan = candidate.get("trade_plan", {})
    horizons = candidate.get("forecast", {}).get("horizons", {})
    f5, f20 = horizons.get("5", {}), horizons.get("20", {})
    st.markdown(f"### {candidate['name']} <span style='color:#667085;font-size:.82rem'>{candidate['ticker']}</span>", unsafe_allow_html=True)
    metrics = st.columns(5)
    metrics[0].metric("최종 판단", ACTION_KO.get(review.get("action"), review.get("action")))
    metrics[1].metric("현재가", _won(plan.get("reference_price")))
    metrics[2].metric("5일 예상", _pct(f5.get("expected_return_pct")))
    metrics[3].metric("상승확률", _plain_pct(f5.get("up_probability_pct")))
    metrics[4].metric("20일 예상", _pct(f20.get("expected_return_pct")))

    left, right = st.columns([1.2, 0.8])
    with left:
        st.markdown("#### AI 최종 의견")
        st.write(review.get("thesis"))
        st.markdown("#### 반대 논리")
        st.write(review.get("counter_thesis"))
        for label, key in [("주요 촉매", "catalysts"), ("핵심 위험", "risks"), ("데이터 한계", "data_gaps"), ("재검토 조건", "invalidation")]:
            values = review.get(key) or []
            if values:
                with st.expander(label, expanded=key in {"risks", "invalidation"}):
                    st.write("\n".join(f"- {value}" for value in values))
    with right:
        st.markdown("#### 실행 가격")
        execution = pd.DataFrame([
            ("진입 하단", plan.get("entry_zone_low")), ("진입 상단", plan.get("entry_zone_high")),
            ("손절 기준", plan.get("stop_price")), ("5일 목표", plan.get("target_5d")), ("20일 목표", plan.get("target_20d")),
        ], columns=["구분", "가격"])
        st.dataframe(execution, hide_index=True, width="stretch", column_config={"가격": st.column_config.NumberColumn(format="%,.0f원")})
        st.caption(f"주문 계획: {plan.get('order_side', 'NONE')} {int(plan.get('order_quantity') or 0):,}주 · 자동 주문 아님")

    scores = {label: candidate.get(key) for label, key in [("가치", "value_score"), ("모멘텀", "momentum_score"), ("수급", "flow_score"), ("품질", "quality_score"), ("변동성", "volatility_score"), ("뉴스", "news_score")]}
    labels = [label for label, value in scores.items() if value is not None]
    values = [scores[label] for label in labels]
    if labels:
        figure = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker_color="#2457d6", text=[f"{value:.1f}" for value in values], textposition="outside"))
        figure.update_layout(height=300, margin=dict(l=10, r=40, t=20, b=20), xaxis=dict(range=[0, 100], gridcolor="#eaecf0", title=None), yaxis=dict(autorange="reversed", title=None), plot_bgcolor="white", paper_bgcolor="white", showlegend=False)
        st.markdown("#### 팩터 구성")
        st.plotly_chart(figure, width="stretch")
    with st.expander("감사 가능한 원본 데이터"):
        st.json({"facts": candidate.get("facts"), "forecast": candidate.get("forecast"), "backtest": candidate.get("backtest"), "risk": candidate.get("risk"), "trade_plan": plan}, expanded=False)
    st.caption(f"AI 분석원 {review.get('source')} · AI 허용 행동 {', '.join(candidate.get('quant_signal', {}).get('allowed_ai_actions', []))}")


def render_history(history: pd.DataFrame) -> None:
    st.markdown("<div class='section-head'><h2>성과 추적</h2><p>당시 판단과 이후 실제 성과를 연결합니다.</p></div>", unsafe_allow_html=True)
    if history.empty:
        st.info("저장된 판단이 없습니다.")
        return
    columns = [column for column in ["as_of_date", "ticker", "name", "strategy", "ai_decision", "ai_confidence", "entry_price", "stop_price", "quantity", "net_return", "excess_return", "outcome", "failure_reason"] if column in history]
    st.dataframe(history[columns], hide_index=True, width="stretch")


def render_methodology(config: AppConfig) -> None:
    st.markdown("## 판단이 만들어지는 순서")
    st.markdown(
        f"""
1. **데이터 확인** — 가격·거래량·재무·수급·뉴스·공시를 원천, 기준일, 상태와 함께 저장합니다.
2. **후보 점수화** — 가치·모멘텀·수급·품질·변동성·뉴스 점수로 전체 종목을 비교합니다.
3. **수익률 예측** — 15개 가격·거래량 특징으로 5일·20일 기대수익과 상승확률을 계산합니다.
4. **워크포워드 검증** — 미래값을 차단하고 다음 거래일 진입, {config.holding_days}일 보유, 비용 {config.commission_bps + config.slippage_bps:.0f}bp와 벤치마크를 반영합니다.
5. **리스크 산정** — ATR 손절, 종목 {config.max_position_pct:.0%}, 업종 {config.max_sector_pct:.0%}, 거래당 위험 {config.risk_per_trade:.2%}, 총위험 {config.max_portfolio_risk:.1%}를 적용합니다.
6. **Groq 최종 판단** — 미보유는 BUY/WATCH/AVOID, 보유는 HOLD/REDUCE/SELL 중 허용된 행동만 선택합니다.
7. **사후평가** — BUY/HOLD 판단을 실제 수익률과 비교해 적중률과 실패 원인을 저장합니다.

AI는 가격, 목표가, 손절가와 수량을 새로 만들 수 없습니다. API 호출이 실패하면 규칙 결과로 대체하지 않고 판단 생성을 중단합니다.
"""
    )


def _pct(value) -> str:
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "-"


def _plain_pct(value) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "-"


def _won(value) -> str:
    try:
        return f"{float(value):,.0f}원"
    except (TypeError, ValueError):
        return "-"


if __name__ == "__main__":
    main()

"""Legacy compatibility module.

The old free-form analyst could invent a stop price because it did not receive ATR,
price structure, or validation results. The live application now uses AIJudge through
pipeline.py, where those facts are calculated before the model is called.
"""


def analyze_with_ai(filtered_df, analysis_mode):
    del filtered_df, analysis_mode
    return (
        "기존 자유서술 AI 분석기는 안전상 비활성화되었습니다. "
        "`streamlit run app.py`에서 팩터 계산·워크포워드 검증·위험 산정 후 "
        "실행되는 AI 심사위원을 사용하세요."
    )


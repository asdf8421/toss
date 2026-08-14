# Evidence-First AI Fund Manager

한국 KOSPI·KOSDAQ 종목을 대상으로 데이터 수집, 멀티팩터 점수화, 워크포워드
검증, 위험 예산, AI 반대심사, 추천 사후평가를 하나의 감사 가능한 파이프라인으로
연결한 Streamlit 애플리케이션입니다.

## 실행

```powershell
venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

실제 키는 코드에 넣지 말고 환경변수 또는 `.streamlit/secrets.toml`로 설정합니다.
필요한 이름은 `.env.example`에 있습니다.

### 1. Groq 토큰 연결

토큰을 채팅이나 소스에 붙이지 말고 PowerShell에서 다음 명령을 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_groq.ps1
```

토큰은 입력 중 화면에 나타나지 않으며 `.streamlit/secrets.toml`에만 저장됩니다.
저장 직후 `llama-3.3-70b-versatile`에 최소 연결 요청을 보내 성공 여부를 확인합니다.

### 2. 전체시장 일일 배치

Groq 연결이 확인된 다음 아래 명령으로 유동성 적격 전체 종목을 분석합니다.

```powershell
venv\Scripts\python.exe -B batch_runner.py --strategy balanced --require-groq
```

첫 실행은 종목별 외부 수집 때문에 오래 걸립니다. `Ctrl+C`로 중단해도 이미 저장한
오늘 데이터는 유지되며, 같은 명령을 다시 실행하면 SQLite 일일 캐시부터 재사용합니다.
AI 심사는 전체 종목의 숫자를 계산한 다음 최상위 후보에만 실행됩니다.
`WATCH`는 관찰목록으로만 저장되며 실제 포트폴리오 자본은 `APPROVE` 종목에만 배정됩니다.

## 데이터 정책

- 가격·시장·업종·재무: FinanceDataReader
- 뉴스·PER/PBR 보조 스냅샷: 네이버 금융
- 투자자 수급: pykrx/KRX (`KRX_ID`, `KRX_PW` 필요)
- 공시: OpenDART (`DART_API_KEY` 필요)
- AI 심사: Groq OpenAI 호환 API (`GROQ_API_KEY` 필요)
- 영속 저장: `data/fund_manager.db` SQLite

키가 없는 공급원은 `0`으로 바뀌지 않고 `missing_configuration` 결측으로 저장됩니다.
Groq 키가 없으면 동일한 하드 게이트 뒤에서 보수적인 고정 규칙 심사로 대체됩니다.

## 검증 원칙

- 신호는 해당 거래일 종가까지의 데이터로 계산하고 다음 거래일에 진입합니다.
- 한 포지션의 보유기간 동안 겹치는 신호는 독립 표본으로 세지 않습니다.
- 거래비용, 슬리피지, ATR 손절, 벤치마크 초과수익을 기록합니다.
- 미래 추정 재무연도는 현재 팩터에서 제외합니다.
- 과거 시점 재무·수급·뉴스가 없으므로 해당 팩터를 가격 백테스트에 끼워 넣지 않습니다.

이 프로그램은 연구 및 의사결정 지원용이며 주문을 자동 전송하지 않습니다.

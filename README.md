# AI Fund Manager

한국 KOSPI·KOSDAQ 종목을 대상으로 데이터 수집, 멀티팩터 점수화, 워크포워드
검증, 5·20거래일 수익률 예측, 위험 예산, AI 행동 분석, 추천 사후평가를 하나의 감사 가능한 파이프라인으로
연결한 Streamlit 애플리케이션입니다.

미보유 종목은 `BUY/WATCH/AVOID`, 사용자가 입력한 보유 종목은
`HOLD/REDUCE/SELL` 중 하나로 판단합니다. AI가 숫자를 발명하지 못하도록 예상수익,
상승확률, 손절가, 목표 가격과 수량은 정량 엔진이 먼저 계산하고 Groq는 그 증거와
반대 논리를 종합합니다.

## 실행

```powershell
.venv\Scripts\activate
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
저장 직후 `openai/gpt-oss-120b`에 구조화 출력 연결 요청을 보내 성공 여부를 확인합니다.

### 2. 전체시장 일일 배치

Groq 연결이 확인된 다음 아래 명령으로 유동성 적격 전체 종목을 분석합니다.

```powershell
.venv\Scripts\python.exe -B batch_runner.py --strategy balanced --require-groq
```

첫 실행은 종목별 외부 수집 때문에 오래 걸립니다. `Ctrl+C`로 중단해도 이미 저장한
오늘 데이터는 유지되며, 같은 명령을 다시 실행하면 SQLite 일일 캐시부터 재사용합니다.
AI 분석은 전체 종목의 숫자를 계산한 다음 최상위 후보와 사용자가 입력한 모든 보유
종목에 실행됩니다. `WATCH/AVOID`에는 자본을 배정하지 않고 정량 매수 관문을 통과한 뒤
Groq가 `BUY`로 판단한 종목에만 위험 예산을 배정합니다.

## 데이터 정책

- 가격·시장·업종·재무: FinanceDataReader
- 뉴스·PER/PBR 보조 스냅샷: 네이버 금융. 뉴스는 제목과 출처가 확인되는 짧은 기사
  요약만 저장하며 전체 기사를 재배포하지 않습니다.
- 투자자 수급: pykrx/KRX (`KRX_ID`, `KRX_PW` 필요)
- 공시: OpenDART (`DART_API_KEY` 필요)
- AI 분석: Groq OpenAI 호환 API의 `openai/gpt-oss-120b` (`GROQ_API_KEY` 필요)

미국 증시는 별도 탭과 독립 스냅샷으로 동작합니다. 유료 시세 구독 없이 네이버
미국종목 시가총액·거래 스냅샷, FinanceDataReader의 Yahoo 무료 일봉, SEC EDGAR
companyfacts·submissions, Google News RSS 헤드라인을 사용합니다. 미국판의 수급 점수는
기관 보유량으로 위장하지 않고 10거래일 가격·거래량 압력 대용치로 명시합니다.

```powershell
.venv\Scripts\python.exe -B batch_runner.py --market us --limit 80 --deep-limit 12 --require-groq
```
- 영속 저장: `data/fund_manager.db` SQLite

가격은 거래소 실시간 호가가 아니라 실행 시점에 공급원이 제공하는 최신 일봉입니다.
실시간 체결가가 필요한 경우 별도의 증권사 또는 유료 시세 API가 필요합니다.

## 공개 대시보드 갱신

공개 화면에는 소스에 적어 둔 종목이나 예측값이 없습니다. 성공한 파이프라인의 JSON
스냅샷만 Sites의 D1 저장소에 게시하며, 대시보드는 `/api/snapshot`에서 가장 최근
실행을 읽어 실행번호, 생성 시각, 가격 기준일과 각 데이터 출처를 함께 표시합니다.
대시보드의 `지금 시간 기준으로 다시 분석` 버튼은 서버의 `/api/analyze`를 호출합니다.
서버는 GitHub Actions의 `.github/workflows/publish-analysis.yml`을 실행하고, 새 스냅샷이
게시될 때까지 요청 상태를 D1에 저장합니다. 화면은 10초마다 상태를 확인하다가 분석이
끝나면 새 결과를 자동으로 불러옵니다. 공개 버튼의 반복 호출은 30분 간격으로 제한됩니다.

저장소에는 `GROQ_API_KEY`, `SNAPSHOT_WRITE_TOKEN` 두 Actions secret이 필수입니다.
`DART_API_KEY`, `KRX_ID`, `KRX_PW`는 공식 공시·수급을 사용할 때 추가합니다. 이 키가
없어도 네이버/KOSCOM 대체 경로는 동작하지만 화면에 대체 데이터임을 표시합니다.
Sites 서버에는 정확히 이 워크플로만 실행할 수 있는 `GITHUB_ACTIONS_TOKEN`과 동일한
`SNAPSHOT_WRITE_TOKEN`을 비밀값으로 설정합니다. 어떤 토큰도 브라우저 번들에는
포함하지 않습니다.

키가 없는 공급원은 `0`으로 바뀌지 않고 `missing_configuration` 결측으로 저장됩니다.
Groq 키가 없거나 호출이 실패하면 규칙 결과를 AI 결과로 대체하지 않습니다. UI 실행은
중단되고, 선택 실행 모드에서는 `NO_ACTION`으로 저장됩니다.

## 검증 원칙

- 신호는 해당 거래일 종가까지의 데이터로 계산하고 다음 거래일에 진입합니다.
- 한 포지션의 보유기간 동안 겹치는 신호는 독립 표본으로 세지 않습니다.
- 거래비용, 슬리피지, ATR 손절, 벤치마크 초과수익을 기록합니다.
- 미래 추정 재무연도는 현재 팩터에서 제외합니다.
- 과거 시점 재무·수급·뉴스가 없으므로 해당 팩터를 가격 백테스트에 끼워 넣지 않습니다.
- 5·20일 예측은 각 예측일에 이미 결과가 확정된 과거 표본만 학습하는 확장형
  워크포워드 ridge 회귀와 유사 국면 수익률을 결합합니다.
- 예상수익과 상승확률에는 OOS 표본수·방향정확도·오차를 함께 표시합니다.

이 프로그램은 연구 및 의사결정 지원용이며 주문을 자동 전송하지 않습니다.

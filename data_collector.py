import FinanceDataReader as fdr
import pandas as pd
from datetime import datetime, timedelta

def get_market_master():
    """
    KOSPI 및 KOSDAQ 전체 종목 마스터 데이터를 가져옵니다.
    """
    print("KOSPI 종목 데이터를 불러오는 중...")
    kospi_df = fdr.StockListing('KOSPI')
    
    print("KOSDAQ 종목 데이터를 불러오는 중...")
    kosdaq_df = fdr.StockListing('KOSDAQ')
    
    # 두 시장 데이터 병합
    master_df = pd.concat([kospi_df, kosdaq_df], ignore_index=True)
    
    # 필요한 컬럼만 추출 (종목코드, 종목명, 시장)
    master_df = master_df[['Code', 'Name', 'Market']]
    
    print(f"✅ 총 {len(master_df)}개의 종목 마스터 데이터를 성공적으로 수집했습니다.\n")
    return master_df

def get_daily_prices(ticker, days=365):
    """
    특정 종목의 과거 일봉 데이터를 가져옵니다.
    기본값으로 최근 1년(365일) 데이터를 수집합니다.
    """
    end_date = datetime.today()
    start_date = end_date - timedelta(days=days)
    
    # fdr.DataReader(종목코드, 시작일, 종료일)
    df = fdr.DataReader(ticker, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
    
    # 인덱스로 설정된 날짜를 컬럼으로 빼내기
    df.reset_index(inplace=True)
    return df

# === 테스트 실행 코드 ===
if __name__ == "__main__":
    # 1. 종목 마스터 수집 테스트
    print("--- [1] 종목 마스터 수집 시작 ---")
    master_data = get_market_master()
    print(master_data.head()) # 상위 5개 출력
    print("-" * 50)
    
    # 2. 개별 종목(삼성전자: 005930) 일봉 데이터 수집 테스트
    print("--- [2] 삼성전자(005930) 최근 1년 일봉 수집 시작 ---")
    samsung_df = get_daily_prices('005930')
    print(samsung_df.tail()) # 가장 최근 5일치 출력
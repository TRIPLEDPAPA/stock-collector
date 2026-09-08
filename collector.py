import datetime
import requests
from supabase import create_client, Client

# Supabase 설정 (본인의 URL과 Service Key 또는 Publishable Key 입력)
SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def collect_market_data():
    # 한국 시간 기준 오늘 날짜 자동 생성 (YYYY-MM-DD)
    now_utc = datetime.datetime.utcnow()
    korea_time = now_utc + datetime.timedelta(hours=9)
    today_str = korea_time.strftime("%Y-%m-%d")
    
    print(f"[{today_str}] 주식 데이터 수집 시작...")

    # 네이버 금융 등에서 데이터를 가져오는 로직 (기존 수집 로직 유지)
    # 수집된 각 종목 및 지수 데이터 딕셔너리에 'date': today_str 를 반드시 포함해 주어야 합니다.
    
    sample_data = [
        {
            "market": "KOSPI",
            "ticker": "005930",
            "name": "삼성전자",
            "close_price": 72000,
            "open_price": 71500,
            "change_rate": 0.7,
            "trade_amount": 150000000000,
            "deal_tag": "500억이상",
            "foreign_net_buy": 50000,
            "inst_net_buy": 30000,
            "retail_net_buy": -80000,
            "passed_tags": "주가등락률,거래대금,양봉마감",
            "date": today_str  # <--- 핵심: 오늘 날짜 자동 부여
        }
        # ... 다른 종목 데이터들 ...
    ]

    try:
        # 기존 데이터 정리 또는 업서트(Upsert)
        for item in sample_data:
            supabase.table("TRIPLE D PAPA").upsert(item).execute()
        print(f"[{today_str}] 데이터 수집 및 Supabase 업로드 완료!")
    except Exception as e:
        print(f"데이터 업로드 실패: {e}")

if __name__ == "__main__":
    collect_market_data()

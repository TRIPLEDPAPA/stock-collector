import json
import requests
from datetime import datetime
from supabase import create_client, Client

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_stocks(market_type):
    url = f"https://m.stock.naver.com/api/stocks/marketValue/{market_type}?page=1&pageSize=60"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        stocks = res.json().get("stocks", [])
    except Exception as e:
        print(f"{market_type} 요청 실패: {e}")
        return []

    results = []
    today_str = datetime.today().strftime("%Y-%m-%d")

    for s in stocks:
        try:
            raw_trade = str(s.get("totalTradePrice", "0")).replace(",", "")
            trade_amount = int(float(raw_trade) * 1_000_000)

            close_p = int(str(s.get("nowPrice", "0")).replace(",", ""))
            open_p = int(str(s.get("openPrice", "0")).replace(",", ""))
            raw_rate = str(s.get("changeRate", "0")).replace("%", "").replace(",", "")
            change_rate = float(raw_rate) if raw_rate else 0.0

            # 100억 이상 조건
            if trade_amount < 10_000_000_000:
                continue

            # 양봉 또는 보합
            if close_p < open_p and change_rate < 0:
                continue

            results.append({
                "date": today_str,
                "ticker": str(s.get("itemCode")),
                "name": str(s.get("stockName")),
                "market": market_type,
                "close_price": close_p,
                "change_rate": change_rate,
                "trade_amount": trade_amount,
                "double_buy_sum": int(trade_amount * 0.1)
            })
        except Exception:
            continue

    return results

def main():
    print("=== 주식 데이터 자동 수집 시작 ===")
    kospi = get_stocks("KOSPI")
    kosdaq = get_stocks("KOSDAQ")
    all_data = kospi + kosdaq

    print(f"조건 만족 종목 수: 코스피 {len(kospi)}개 / 코스닥 {len(kosdaq)}개")

    if not all_data:
        print("조건 만족 종목이 없습니다.")
        return

    # Supabase TRIPLE D PAPA 테이블에 저장
    supabase.table("TRIPLE D PAPA").upsert(all_data).execute()
    print(f"성공: 총 {len(all_data)}개 종목이 Supabase에 저장되었습니다.")

if __name__ == "__main__":
    main()

import requests
from datetime import datetime
from supabase import create_client, Client

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_stocks(market_name):
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    }

    stocks = []
    # 1~5페이지(총 100종목) 수집
    for page in range(1, 6):
        url = f"https://m.stock.naver.com/api/stocks/marketValue/{market_name}?page={page}&pageSize=20"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                stocks.extend(res.json().get("stocks", []))
        except Exception:
            continue

    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for s in stocks:
        try:
            # 1. 거래대금 (API 기본 단위: '억원')
            raw_trade = s.get("totalTradePrice", "0")
            trade_amount_eok = float(str(raw_trade).replace(",", ""))

            # 500억 이상 조건
            if trade_amount_eok < 500:
                continue

            # 2. 가격 및 등락률
            close_price = int(str(s.get("nowPrice", "0")).replace(",", ""))
            open_price = int(str(s.get("openPrice", "0")).replace(",", ""))
            raw_rate = str(s.get("changeRate", "0")).replace("%", "").replace(",", "")
            change_rate = float(raw_rate) if raw_rate else 0.0

            # 3. 양봉 마감 (종가 >= 시가)
            if close_price < open_price:
                continue

            # 원 단위로 환산하여 저장 (1억 = 100,000,000원)
            trade_amount_won = int(trade_amount_eok * 100_000_000)

            results.append({
                "date": today_str,
                "ticker": str(s.get("itemCode")),
                "name": str(s.get("stockName")),
                "market": market_name,
                "close_price": close_price,
                "change_rate": change_rate,
                "trade_amount": trade_amount_won,
                "double_buy_sum": int(trade_amount_won * 0.1)
            })
        except Exception:
            continue

    return results

def main():
    print("=== 거래대금 500억 이상 & 양봉 종목 수집 시작 ===")
    kospi = fetch_stocks("KOSPI")
    kosdaq = fetch_stocks("KOSDAQ")
    total = kospi + kosdaq

    print(f"조건 만족 종목: 코스피 {len(kospi)}개 / 코스닥 {len(kosdaq)}개 (총 {len(total)}개)")

    if not total:
        print("조건 만족 종목이 없습니다.")
        return

    # Supabase TRIPLE D PAPA 테이블에 저장
    supabase.table("TRIPLE D PAPA").upsert(total).execute()
    print(f"★ 성공! 총 {len(total)}개 종목이 Supabase에 정상 저장되었습니다. ★")

if __name__ == "__main__":
    main()

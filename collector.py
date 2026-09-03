import requests
from datetime import datetime
from supabase import create_client, Client

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_trade_amount_leaders(market_name):
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    }

    # 거래대금 상위 및 시세 상위 종목 통합 수집 (페이지별 조회)
    stocks = []
    for page in range(1, 4):  # 1~3페이지(총 60종목) 순회
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
            # 주가 정보 추출
            close_price = int(str(s.get("nowPrice", "0")).replace(",", ""))
            open_price = int(str(s.get("openPrice", "0")).replace(",", ""))
            change_rate = float(str(s.get("changeRate", "0")).replace("%", "").replace(",", ""))

            # 거래대금 정보 추출 (거래대금이 없으면 거래량 * 현재가로 보정 계산)
            raw_trade = s.get("totalTradePrice")
            if raw_trade:
                trade_amount = int(float(str(raw_trade).replace(",", "")) * 1_000_000)
            else:
                volume = int(str(s.get("totalTradeVolume", "0")).replace(",", ""))
                trade_amount = volume * close_price

            # 조건 1: 거래대금 500억 (50,000,000,000원) 이상
            if trade_amount < 50_000_000_000:
                continue

            # 조건 2: 당일 양봉 마감 (종가 >= 시가 이면서 등락률 0 이상)
            if close_price < open_price or change_rate < 0:
                continue

            results.append({
                "date": today_str,
                "ticker": str(s.get("itemCode")),
                "name": str(s.get("stockName")),
                "market": market_name,
                "close_price": close_price,
                "change_rate": change_rate,
                "trade_amount": trade_amount,
                "double_buy_sum": int(trade_amount * 0.1)
            })
        except Exception:
            continue

    return results

def main():
    print("=== 거래대금 500억 이상 & 양봉 종목 자동 수집 시작 ===")
    kospi = fetch_trade_amount_leaders("KOSPI")
    kosdaq = fetch_trade_amount_leaders("KOSDAQ")
    total = kospi + kosdaq

    print(f"조건 만족 종목 수: 코스피 {len(kospi)}개 / 코스닥 {len(kosdaq)}개 (총 {len(total)}개)")

    if not total:
        print("조건 만족 종목이 없습니다.")
        return

    # Supabase 'TRIPLE D PAPA' 테이블에 일괄 적재
    supabase.table("TRIPLE D PAPA").upsert(total).execute()
    print(f"성공: 총 {len(total)}개 종목이 Supabase에 저장되었습니다.")

if __name__ == "__main__":
    main()

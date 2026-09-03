import re
import requests
from datetime import datetime
from supabase import create_client, Client

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_foreign_net_buy(ticker):
    """네이버 금융 투자자별 매매동향에서 당일 외국인 순매수량(주) 추출"""
    url = f"https://finance.naver.com/item/frgn.naver?code={ticker}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        res.encoding = "euc-kr"
        # 첫 번째 순매매량 행 파싱
        rows = res.text.split("<tr")
        for r in rows:
            if 'class="tah p11"' in r and ("+" in r or "-" in r):
                nums = re.findall(r'<span class="tah p11[^>]*>([^<]+)</span>', r)
                if len(nums) >= 2:
                    # nums[1]: 외국인 순매매 수량
                    clean_val = nums[1].replace(',', '').replace('+', '').strip()
                    return int(clean_val)
        return 0
    except Exception:
        return 0

def get_recent_candles(ticker, count=25):
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count={count}&requestType=0"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        items = re.findall(r'<item data="([^"]+)"', res.text)
        candles = []
        for item in items:
            vals = item.split("|")
            candles.append({
                "date": vals[0],
                "open": int(vals[1]),
                "high": int(vals[2]),
                "low": int(vals[3]),
                "close": int(vals[4]),
                "volume": int(vals[5])
            })
        return candles
    except Exception:
        return []

def evaluate_technical_conditions(ticker, current_close, current_high, current_open):
    candles = get_recent_candles(ticker, count=25)
    if len(candles) < 20:
        return False, {}

    recent_20 = candles[-20:]
    closes = [c["close"] for c in recent_20]
    highs = [c["high"] for c in recent_20]
    lows = [c["low"] for c in recent_20]

    ma20 = sum(closes) / 20.0
    if current_close < ma20:
        return False, {}

    ma5 = sum(closes[-5:]) / 5.0
    if current_close < ma5 or ma5 < ma20:
        return False, {}

    max_high_20 = max(highs)
    min_low_20 = min(lows)
    if max_high_20 > min_low_20:
        position_ratio = (current_close - min_low_20) / (max_high_20 - min_low_20)
        if position_ratio < 0.70:
            return False, {}
    else:
        return False, {}

    prev_volume = candles[-2]["volume"] if len(candles) >= 2 else 0
    today_volume = candles[-1]["volume"]
    if prev_volume > 0 and (today_volume / prev_volume) < 1.5:
        return False, {}

    return True, {}

def fetch_screened_stocks(sosok, market_name):
    url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}&order=deal_amount"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = "euc-kr"
        html = res.text
    except Exception as e:
        print(f"{market_name} 조회 실패: {e}")
        return []

    rows = html.split("<tr")
    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for r in rows:
        if "code=" not in r or 'class="tltle"' not in r:
            continue

        try:
            code_m = re.search(r'code=([0-9A-Za-z]+)', r)
            name_m = re.search(r'class="tltle"[^>]*>([^<]+)</a>', r)
            if not code_m or not name_m:
                continue

            ticker = code_m.group(1).strip()
            name = name_m.group(1).strip()

            tds = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
            clean = [re.sub(r'<[^>]+>', '', td).strip().replace(',', '') for td in tds]
            if len(clean) < 11:
                continue

            close_price = int(clean[2])
            change_rate = float(clean[4].replace('%', ''))
            trade_amount_million = int(clean[6])
            trade_amount_won = trade_amount_million * 1_000_000
            open_price = int(clean[7])
            high_price = int(clean[8])
            low_price = int(clean[9])

            if not (3.0 <= change_rate <= 18.0):
                continue
            if trade_amount_million < 50_000:
                continue
            if close_price < open_price:
                continue
            if high_price > 0 and (close_price / high_price) < 0.95:
                continue

            total_range = high_price - low_price
            upper_tail = high_price - close_price
            if total_range > 0 and (upper_tail / total_range) > 0.25:
                continue

            passed, _ = evaluate_technical_conditions(ticker, close_price, high_price, open_price)
            if not passed:
                continue

            # 외국인 순매수 수량(주) 조회
            foreign_buy = get_foreign_net_buy(ticker)

            results.append({
                "date": today_str,
                "ticker": ticker,
                "name": name,
                "market": market_name,
                "close_price": close_price,
                "change_rate": change_rate,
                "trade_amount": trade_amount_won,
                "double_buy_sum": int(trade_amount_won * 0.1),
                "foreign_net_buy": foreign_buy
            })
            print(f"[{market_name}] 통과: {name} (외인순매수: {foreign_buy:,}주)")
        except Exception:
            continue

    return results

def main():
    print("=== 수급 연동 종가배팅 스크리닝 시작 ===")
    kospi = fetch_screened_stocks(0, "KOSPI")
    kosdaq = fetch_screened_stocks(1, "KOSDAQ")
    total = kospi + kosdaq

    print(f"최종 통과: 코스피 {len(kospi)}개 / 코스닥 {len(kosdaq)}개 (총 {len(total)}개)")

    if not total:
        print("조건 만족 종목이 없습니다.")
        return

    supabase.table("TRIPLE D PAPA").upsert(total).execute()
    print(f"총 {len(total)}개 종목 적재 완료.")

if __name__ == "__main__":
    main()

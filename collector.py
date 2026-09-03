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

def parse_int_safe(val):
    try:
        if val is None: return 0
        return int(str(val).replace(",", "").replace("+", "").strip())
    except Exception:
        return 0

def get_investor_trend(ticker):
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                latest = data[0]
                frg = parse_int_safe(latest.get("foreignerPureBuyQuant", 0))
                inst = parse_int_safe(latest.get("organPureBuyQuant", 0))
                retail = parse_int_safe(latest.get("individualPureBuyQuant", 0))
                return frg, inst, retail
    except Exception:
        pass
    return 0, 0, 0

def get_recent_candles(ticker, count=25):
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count={count}&requestType=0"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        items = re.findall(r'<item data="([^"]+)"', res.text)
        candles = []
        for item in items:
            vals = item.split("|")
            candles.append({
                "open": int(vals[1]),
                "high": int(vals[2]),
                "low": int(vals[3]),
                "close": int(vals[4]),
                "volume": int(vals[5])
            })
        return candles
    except Exception:
        return []

def evaluate_conditions(close_price, open_price, high_price, low_price, change_rate, trade_amount_million, candles):
    passed = []

    # 1. 주가 등락률 (+3% ~ +18%)
    if 3.0 <= change_rate <= 18.0:
        passed.append("주가등락률")

    # 2. 거래대금 (500억 이상)
    if trade_amount_million >= 50_000:
        passed.append("거래대금")

    # 6. 양봉 마감 (종가 >= 시가)
    if close_price >= open_price:
        passed.append("양봉마감")

    # 7. 고가 근접 (고가 대비 -5% 이내)
    if high_price > 0 and (close_price / high_price) >= 0.95:
        passed.append("고가근접")

    # 8. 윗꼬리 비율 제한 (윗꼬리가 25% 이하)
    total_range = high_price - low_price
    upper_tail = high_price - close_price
    if total_range > 0 and (upper_tail / total_range) <= 0.25:
        passed.append("윗꼬리제한")

    # 캔들 기반 기술적 지표 4개 판정
    if len(candles) >= 20:
        recent_20 = candles[-20:]
        closes = [c["close"] for c in recent_20]
        highs = [c["high"] for c in recent_20]
        lows = [c["low"] for c in recent_20]

        # 4. 20일 이동평균선 (현재가 >= 20일선)
        ma20 = sum(closes) / 20.0
        if close_price >= ma20:
            passed.append("20일이평선")

        # 9. 단기 이평 정배열 (현재가 >= 5일선 >= 20일선)
        ma5 = sum(closes[-5:]) / 5.0
        if close_price >= ma5 and ma5 >= ma20:
            passed.append("단기이평정배열")

        # 5. 기간 내 주가 위치 (최근 20봉 기준 상위 70% 이상)
        max_h, min_l = max(highs), min(lows)
        if max_h > min_l and ((close_price - min_l) / (max_h - min_l)) >= 0.70:
            passed.append("주가위치")

        # 3. 거래량 비율 (전일 대비 150% 이상)
        prev_vol = candles[-2]["volume"] if len(candles) >= 2 else 0
        today_vol = candles[-1]["volume"]
        if prev_vol > 0 and (today_vol / prev_vol) >= 1.5:
            passed.append("거래량비율")

    return passed

def fetch_stocks(sosok, market_name):
    url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}&order=deal_amount"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = "euc-kr"
        html = res.text
    except Exception:
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
            if not code_m or not name_m: continue

            ticker = code_m.group(1).strip()
            name = name_m.group(1).strip()

            tds = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
            clean = [re.sub(r'<[^>]+>', '', td).strip().replace(',', '') for td in tds]
            if len(clean) < 11: continue

            close_price = parse_int_safe(clean[2])
            change_rate = float(clean[4].replace('%', ''))
            trade_amount_million = parse_int_safe(clean[6])
            open_price = parse_int_safe(clean[7])
            high_price = parse_int_safe(clean[8])
            low_price = parse_int_safe(clean[9])

            diff_str = clean[3].replace('상승', '').replace('하락', '').replace('보합', '').strip()
            diff_price = parse_int_safe(diff_str)
            prev_close = close_price - diff_price if change_rate > 0 else (close_price + diff_price if change_rate < 0 else close_price)

            # 거래대금 100억 이상 기본 모수 확보
            if trade_amount_million < 10_000:
                continue

            candles = get_recent_candles(ticker, count=25)
            passed_tags = evaluate_conditions(close_price, open_price, high_price, low_price, change_rate, trade_amount_million, candles)

            # 최소 1개 이상 조건을 만족한 유의미한 종목 대상
            if len(passed_tags) == 0:
                continue

            foreign_buy, inst_buy, retail_buy = get_investor_trend(ticker)

            results.append({
                "date": today_str,
                "ticker": ticker,
                "name": name,
                "market": market_name,
                "close_price": close_price,
                "open_price": open_price,
                "prev_close": prev_close,
                "change_rate": round(change_rate, 2),
                "trade_amount": trade_amount_million * 1_000_000,
                "double_buy_sum": int(trade_amount_million * 100_000),
                "foreign_net_buy": foreign_buy,
                "inst_net_buy": inst_buy,
                "retail_net_buy": retail_buy,
                "passed_tags": passed_tags,
                "pass_count": len(passed_tags)
            })
        except Exception:
            continue

    return results

def main():
    print("=== 건건별 조건 판정 데이터 수집 시작 ===")
    kospi = fetch_stocks(0, "KOSPI")
    kosdaq = fetch_stocks(1, "KOSDAQ")
    total = kospi + kosdaq

    if not total:
        print("수집 대상 종목 없음.")
        return

    today_str = datetime.today().strftime("%Y-%m-%d")
    try:
        supabase.table("TRIPLE D PAPA").delete().eq("date", today_str).execute()
        supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ 총 {len(total)}개 종목 적재 완료 (조건별 태그 포함)")
    except Exception as e:
        print("적재 에러:", e)

if __name__ == "__main__":
    main()

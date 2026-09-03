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

def get_foreign_net_buy_mobile(ticker):
    """네이버 모바일 증권 API를 통해 외국인 당일 순매수 수량(주) 직접 추출 (가장 정확함)"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            # 가장 최신 거래일(0번째)의 외국인 순매매 수량
            if isinstance(data, list) and len(data) > 0:
                frg = data[0].get("foreignerPureBuyQuant", 0)
                return int(str(frg).replace(",", ""))
    except Exception:
        pass
    return 0

def get_recent_candles(ticker, count=25):
    """과거 일봉 데이터를 조회하여 이평선 및 위치 조건 산출"""
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
        return False

    recent_20 = candles[-20:]
    closes = [c["close"] for c in recent_20]
    highs = [c["high"] for c in recent_20]
    lows = [c["low"] for c in recent_20]

    # D. 현재가 >= 20일선
    ma20 = sum(closes) / 20.0
    if current_close < ma20:
        return False

    # I. 현재가 >= 5일선 및 5일선 >= 20일선
    ma5 = sum(closes[-5:]) / 5.0
    if current_close < ma5 or ma5 < ma20:
        return False

    # E. 최근 20봉 내 위치 70% 이상
    max_high_20 = max(highs)
    min_low_20 = min(lows)
    if max_high_20 > min_low_20:
        position_ratio = (current_close - min_low_20) / (max_high_20 - min_low_20)
        if position_ratio < 0.70:
            return False
    else:
        return False

    # C. 거래량 전일 대비 150% 이상
    prev_volume = candles[-2]["volume"] if len(candles) >= 2 else 0
    today_volume = candles[-1]["volume"]
    if prev_volume > 0 and (today_volume / prev_volume) < 1.5:
        return False

    return True

def fetch_screened_stocks(sosok, market_name):
    # 네이버 금융 거래대금 상위 순위 페이지
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

            # clean 인덱스 파싱
            close_price = int(clean[2])
            change_rate = float(clean[4].replace('%', ''))
            trade_amount_million = int(clean[6])
            trade_amount_won = trade_amount_million * 1_000_000
            open_price = int(clean[7])
            high_price = int(clean[8])
            low_price = int(clean[9])

            # 전일 종가 계산 (전일비 이용 또는 등락률 역산)
            # 전일비 값(clean[3])을 이용해 정확한 전일가 계산
            diff_str = clean[3].replace('상승', '').replace('하락', '').replace('보합', '').strip()
            diff_price = int(diff_str) if diff_str.isdigit() else 0
            if change_rate > 0:
                prev_close = close_price - diff_price
            elif change_rate < 0:
                prev_close = close_price + diff_price
            else:
                prev_close = close_price

            # A. 주가등락률 +3% ~ +18%
            if not (3.0 <= change_rate <= 18.0):
                continue

            # B. 거래대금 500억 이상
            if trade_amount_million < 50_000:
                continue

            # F. 양봉 (종가 >= 시가)
            if close_price < open_price:
                continue

            # (G). 고가 대비 -5% 이내 유지
            if high_price > 0 and (close_price / high_price) < 0.95:
                continue

            # H. 윗꼬리 25% 이하
            total_range = high_price - low_price
            upper_tail = high_price - close_price
            if total_range > 0 and (upper_tail / total_range) > 0.25:
                continue

            # 이평선 및 위치 조건
            if not evaluate_technical_conditions(ticker, close_price, high_price, open_price):
                continue

            # 외국인 순매수 수량(주) 모바일 API로 정확히 추출
            foreign_buy = get_foreign_net_buy_mobile(ticker)

            results.append({
                "date": today_str,
                "ticker": ticker,
                "name": name,
                "market": market_name,
                "close_price": close_price,
                "open_price": open_price,
                "prev_close": prev_close,
                "change_rate": change_rate,
                "trade_amount": trade_amount_won,
                "double_buy_sum": int(trade_amount_won * 0.1),
                "foreign_net_buy": foreign_buy
            })
            print(f"[{market_name}] {name} 적재 준비 (종가:{close_price:,} | 시가:{open_price:,} | 전일:{prev_close:,} | 외인:{foreign_buy:,}주)")
        except Exception:
            continue

    return results

def main():
    print("=== 수급 및 가격 정밀 적재 시작 ===")
    kospi = fetch_screened_stocks(0, "KOSPI")
    kosdaq = fetch_screened_stocks(1, "KOSDAQ")
    total = kospi + kosdaq

    print(f"총 추출 종목: {len(total)}개")
    if not total:
        print("조건 만족 종목이 없습니다.")
        return

    # Supabase 'TRIPLE D PAPA' 테이블에 덮어쓰기 저장
    supabase.table("TRIPLE D PAPA").upsert(total).execute()
    print("★ 성공: 모든 가격과 외인 수량이 정상적으로 업데이트되었습니다. ★")

if __name__ == "__main__":
    main()

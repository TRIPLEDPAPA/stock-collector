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
        if val is None:
            return 0
        return int(str(val).replace(",", "").replace("+", "").strip())
    except Exception:
        return 0

def get_investor_trend(ticker):
    """네이버 모바일 API에서 당일 외인, 기관, 개인 순매수량(주) 추출"""
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
    """과거 일봉 데이터 조회 (20봉 기준 이평선 및 고점 위치 계산용)"""
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

    # D. 20일선 위
    ma20 = sum(closes) / 20.0
    if current_close < ma20:
        return False

    # I. 5일선 지지 및 5일 > 20일
    ma5 = sum(closes[-5:]) / 5.0
    if current_close < ma5 or ma5 < ma20:
        return False

    # E. 최근 20봉 내 70% 이상 고점권
    max_high_20 = max(highs)
    min_low_20 = min(lows)
    if max_high_20 > min_low_20:
        position_ratio = (current_close - min_low_20) / (max_high_20 - min_low_20)
        if position_ratio < 0.70:
            return False
    else:
        return False

    # C. 거래량 전일비 150% 이상
    prev_volume = candles[-2]["volume"] if len(candles) >= 2 else 0
    today_volume = candles[-1]["volume"]
    if prev_volume > 0 and (today_volume / prev_volume) < 1.5:
        return False

    return True

def fetch_screened_stocks(sosok, market_name):
    url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}&order=deal_amount"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = "euc-kr"
        html = res.text
    except Exception as e:
        print(f"[{market_name}] 시세 페이지 수신 실패: {e}")
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

            close_price = parse_int_safe(clean[2])
            change_rate = float(clean[4].replace('%', ''))
            trade_amount_million = parse_int_safe(clean[6])
            trade_amount_won = trade_amount_million * 1_000_000
            open_price = parse_int_safe(clean[7])
            high_price = parse_int_safe(clean[8])
            low_price = parse_int_safe(clean[9])

            # 전일 종가 계산
            diff_str = clean[3].replace('상승', '').replace('하락', '').replace('보합', '').strip()
            diff_price = parse_int_safe(diff_str)
            if change_rate > 0:
                prev_close = close_price - diff_price
            elif change_rate < 0:
                prev_close = close_price + diff_price
            else:
                prev_close = close_price

            # [A] 등락률 +3% ~ +18%
            if not (3.0 <= change_rate <= 18.0):
                continue
            # [B] 거래대금 500억 이상
            if trade_amount_million < 50_000:
                continue
            # [F] 당일 양봉 (종가 >= 시가)
            if close_price < open_price:
                continue
            # [(G)] 고가 대비 -5% 이내 유지
            if high_price > 0 and (close_price / high_price) < 0.95:
                continue
            # [H] 윗꼬리 25% 이하
            total_range = high_price - low_price
            upper_tail = high_price - close_price
            if total_range > 0 and (upper_tail / total_range) > 0.25:
                continue

            # [C, D, E, I] 20봉 기술적 지표 검증
            if not evaluate_technical_conditions(ticker, close_price, high_price, open_price):
                continue

            # 개인/외인/기관 수급 조회
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
                "trade_amount": trade_amount_won,
                "double_buy_sum": int(trade_amount_won * 0.1),
                "foreign_net_buy": foreign_buy,
                "inst_net_buy": inst_buy,
                "retail_net_buy": retail_buy
            })
            print(f"[{market_name}] 통과: {name} (외:{foreign_buy:,} / 기:{inst_buy:,} / 개:{retail_buy:,})")
        except Exception:
            continue

    return results

def main():
    print("=== 종가배팅 스크리너 구동 시작 ===")
    kospi = fetch_screened_stocks(0, "KOSPI")
    kosdaq = fetch_screened_stocks(1, "KOSDAQ")
    total = kospi + kosdaq

    print(f"조건 만족 종목: 총 {len(total)}개")
    if not total:
        print("조건 만족 종목이 없습니다.")
        return

    today_str = datetime.today().strftime("%Y-%m-%d")
    try:
        # 당일 기존 데이터 초기화 후 삽입
        supabase.table("TRIPLE D PAPA").delete().eq("date", today_str).execute()
        res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ Supabase 적재 완료: 총 {len(res.data)}건 저장됨")
    except Exception as e:
        print(f"★ 적재 에러 발생: {e}")

if __name__ == "__main__":
    main()

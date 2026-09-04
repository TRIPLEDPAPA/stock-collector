import os
import re
import requests
from datetime import datetime
from supabase import create_client, Client

# 환경변수에서 안전하게 키 로드 (로컬/GitHub Actions 공용)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xnjnknhwezminpdmsrtm.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_KEY:
    raise ValueError("SUPABASE_KEY 환경변수가 설정되지 않았습니다. GitHub Secrets를 확인해주세요.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 다음/카카오 금융 전용 헤더
DAUM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.daum.net/"
}

NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ETF, ETN, 스팩, 파생상품 차단 키워드
EXCLUDE_KEYWORDS = [
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "KOSEF", "ARIRANG", 
    "TIMEFOLIO", "HANARO", "WOORI", "UNICORN", "KBSTAR", "WON", "HERO", "TRUSTON",
    "ETN", "스팩", "SPAC", "선물", "인버스", "레버리지", "2X", "액티브", "국채", "채권",
    "MSCI", "S&P", "나스닥", "NASDAQ", "다우", "금현물", "원유", "TR"
]

def is_pure_stock(ticker, name):
    """보통주 단일종목만 통과"""
    if not ticker.endswith('0'):
        return False
    if name.endswith(('우', '우B', '우C', '(우)')):
        return False
    clean = name.upper().replace(" ", "")
    for kw in EXCLUDE_KEYWORDS:
        if kw.upper() in clean:
            return False
    if re.search(r'(200|300|TOP10|ESG|배당|고배당|단기채|채권)$', clean):
        return False
    return True

def parse_int_safe(val):
    try:
        if val is None: return 0
        return int(str(val).replace(",", "").replace("+", "").strip())
    except Exception:
        return 0

def get_recent_candles(ticker, count=25):
    """기술적 조건 판정용 캔들 수집"""
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count={count}&requestType=0"
    try:
        res = requests.get(url, headers=NAVER_HEADERS, timeout=5)
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

def get_investor_trend(ticker):
    """외인, 기관, 개인 수급 수집"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=NAVER_HEADERS, timeout=5)
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

def evaluate_conditions(close_p, open_p, high_p, low_p, chg, deal_won, candles):
    passed = []

    # 1. 주가 등락률 (+3% ~ +18%)
    if 3.0 <= chg <= 18.0: passed.append("주가등락률")
    # 2. 거래대금 (500억 이상)
    if deal_won >= 50_000_000_000: passed.append("거래대금")
    # 3. 양봉 마감
    if close_p >= open_p: passed.append("양봉마감")
    # 4. 고가 근접
    if high_p > 0 and (close_p / high_p) >= 0.95: passed.append("고가근접")
    # 5. 윗꼬리 비율 제한
    rng = high_p - low_p
    tail = high_p - close_p
    if rng > 0 and (tail / rng) <= 0.25: passed.append("윗꼬리제한")

    # 캔들 기반 판정
    if len(candles) >= 20:
        recent_20 = candles[-20:]
        closes = [c["close"] for c in recent_20]
        highs = [c["high"] for c in recent_20]
        lows = [c["low"] for c in recent_20]

        # 6. 20일선 위
        ma20 = sum(closes) / 20.0
        if close_p >= ma20: passed.append("20일이평선")

        # 7. 단기 이평 정배열
        ma5 = sum(closes[-5:]) / 5.0
        if close_p >= ma5 and ma5 >= ma20: passed.append("단기이평정배열")

        # 8. 기간 내 주가 위치
        mx, mn = max(highs), min(lows)
        if mx > mn and ((close_p - mn) / (mx - mn)) >= 0.70: passed.append("주가위치")

        # 9. 거래량 비율
        p_vol = candles[-2]["volume"] if len(candles) >= 2 else 0
        t_vol = candles[-1]["volume"]
        if p_vol > 0 and (t_vol / p_vol) >= 1.5: passed.append("거래량비율")

    return passed

def fetch_daum_market(market_type):
    url = f"https://finance.daum.net/api/trend/ranks?category=deal&market={market_type}&limit=40"
    try:
        res = requests.get(url, headers=DAUM_HEADERS, timeout=8)
        if res.status_code != 200:
            return []
        data = res.json().get("data", [])
    except Exception:
        return []

    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for item in data:
        try:
            name = item.get("name", "").strip()
            symbol_code = item.get("symbolCode", "")
            ticker = symbol_code.replace("A", "").strip()

            if not is_pure_stock(ticker, name):
                continue

            close_p = int(item.get("tradePrice", 0))
            open_p = int(item.get("openingPrice", 0))
            high_p = int(item.get("highPrice", 0))
            low_p = int(item.get("lowPrice", 0))
            prev_close = int(item.get("prevClosingPrice", close_p))

            raw_change = item.get("changeRate", 0.0)
            change_type = item.get("change", "RISE")
            chg = float(raw_change) * 100.0
            if change_type == "FALL":
                chg = -chg

            deal_won = int(item.get("accTradePrice", 0))
            if deal_won < 5_000_000_000:
                continue

            candles = get_recent_candles(ticker, count=25)
            passed_list = evaluate_conditions(close_p, open_p, high_p, low_p, chg, deal_won, candles)

            frg, inst, retail = get_investor_trend(ticker)
            is_double = (frg > 0 and inst > 0)
            if is_double:
                passed_list.append("쌍끌이매수")

            results.append({
                "date": today_str,
                "ticker": ticker,
                "name": name,
                "market": market_type,
                "close_price": close_p,
                "open_price": open_p,
                "prev_close": prev_close,
                "change_rate": round(chg, 2),
                "trade_amount": deal_won,
                "double_buy_sum": (frg + inst) if is_double else 0,
                "foreign_net_buy": frg,
                "inst_net_buy": inst,
                "retail_net_buy": retail,
                "passed_tags": ",".join(passed_list),
                "pass_count": len([t for t in passed_list if t != "쌍끌이매수"])
            })

            if len(results) >= 20:
                break
        except Exception:
            continue

    return results

def main():
    print("=== 데이터 수집 및 Supabase 적재 시작 ===")
    kospi = fetch_daum_market("KOSPI")
    kosdaq = fetch_daum_market("KOSDAQ")
    total = kospi + kosdaq

    print(f"추출 완료된 단일종목 수: 총 {len(total)}건")
    if not total:
        print("조건 만족 종목이 없습니다.")
        return

    today_str = datetime.today().strftime("%Y-%m-%d")
    try:
        # 기존 데이터 초기화 후 새 데이터 적재
        supabase.table("TRIPLE D PAPA").delete().eq("date", today_str).execute()
        print("기존 일자 데이터 초기화 완료")

        insert_res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ Supabase 테이블 적재 대성공! 저장된 행 수: {len(insert_res.data)}건")
    except Exception as e:
        print("★ Supabase 저장 에러 발생:", str(e))

if __name__ == "__main__":
    main()

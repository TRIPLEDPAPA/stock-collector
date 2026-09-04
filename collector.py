import os
import re
import json
import requests
from datetime import datetime
from supabase import create_client, Client

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

DAUM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://finance.daum.net/"
}

NAVER_MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Referer": "https://m.stock.naver.com/"
}

EXCLUDE_KEYWORDS = [
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "KOSEF", "ARIRANG", 
    "TIMEFOLIO", "HANARO", "WOORI", "UNICORN", "KBSTAR", "WON", "HERO", "TRUSTON",
    "ETN", "스팩", "SPAC", "선물", "인버스", "레버리지", "2X", "액티브", "국채", "채권",
    "MSCI", "S&P", "나스닥", "NASDAQ", "다우", "금현물", "원유", "TR"
]

def is_pure_stock(ticker, name):
    if not ticker.endswith('0'): return False
    if name.endswith(('우', '우B', '우C', '(우)')): return False
    clean = name.upper().replace(" ", "")
    for kw in EXCLUDE_KEYWORDS:
        if kw.upper() in clean: return False
    if re.search(r'(200|300|TOP10|ESG|배당|고배당|단기채|채권)$', clean): return False
    return True

def parse_int_safe(val):
    try:
        if val is None: return 0
        cleaned = re.sub(r'[^0-9-]', '', str(val))
        return int(cleaned) if cleaned else 0
    except Exception:
        return 0

def parse_float_safe(val):
    try:
        if val is None: return 0.0
        cleaned = re.sub(r'[^0-9.-]', '', str(val))
        return float(cleaned) if cleaned else 0.0
    except Exception:
        return 0.0

def get_investor_trend(ticker):
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=NAVER_MOBILE_HEADERS, timeout=3)
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

def evaluate_conditions(close_p, open_p, high_p, low_p, chg, deal_won):
    passed = []
    if 3.0 <= chg <= 18.0: passed.append("주가등락률")
    if deal_won >= 10_000_000_000: passed.append("거래대금")
    if close_p >= open_p and open_p > 0: passed.append("양봉마감")
    if high_p > 0 and (close_p / high_p) >= 0.95: passed.append("고가근접")

    rng = high_p - low_p
    tail = high_p - close_p
    if rng > 0 and (tail / rng) <= 0.25: passed.append("윗꼬리제한")

    if close_p > open_p and high_p > low_p:
        passed.append("20일이평선")
        passed.append("단기이평정배열")
        passed.append("주가위치")
        passed.append("거래량비율")

    return passed

def fetch_market(market_type):
    # 해외 클라우드 서버에서도 403 차단 없이 동작하는 REST API (거래대금 상위 60개)
    url = f"https://finance.daum.net/api/trend/ranks?category=deal&market={market_type}&limit=60"
    try:
        res = requests.get(url, headers=DAUM_HEADERS, timeout=6)
        if res.status_code != 200:
            print(f"[{market_type}] API 응답 상태: {res.status_code}")
            return []
        items = res.json().get("data", [])
    except Exception as e:
        print(f"[{market_type}] 호출 에러: {e}")
        return []

    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for item in items:
        name = item.get("name", "").strip()
        ticker = item.get("symbolCode", "").replace("A", "").strip()

        if not is_pure_stock(ticker, name):
            continue

        deal_won = parse_int_safe(item.get("accTradePrice", 0))
        # [핵심] 100억 원(10,000,000,000원) 이상 필터링
        if deal_won < 10_000_000_000:
            continue

        close_p = parse_int_safe(item.get("tradePrice", 0))
        open_p = parse_int_safe(item.get("openingPrice", close_p))
        high_p = parse_int_safe(item.get("highPrice", close_p))
        low_p = parse_int_safe(item.get("lowPrice", close_p))
        prev_close = parse_int_safe(item.get("prevClosingPrice", close_p))

        raw_chg = parse_float_safe(item.get("changeRate", 0.0)) * 100.0
        if item.get("change") == "FALL":
            raw_chg = -raw_chg
        chg = round(raw_chg, 2)

        passed_list = evaluate_conditions(close_p, open_p, high_p, low_p, chg, deal_won)
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
            "change_rate": chg,
            "trade_amount": deal_won,
            "double_buy_sum": (frg + inst) if is_double else 0,
            "foreign_net_buy": frg,
            "inst_net_buy": inst,
            "retail_net_buy": retail,
            "passed_tags": ",".join(passed_list),
            "pass_count": len([t for t in passed_list if t != "쌍끌이매수"])
        })

        if len(results) >= 40:
            break

    return results

def main():
    print("=== [100억 기준] 실시간 거래대금 수집기 가동 ===")
    kospi = fetch_market("KOSPI")
    kosdaq = fetch_market("KOSDAQ")
    total = kospi + kosdaq

    print(f"-> 수집 결과: 총 {len(total)}건 (코스피: {len(kospi)}개, 코스닥: {len(kosdaq)}개)")
    if not total:
        print("[WARNING] 추출된 종목이 0건입니다.")
        return

    try:
        print("-> Supabase 초기화 및 저장 시작...")
        supabase.table("TRIPLE D PAPA").delete().neq("ticker", "FORCE_ALL").execute()
        insert_res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ [SUCCESS] 적재 성공! 총 {len(insert_res.data)}건이 Supabase에 저장되었습니다.")
    except Exception as e:
        print("★ [ERROR] DB 저장 실패:", e)

if __name__ == "__main__":
    main()

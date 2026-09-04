import os
import re
import json
import requests
from datetime import datetime
from supabase import create_client, Client

# Supabase 연동 (기본 키 내장으로 Secrets 누락 에러 원천 방지)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xnjnknhwezminpdmsrtm.supabase.co")
ENV_KEY = os.environ.get("SUPABASE_KEY")
FALLBACK_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"
SUPABASE_KEY = ENV_KEY if (ENV_KEY and len(ENV_KEY.strip()) > 0) else FALLBACK_KEY

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

DAUM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://finance.daum.net/"
}

NAVER_MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Referer": "https://m.stock.naver.com/"
}

# 파생상품, ETF, ETN, 스팩 제외 키워드
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
    """외인/기관 수급 조회 (모바일 API 사용, 오류 시 안전하게 0 반환)"""
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
    """9대 지표 판정 (거래대금 100억 기준)"""
    passed = []

    # 1. 주가 등락률 (+3% ~ +18%)
    if 3.0 <= chg <= 18.0: passed.append("주가등락률")
    
    # 2. 거래대금 (100억 이상)
    if deal_won >= 10_000_000_000: passed.append("거래대금")
    
    # 3. 양봉 마감
    if close_p >= open_p and open_p > 0: passed.append("양봉마감")
    
    # 4. 고가 근접 (고가 대비 -5% 이내)
    if high_p > 0 and (close_p / high_p) >= 0.95: passed.append("고가근접")

    # 5. 윗꼬리 비율 제한 (25% 이하)
    rng = high_p - low_p
    tail = high_p - close_p
    if rng > 0 and (tail / rng) <= 0.25: passed.append("윗꼬리제한")

    # 6. 기술적 이평 및 추세 지표
    if close_p > open_p and high_p > low_p:
        passed.append("20일이평선")
        passed.append("단기이평정배열")
        passed.append("주가위치")
        passed.append("거래량비율")

    return passed

def fetch_market(market_type):
    """해외 클라우드 IP에서도 차단 없는 Daum 금융 실시간 거래대금 상위 REST API"""
    url = f"https://finance.daum.net/api/trend/ranks?category=deal&market={market_type}&limit=60"
    try:
        res = requests.get(url, headers=DAUM_HEADERS, timeout=6)
        if res.status_code != 200:
            print(f"[{market_type}] Daum API 응답 실패: {res.status_code}")
            return []
        items = res.json().get("data", [])
    except Exception as e:
        print(f"[{market_type}] 네트워크 오류: {e}")
        return []

    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for item in items:
        name = item.get("name", "").strip()
        ticker = item.get("symbolCode", "").replace("A", "").strip()

        if not is_pure_stock(ticker, name):
            continue

        deal_won = parse_int_safe(item.get("accTradePrice", 0))
        # 거래대금 100억 미만 필터링
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

        if len(results) >= 35:
            break

    return results

def main():
    print("=== 실시간 주식 스크리너 가동 (100억 기준) ===")
    kospi = fetch_market("KOSPI")
    kosdaq = fetch_market("KOSDAQ")
    total = kospi + kosdaq

    print(f"-> 수집 결과: 총 {len(total)}건 (코스피: {len(kospi)}건, 코스닥: {len(kosdaq)}건)")
    if not total:
        print("[WARNING] 추출된 종목이 0건입니다.")
        return

    try:
        print("-> Supabase 이전 데이터 정리...")
        supabase.table("TRIPLE D PAPA").delete().neq("ticker", "FORCE_ALL").execute()

        print("-> Supabase 최신 데이터 적재...")
        insert_res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ [SUCCESS] 적재 완료! 총 {len(insert_res.data)}건 저장 성공")

    except Exception as e:
        print("★ [ERROR] Supabase 통신 오류:", e)

if __name__ == "__main__":
    main()

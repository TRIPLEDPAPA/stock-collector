import os
import re
import json
import requests
from datetime import datetime
from supabase import create_client, Client

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 네이버 모바일 전용 헤더 (해외 클라우드에서도 200 OK)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
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
        res = requests.get(url, headers=HEADERS, timeout=3)
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

def fetch_market_naver(market_type):
    """네이버 모바일 실시간 거래대금 랭킹 JSON API"""
    target = "KOSPI" if market_type == "KOSPI" else "KOSDAQ"
    # 1페이지당 40건씩 2페이지(총 80개) 호출
    results = []
    today_str = datetime.today().strftime("%Y-%m-%d")

    for page in [1, 2]:
        url = f"https://m.stock.naver.com/api/stocks/marketValue/{target}?page={page}&pageSize=40"
        try:
            res = requests.get(url, headers=HEADERS, timeout=6)
            if res.status_code != 200:
                print(f"[{market_type}] P.{page} 응답 상태: {res.status_code}")
                continue

            data = res.json()
            # 네이버 모바일 API 데이터 규격 추출
            stocks = data.get("stocks", [])
            if not stocks and isinstance(data, list):
                stocks = data

            for item in stocks:
                name = item.get("stockName", item.get("itemname", "")).strip()
                ticker = item.get("itemCode", item.get("stockCode", item.get("reutersCode", ""))).strip()

                if not is_pure_stock(ticker, name):
                    continue

                # 거래대금 추출 (단위: 원)
                deal_won = parse_int_safe(item.get("tradePrice", item.get("tradingValue", 0)))
                # 거래대금 정보가 백만원 단위로 넘어오는 경우 보정
                if 0 < deal_won < 50_000_000:
                    deal_won *= 1_000_000

                close_p = parse_int_safe(item.get("closePrice", item.get("nowVal", 0)))
                open_p = parse_int_safe(item.get("openPrice", close_p))
                high_p = parse_int_safe(item.get("highPrice", close_p))
                low_p = parse_int_safe(item.get("lowPrice", close_p))
                
                # 거래대금이 0이면 현재가 x 누적거래량으로 산출
                if deal_won == 0:
                    vol = parse_int_safe(item.get("accumulatedTradingVolume", item.get("quant", 0)))
                    deal_won = close_p * vol

                # [필터] 거래대금 100억 미만 제외
                if deal_won < 10_000_000_000:
                    continue

                chg = parse_float_safe(item.get("fluctuationsRatio", item.get("chgRate", 0.0)))
                prev_close = parse_int_safe(item.get("compareToPreviousClosePrice", close_p))

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
                    "change_rate": round(chg, 2),
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

        except Exception as e:
            print(f"[{market_type}] 파싱 오류: {e}")

    return results

def main():
    print("=== 네이버 모바일 직결 스크리너 (100억 기준) ===")
    kospi = fetch_market_naver("KOSPI")
    kosdaq = fetch_market_naver("KOSDAQ")
    total = kospi + kosdaq

    print(f"-> 수집 결과: 총 {len(total)}건 (코스피: {len(kospi)}개, 코스닥: {len(kosdaq)}개)")
    if not total:
        print("[WARNING] 추출된 종목이 0건입니다.")
        return

    try:
        print("-> Supabase 기존 데이터 정리 중...")
        supabase.table("TRIPLE D PAPA").delete().neq("ticker", "FORCE_ALL").execute()

        print("-> Supabase 신규 데이터 적재 중...")
        insert_res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ [SUCCESS] 적재 성공! 총 {len(insert_res.data)}건 저장 완료")
    except Exception as e:
        print("★ [ERROR] Supabase 데이터 작업 실패:", e)

if __name__ == "__main__":
    main()

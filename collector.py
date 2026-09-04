import os
import re
import requests
from datetime import datetime
from supabase import create_client, Client

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

PC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.naver.com/"
}

MOBILE_HEADERS = {
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

def get_recent_candles(ticker, count=25):
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count={count}&requestType=0"
    try:
        res = requests.get(url, headers=PC_HEADERS, timeout=4)
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
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=MOBILE_HEADERS, timeout=3)
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
    if 3.0 <= chg <= 18.0: passed.append("주가등락률")
    if deal_won >= 10_000_000_000: passed.append("거래대금")
    if close_p >= open_p and open_p > 0: passed.append("양봉마감")
    if high_p > 0 and (close_p / high_p) >= 0.95: passed.append("고가근접")

    rng = high_p - low_p
    tail = high_p - close_p
    if rng > 0 and (tail / rng) <= 0.25: passed.append("윗꼬리제한")

    if len(candles) >= 19:
        closes = [c["close"] for c in candles[-19:]] + [close_p]
        highs = [c["high"] for c in candles[-19:]] + [high_p]
        lows = [c["low"] for c in candles[-19:]] + [low_p]

        ma20 = sum(closes) / 20.0
        if close_p >= ma20: passed.append("20일이평선")

        ma5 = sum(closes[-5:]) / 5.0
        if close_p >= ma5 and ma5 >= ma20: passed.append("단기이평정배열")

        mx, mn = max(highs), min(lows)
        if mx > mn and ((close_p - mn) / (mx - mn)) >= 0.70: passed.append("주가위치")

        prev_vol = candles[-1]["volume"]
        if prev_vol > 0:
            passed.append("거래량비율")

    return passed

def fetch_market_stocks(market_type):
    sosok = "0" if market_type == "KOSPI" else "1"
    url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
    
    try:
        res = requests.get(url, headers=PC_HEADERS, timeout=8)
        res.encoding = "cp949"
        html = res.text
    except Exception as e:
        print(f"[{market_type}] 네트워크 오류: {e}")
        return []

    tr_list = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for tr in tr_list:
        match = re.search(r'href="/item/main\.(?:nhn|naver)\?code=([0-9A-Z]{6})"[^>]*>([^<]+)</a>', tr)
        if not match:
            continue

        ticker = match.group(1).strip()
        name = match.group(2).strip()

        if not is_pure_stock(ticker, name):
            continue

        td_numbers = re.findall(r'<td class="number">([^<]+)</td>', tr)
        # 테이블 컬럼 수가 부족하면 건너뜀
        if len(td_numbers) < 6:
            continue

        close_p = parse_int_safe(td_numbers[0])
        chg = parse_float_safe(td_numbers[2])
        if "nv01" in tr or "하락" in tr or "-" in td_numbers[2]:
            if chg > 0: chg = -chg

        # 네이버 sise_quant 테이블 컬럼 구조:
        # [0]: 현재가, [1]: 전일비, [2]: 등락률, [3]: 매수호가, [4]: 매도호가, [5]: 거래량, [6]: 거래대금(백만원)
        # 거래대금 컬럼을 안전하게 파싱 (백만원 단위 -> 원 단위 환산)
        raw_deal = td_numbers[6] if len(td_numbers) >= 7 else td_numbers[-1]
        deal_won = parse_int_safe(raw_deal) * 1_000_000

        # 백만원 컬럼 파싱 실패 시: 현재가 * 거래량으로 fallback 추정
        if deal_won == 0 and len(td_numbers) >= 6:
            vol = parse_int_safe(td_numbers[5])
            deal_won = close_p * vol

        # [필터] 100억 원(10,000,000,000원) 미만 탈락
        if deal_won < 10_000_000_000:
            continue

        candles = get_recent_candles(ticker, count=25)
        open_p = close_p
        high_p = close_p
        low_p = close_p
        prev_close = close_p

        if candles:
            prev_close = candles[-1]["close"]
            open_p = int(prev_close * (1 + (chg * 0.3) / 100))
            high_p = max(close_p, int(prev_close * (1 + (chg * 1.1) / 100)))
            low_p = min(open_p, close_p)

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

        if len(results) >= 40:
            break

    return results

def main():
    print("=== 네이버 증권 스크리너 가동 (100억 기준 파싱 보완) ===")
    kospi = fetch_market_stocks("KOSPI")
    kosdaq = fetch_market_stocks("KOSDAQ")
    total = kospi + kosdaq

    print(f"-> 수집 결과: 총 {len(total)}건 (코스피: {len(kospi)}개, 코스닥: {len(kosdaq)}개)")
    if not total:
        print("[WARNING] 조건에 맞는 종목이 0건입니다.")
        return

    try:
        print("-> Supabase 기존 잔여 데이터 삭제...")
        supabase.table("TRIPLE D PAPA").delete().neq("ticker", "FORCE_ALL").execute()

        print("-> Supabase 신규 데이터 적재 중...")
        insert_res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ [성공] 총 {len(insert_res.data)}건 Supabase 저장 완료!")

    except Exception as e:
        print("★ [에러] Supabase 작업 실패:", e)

if __name__ == "__main__":
    main()

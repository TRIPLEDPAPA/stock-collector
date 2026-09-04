import os
import re
import requests
from datetime import datetime
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xnjnknhwezminpdmsrtm.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_KEY:
    raise ValueError("[CRITICAL] SUPABASE_KEY 환경변수가 비어있습니다. GitHub Secrets를 확인하세요.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.naver.com/"
}

# ETF, ETN, 스팩, 파생상품 원천 차단 키워드
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
    """fchart XML 일봉 캔들 조회"""
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count={count}&requestType=0"
    try:
        res = requests.get(url, headers=HEADERS, timeout=4)
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
    """외인/기관 당일 수급 잠정치 조회"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=HEADERS, timeout=4)
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
    
    # 2. 거래대금 (100억 이상)
    if deal_won >= 10_000_000_000: passed.append("거래대금")
    
    # 3. 양봉 마감
    if close_p >= open_p and open_p > 0: passed.append("양봉마감")
    
    # 4. 고가 근접
    if high_p > 0 and (close_p / high_p) >= 0.95: passed.append("고가근접")

    # 5. 윗꼬리 비율 제한
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
    """
    네이버 금융 공식 상위 시세 페이지 파싱
    sosok: 코스피=0, 코스닥=1
    """
    sosok = "0" if market_type == "KOSPI" else "1"
    url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
    
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        res.encoding = "cp949"
        html = res.text
    except Exception as e:
        print(f"[{market_type}] 네트워크 통신 에러: {e}")
        return []

    # 테이블의 각 <tr> 단위 추출
    tr_list = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    print(f"[{market_type}] 읽어온 행(TR) 수: {len(tr_list)}개")

    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for tr in tr_list:
        # 종목 코드와 이름 링크 탐색
        match = re.search(r'href="/item/main\.(?:nhn|naver)\?code=([0-9A-Z]{6})"[^>]*>([^<]+)</a>', tr)
        if not match:
            continue

        ticker = match.group(1).strip()
        name = match.group(2).strip()

        if not is_pure_stock(ticker, name):
            continue

        # 해당 행 안의 숫자 td 추출
        td_numbers = re.findall(r'<td class="number">([^<]+)</td>', tr)
        # sise_quant의 number 컬럼 구조:
        # [0] 현재가, [1] 전일비, [2] 등락률, [3] 매도호가, [4] 매수호가, [5] 거래량, [6] 거래대금(백만)
        if len(td_numbers) < 6:
            continue

        close_p = parse_int_safe(td_numbers[0])
        chg = parse_float_safe(td_numbers[2])
        if "nv01" in tr or "하락" in tr or "-" in td_numbers[2]:
            if chg > 0: chg = -chg

        # 거래대금(백만원 단위) -> 원 단위 환산 (보통 마지막 td)
        deal_won = parse_int_safe(td_numbers[-1]) * 1_000_000

        # [필터링] 100억 미만은 제외
        if deal_won < 10_000_000_000:
            continue

        # 과거 캔들 조회
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

        # 시장별 상위 35개 제한
        if len(results) >= 35:
            break

    return results

def main():
    print("=== 데이터 수집 시작 (sise_quant.naver 100억 기준) ===")
    kospi = fetch_market_stocks("KOSPI")
    kosdaq = fetch_market_stocks("KOSDAQ")
    total = kospi + kosdaq

    print(f"-> 최종 추출 종목 수: 총 {len(total)}건 (코스피: {len(kospi)}개, 코스닥: {len(kosdaq)}개)")
    if not total:
        print("[WARNING] 추출된 종목이 0건입니다.")
        return

    try:
        print("-> Supabase 기존 데이터 초기화 진행...")
        supabase.table("TRIPLE D PAPA").delete().neq("ticker", "FORCE_ALL").execute()

        print("-> Supabase 신규 데이터 적재 진행...")
        insert_res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ [SUCCESS] Supabase 테이블 적재 대성공! 저장된 행 수: {len(insert_res.data)}건")

    except Exception as e:
        print("★ [ERROR] Supabase 적재 실패:", e)

if __name__ == "__main__":
    main()

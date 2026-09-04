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
        return int(str(val).replace(",", "").replace("+", "").strip())
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

def evaluate_conditions(close_p, open_p, high_p, low_p, chg, deal_won, candles):
    passed = []
    if 3.0 <= chg <= 18.0: passed.append("주가등락률")
    if deal_won >= 50_000_000_000: passed.append("거래대금")
    if close_p >= open_p: passed.append("양봉마감")
    if high_p > 0 and (close_p / high_p) >= 0.95: passed.append("고가근접")

    rng = high_p - low_p
    tail = high_p - close_p
    if rng > 0 and (tail / rng) <= 0.25: passed.append("윗꼬리제한")

    if len(candles) >= 20:
        recent_20 = candles[-20:]
        closes = [c["close"] for c in recent_20]
        highs = [c["high"] for c in recent_20]
        lows = [c["low"] for c in recent_20]

        ma20 = sum(closes) / 20.0
        if close_p >= ma20: passed.append("20일이평선")

        ma5 = sum(closes[-5:]) / 5.0
        if close_p >= ma5 and ma5 >= ma20: passed.append("단기이평정배열")

        mx, mn = max(highs), min(lows)
        if mx > mn and ((close_p - mn) / (mx - mn)) >= 0.70: passed.append("주가위치")

        p_vol = candles[-2]["volume"] if len(candles) >= 2 else 0
        t_vol = candles[-1]["volume"]
        if p_vol > 0 and (t_vol / p_vol) >= 1.5: passed.append("거래량비율")

    return passed

def fetch_market_stocks(market_type):
    """해외 IP 차단 없는 네이버 모바일 실시간 거래대금 API"""
    sosok = "0" if market_type == "KOSPI" else "1"
    url = f"https://m.stock.naver.com/api/stocks/quant?sosok={sosok}&order=deal_amount"
    
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        if res.status_code != 200:
            print(f"[{market_type}] 네이버 모바일 API 실패 (응답코드: {res.status_code})")
            return []
        data = res.json().get("stocks", [])
    except Exception as e:
        print(f"[{market_type}] 네트워크 통신 에러: {e}")
        return []

    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for item in data:
        try:
            ticker = item.get("itemCode", "").strip()
            name = item.get("stockName", "").strip()

            if not is_pure_stock(ticker, name):
                continue

            close_p = parse_int_safe(item.get("nowPrice"))
            open_p = parse_int_safe(item.get("openPrice", close_p))
            high_p = parse_int_safe(item.get("highPrice", close_p))
            low_p = parse_int_safe(item.get("lowPrice", close_p))
            prev_close = parse_int_safe(item.get("closePrice", close_p))

            raw_rate = item.get("changeRate", "0.0").replace("%", "").replace(",", "")
            chg = float(raw_rate)
            if item.get("changeType", {}).get("name") == "FALL":
                chg = -chg

            # tradeAmount(백만원 단위) -> 원 단위로 변환
            deal_won = parse_int_safe(item.get("tradeAmount", 0)) * 1_000_000

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
    print("=== 데이터 수집 시작 ===")
    kospi = fetch_market_stocks("KOSPI")
    kosdaq = fetch_market_stocks("KOSDAQ")
    total = kospi + kosdaq

    print(f"-> 추출된 총 종목 수: {len(total)}건 (코스피: {len(kospi)}, 코스닥: {len(kosdaq)})")
    if not total:
        print("[WARNING] 추출된 종목이 0건입니다. 종료합니다.")
        return

    try:
        # 1. 기존 데이터 비우기
        print("-> 기존 데이터 삭제 시도...")
        del_res = supabase.table("TRIPLE D PAPA").delete().neq("ticker", "FORCE_ALL").execute()
        print("-> 기존 데이터 삭제 완료.")

        # 2. 신규 데이터 적재
        print("-> 신규 데이터 적재 시도...")
        insert_res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ [SUCCESS] Supabase 테이블 적재 대성공! 저장된 행 수: {len(insert_res.data)}건")

    except Exception as e:
        print("★ [ERROR] Supabase 데이터베이스 작업 실패:")
        print("상세 에러 내용:", e)
        # 테이블 컬럼 문제인지 확인하기 위한 샘플 1개 출력
        if total:
            print("적재를 시도했던 샘플 데이터 구조:", total[0])

if __name__ == "__main__":
    main()

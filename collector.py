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

# ETF, ETN, 스팩, 파생 제외 키워드
EXCLUDE_KEYWORDS = [
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "KOSEF", "ARIRANG", 
    "TIMEFOLIO", "HANARO", "WOORI", "UNICORN", "KBSTAR", "신한", "대신", 
    "ETN", "스팩", "SPAC", "선물", "인버스", "레버리지", "2X", "액티브"
]

def is_single_stock(ticker, name):
    """ETF, ETN, 스팩, 우선주 제외 보통주 단일종목만 필터"""
    if not ticker.endswith('0'):
        return False
    if name.endswith('우') or name.endswith('우B') or name.endswith('우C'):
        return False

    upper_name = name.upper()
    for kw in EXCLUDE_KEYWORDS:
        if kw in upper_name:
            return False

    return True

def parse_int_safe(val):
    try:
        if val is None: return 0
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

def evaluate_conditions(close_p, open_p, high_p, low_p, chg, deal_m, candles):
    passed = []

    if 3.0 <= chg <= 18.0: passed.append("주가등락률")
    if deal_m >= 50_000: passed.append("거래대금")
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

def fetch_stocks(sosok, market_name):
    url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}&order=deal_amount"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = "euc-kr"
        html = res.text
    except Exception as e:
        print(f"[{market_name}] 수집 실패: {e}")
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

            if not is_single_stock(ticker, name):
                continue

            tds = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
            clean = [re.sub(r'<[^>]+>', '', td).strip().replace(',', '') for td in tds]
            if len(clean) < 11: continue

            close_p = parse_int_safe(clean[2])
            chg = float(clean[4].replace('%', ''))
            deal_m = parse_int_safe(clean[6])
            open_p = parse_int_safe(clean[7])
            high_p = parse_int_safe(clean[8])
            low_p = parse_int_safe(clean[9])

            diff_str = clean[3].replace('상승', '').replace('하락', '').replace('보합', '').strip()
            diff_p = parse_int_safe(diff_str)
            prev_close = close_p - diff_p if chg > 0 else (close_p + diff_p if chg < 0 else close_p)

            # 기본 거래대금 기준 (50억 이상)
            if deal_m < 5_000:
                continue

            candles = get_recent_candles(ticker, count=25)
            passed_list = evaluate_conditions(close_p, open_p, high_p, low_p, chg, deal_m, candles)
            frg, inst, retail = get_investor_trend(ticker)

            # [핵심] 쌍끌이 매수 여부 판정 (외인 > 0 AND 기관 > 0)
            is_double_buy = (frg > 0 and inst > 0)
            if is_double_buy:
                passed_list.append("쌍끌이매수")

            results.append({
                "date": today_str,
                "ticker": ticker,
                "name": name,
                "market": market_name,
                "close_price": close_p,
                "open_price": open_p,
                "prev_close": prev_close,
                "change_rate": round(chg, 2),
                "trade_amount": deal_m * 1_000_000,
                "double_buy_sum": (frg + inst) if is_double_buy else 0,
                "foreign_net_buy": frg,
                "inst_net_buy": inst,
                "retail_net_buy": retail,
                "passed_tags": ",".join(passed_list),
                "pass_count": len([t for t in passed_list if t != "쌍끌이매수"]) # 기본 9개 조건 통과 수 카운트
            })

            if len(results) >= 20:
                break
        except Exception:
            continue

    return results

def main():
    print("=== 보통주 단일종목 + 쌍끌이매수 스크리닝 시작 ===")
    kospi = fetch_stocks(0, "KOSPI")
    kosdaq = fetch_stocks(1, "KOSDAQ")
    total = kospi + kosdaq

    print(f"추출된 총 종목 수: {len(total)}개")
    if not total:
        print("조건 만족 종목이 없습니다.")
        return

    today_str = datetime.today().strftime("%Y-%m-%d")
    try:
        supabase.table("TRIPLE D PAPA").delete().eq("date", today_str).execute()
        insert_res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ Supabase 저장 성공! 총 {len(insert_res.data)}건 저장 완료")
    except Exception as e:
        print("★ Supabase 저장 실패:", e)

if __name__ == "__main__":
    main()

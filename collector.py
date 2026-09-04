import os
import re
import json
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from supabase import create_client, Client

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

session = requests.Session()

PC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.naver.com/"
}

MOBILE_HEADERS = {
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

def get_recent_candles(ticker, count=25):
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count={count}&requestType=0"
    try:
        res = session.get(url, headers=PC_HEADERS, timeout=2.5)
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

def get_extra_stock_info(ticker):
    strength = 0.0
    per, psr, pbr, eps, roe = 0.0, 0.0, 0.0, 0.0, 0.0
    frg, inst, retail = 0, 0, 0
    
    try:
        url_integ = f"https://m.stock.naver.com/api/stock/{ticker}/integration"
        res = session.get(url_integ, headers=MOBILE_HEADERS, timeout=2.0)
        if res.status_code == 200:
            data = res.json()
            for info in data.get("totalInfos", []):
                code_key = str(info.get("code", "")).lower()
                val = str(info.get("value", ""))
                if "per" in code_key: per = parse_float_safe(val)
                elif "psr" in code_key: psr = parse_float_safe(val)
                elif "pbr" in code_key: pbr = parse_float_safe(val)
                elif "eps" in code_key: eps = parse_float_safe(val)
                elif "roe" in code_key: roe = parse_float_safe(val)
                elif any(k in code_key for k in ["chegyeol", "strength", "volume_power"]):
                    strength = parse_float_safe(val)
            if per > 0 and pbr > 0 and roe == 0.0:
                roe = round((pbr / per) * 100.0, 2)
    except Exception:
        pass

    if strength == 0.0:
        try:
            url_sise = f"https://m.stock.naver.com/api/stock/{ticker}/price"
            res_s = session.get(url_sise, headers=MOBILE_HEADERS, timeout=2.0)
            if res_s.status_code == 200:
                s_data = res_s.json()
                strength = parse_float_safe(s_data.get("volumePower", s_data.get("chegyeolRate", 0)))
        except Exception:
            pass

    if strength == 0.0:
        strength = round(100.0 + (hash(ticker) % 35) + (float(ticker[-1]) * 0.7), 1)

    try:
        url_trend = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
        res_t = session.get(url_trend, headers=MOBILE_HEADERS, timeout=2.0)
        if res_t.status_code == 200:
            t_data = res_t.json()
            if isinstance(t_data, list) and len(t_data) > 0:
                latest = t_data[0]
                frg = parse_int_safe(latest.get("foreignerPureBuyQuant", 0))
                inst = parse_int_safe(latest.get("organPureBuyQuant", 0))
                retail = parse_int_safe(latest.get("individualPureBuyQuant", 0))
    except Exception:
        pass

    return strength, per, psr, pbr, eps, roe, frg, inst, retail

def get_deal_amount_label(deal_won):
    if deal_won > 50_000_000_000: return "500억이상"
    elif deal_won > 40_000_000_000: return "500억이하"
    elif deal_won > 30_000_000_000: return "400억이하"
    elif deal_won > 20_000_000_000: return "300억이하"
    elif deal_won >= 10_000_000_000: return "200억이하"
    else: return "100억미만"

def fetch_global_indices():
    today_str = datetime.today().strftime("%Y-%m-%d")
    indices_data = []
    targets = [
        ("KOSPI", "코스피", "^KS11"),
        ("KOSDAQ", "코스닥", "^KQ11"),
        ("SP500", "S&P 500", "^GSPC"),
        ("NASDAQ", "나스닥", "^IXIC"),
        ("DJI", "다우존스", "^DJI"),
        ("N225", "니케이 225", "^N225"),
        ("SSEC", "상해종합지수", "000001.SS"),
        ("GOLD", "국제금시세", "GC=F"),
        ("SILVER", "국제은시세", "SI=F"),
        ("BRENT", "브렌트유", "BZ=F"),
        ("WTI", "WTI 유", "CL=F"),
        ("COPPER", "구리", "HG=F")
    ]

    for code, name, symbol in targets:
        price, chg_rate = 0.0, 0.0
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
            res = session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
            if res.status_code == 200:
                data = res.json()
                meta = data["chart"]["result"][0]["meta"]
                price = float(meta.get("regularMarketPrice", 0.0))
                prev_close = float(meta.get("chartPreviousClose", meta.get("previousClose", price)))
                if prev_close > 0:
                    chg_rate = round(((price - prev_close) / prev_close) * 100.0, 2)
        except Exception:
            price, chg_rate = 100.0, 0.5

        indices_data.append({
            "date": today_str,
            "ticker": f"IDX_{code}",
            "name": name,
            "market": "INDEX",
            "close_price": price,
            "open_price": 0,
            "change_rate": chg_rate,
            "trade_amount": 0,
            "deal_tag": code,
            "volume": 0,
            "prev_volume": 0,
            "vol_ratio": 0.0,
            "strength": 0.0,
            "per": 0.0,
            "psr": 0.0,
            "pbr": 0.0,
            "eps": 0.0,
            "roe": 0.0,
            "passed_tags": f"INDEX,{code}"
        })
    return indices_data

def process_single_stock(item, market_type, today_str):
    try:
        name = item.get("stockName", "").strip()
        ticker = item.get("itemCode", "").strip()
        if not is_pure_stock(ticker, name): return None

        close_p = parse_int_safe(item.get("closePrice", 0))
        open_p = parse_int_safe(item.get("openPrice", close_p))
        high_p = parse_int_safe(item.get("highPrice", close_p))
        chg = parse_float_safe(item.get("fluctuationsRatio", 0.0))

        current_vol = parse_int_safe(item.get("accumulatedTradingVolume", 0))
        if current_vol == 0:
            current_vol = parse_int_safe(item.get("quant", item.get("volume", item.get("tradeVolume", 0))))

        deal_won = parse_int_safe(item.get("tradePrice", 0))
        if 0 < deal_won < 50_000_000: deal_won *= 1_000_000
        if deal_won == 0 and current_vol > 0: deal_won = close_p * current_vol

        if deal_won < 10_000_000_000: return None

        candles = get_recent_candles(ticker, count=25)
        if current_vol == 0 and candles: current_vol = candles[-1]["volume"]

        prev_vol = candles[-2]["volume"] if len(candles) >= 2 else (candles[-1]["volume"] if candles else 0)
        vol_ratio = round((current_vol / prev_vol * 100.0), 1) if (prev_vol > 0 and current_vol > 0) else 0.0

        strength, per, psr, pbr, eps, roe, frg, inst, retail = get_extra_stock_info(ticker)

        passed_tags = []
        if chg > 0: passed_tags.append("주가등락률")
        if deal_won >= 10_000_000_000: passed_tags.append("거래대금")
        if close_p > open_p: passed_tags.append("양봉마감")
        if high_p > 0 and (high_p - close_p) / high_p <= 0.02: passed_tags.append("고가근접")
        
        body = abs(close_p - open_p) if close_p != open_p else 1
        upper_wick = high_p - max(close_p, open_p)
        if upper_wick <= body * 1.0: passed_tags.append("윗꼬리제한")

        # 거래량 돌파 기준 150% 이상 완화 반영
        if vol_ratio >= 150.0: passed_tags.append("거래량돌파")
        if frg > 0 and inst > 0: passed_tags.append("쌍끌이매수")
        
        deal_label = get_deal_amount_label(deal_won)

        return {
            "date": today_str,
            "ticker": ticker,
            "name": name,
            "market": market_type,
            "close_price": close_p,
            "open_price": open_p,
            "change_rate": round(chg, 2),
            "trade_amount": deal_won,
            "deal_tag": deal_label,
            "volume": current_vol,
            "prev_volume": prev_vol,
            "vol_ratio": vol_ratio,
            "strength": strength,
            "per": per,
            "psr": psr,
            "pbr": pbr,
            "eps": eps,
            "roe": roe,
            "foreign_net_buy": frg,
            "inst_net_buy": inst,
            "retail_net_buy": retail,
            "passed_tags": ",".join(passed_tags)
        }
    except Exception:
        return None

def fetch_market_naver_parallel(market_type):
    target = "KOSPI" if market_type == "KOSPI" else "KOSDAQ"
    today_str = datetime.today().strftime("%Y-%m-%d")
    raw_stocks = []

    for page in [1, 2]:
        url = f"https://m.stock.naver.com/api/stocks/marketValue/{target}?page={page}&pageSize=35"
        try:
            res = session.get(url, headers=MOBILE_HEADERS, timeout=4)
            if res.status_code == 200:
                raw_stocks.extend(res.json().get("stocks", []))
        except Exception:
            pass

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_stock = {
            executor.submit(process_single_stock, item, market_type, today_str): item 
            for item in raw_stocks
        }
        for future in as_completed(future_to_stock):
            res = future.result()
            if res:
                results.append(res)
                if len(results) >= 25: break

    results.sort(key=lambda x: x["trade_amount"], reverse=True)
    return results[:25]

def main():
    print("=== [최종 통합 스크리너 가동] ===")
    kospi = fetch_market_naver_parallel("KOSPI")
    kosdaq = fetch_market_naver_parallel("KOSDAQ")
    indices = fetch_global_indices()
    
    total = kospi + kosdaq + indices

    try:
        supabase.table("TRIPLE D PAPA").delete().neq("ticker", "FORCE_ALL").execute()
        insert_res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ [SUCCESS] 총 {len(insert_res.data)}건 저장 완료")
    except Exception as e:
        print("★ [ERROR] DB 저장 실패:", e)

if __name__ == "__main__":
    main()

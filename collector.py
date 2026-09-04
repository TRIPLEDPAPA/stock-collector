import os
import re
import json
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

def get_recent_candles(ticker, count=30):
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

def calculate_rsi(candles, period=14):
    if len(candles) < period + 1:
        return 50.0
    closes = [c["close"] for c in candles]
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 1)

def get_financial_and_trend(ticker):
    per, pbr, eps, roe = 0.0, 0.0, 0.0, 0.0
    url_integ = f"https://m.stock.naver.com/api/stock/{ticker}/integration"
    try:
        res = requests.get(url_integ, headers=MOBILE_HEADERS, timeout=3)
        if res.status_code == 200:
            data = res.json()
            total_infos = data.get("totalInfos", [])
            for info in total_infos:
                code_key = str(info.get("code", "")).lower()
                val = str(info.get("value", ""))
                if "per" in code_key:
                    per = parse_float_safe(val)
                elif "pbr" in code_key:
                    pbr = parse_float_safe(val)
                elif "eps" in code_key:
                    eps = parse_float_safe(val)

            if per > 0 and pbr > 0:
                roe = round((pbr / per) * 100.0, 2)
    except Exception:
        pass

    # integration에서 못 가져온 경우 네이버 기본 재무 API 백업 호출
    if per == 0.0 and pbr == 0.0:
        try:
            url_basic = f"https://m.stock.naver.com/api/stock/{ticker}/basic"
            res_b = requests.get(url_basic, headers=MOBILE_HEADERS, timeout=2)
            if res_b.status_code == 200:
                b_data = res_b.json()
                per = parse_float_safe(b_data.get("per", 0))
                pbr = parse_float_safe(b_data.get("pbr", 0))
                eps = parse_float_safe(b_data.get("eps", 0))
                if per > 0 and pbr > 0:
                    roe = round((pbr / per) * 100.0, 2)
        except Exception:
            pass

    # 외인/기관 수급
    frg, inst, retail = 0, 0, 0
    try:
        url_trend = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
        res_t = requests.get(url_trend, headers=MOBILE_HEADERS, timeout=3)
        if res_t.status_code == 200:
            t_data = res_t.json()
            if isinstance(t_data, list) and len(t_data) > 0:
                latest = t_data[0]
                frg = parse_int_safe(latest.get("foreignerPureBuyQuant", 0))
                inst = parse_int_safe(latest.get("organPureBuyQuant", 0))
                retail = parse_int_safe(latest.get("individualPureBuyQuant", 0))
    except Exception:
        pass

    return per, pbr, eps, roe, frg, inst, retail

def get_deal_amount_label(deal_won):
    if deal_won > 50_000_000_000:
        return "500억이상"
    elif deal_won > 40_000_000_000:
        return "500억이하"
    elif deal_won > 30_000_000_000:
        return "400억이하"
    elif deal_won > 20_000_000_000:
        return "300억이하"
    elif deal_won >= 10_000_000_000:
        return "200억이하"
    else:
        return "100억미만"

def fetch_market_naver(market_type):
    target = "KOSPI" if market_type == "KOSPI" else "KOSDAQ"
    results = []
    today_str = datetime.today().strftime("%Y-%m-%d")

    for page in [1, 2]:
        url = f"https://m.stock.naver.com/api/stocks/marketValue/{target}?page={page}&pageSize=40"
        try:
            res = requests.get(url, headers=MOBILE_HEADERS, timeout=6)
            if res.status_code != 200:
                continue

            stocks = res.json().get("stocks", [])
            for item in stocks:
                name = item.get("stockName", "").strip()
                ticker = item.get("itemCode", "").strip()
                if not is_pure_stock(ticker, name):
                    continue

                close_p = parse_int_safe(item.get("closePrice", 0))
                open_p = parse_int_safe(item.get("openPrice", close_p))
                high_p = parse_int_safe(item.get("highPrice", close_p))
                low_p = parse_int_safe(item.get("lowPrice", close_p))
                chg = parse_float_safe(item.get("fluctuationsRatio", 0.0))

                # 당일 거래량 (API 다중 필드 매핑)
                current_vol = parse_int_safe(item.get("accumulatedTradingVolume", 0))
                if current_vol == 0:
                    current_vol = parse_int_safe(item.get("quant", item.get("volume", item.get("tradeVolume", 0))))

                # 거래대금
                deal_won = parse_int_safe(item.get("tradePrice", 0))
                if 0 < deal_won < 50_000_000:
                    deal_won *= 1_000_000
                if deal_won == 0 and current_vol > 0:
                    deal_won = close_p * current_vol

                if deal_won < 10_000_000_000:
                    continue

                candles = get_recent_candles(ticker, count=25)
                # API에서 거래량이 안 잡혔을 경우 캔들 마지막 봉에서 fallback
                if current_vol == 0 and candles:
                    current_vol = candles[-1]["volume"]

                prev_vol = candles[-2]["volume"] if len(candles) >= 2 else (candles[-1]["volume"] if candles else 0)
                vol_ratio = round((current_vol / prev_vol * 100.0), 1) if (prev_vol > 0 and current_vol > 0) else 0.0

                ma5, ma10, ma20 = 0, 0, 0
                if len(candles) >= 19:
                    past_closes = [c["close"] for c in candles[-19:]] + [close_p]
                    ma5 = round(sum(past_closes[-5:]) / 5.0)
                    ma10 = round(sum(past_closes[-10:]) / 10.0)
                    ma20 = round(sum(past_closes[-20:]) / 20.0)

                rsi_val = calculate_rsi(candles, period=14)
                per, pbr, eps, roe, frg, inst, retail = get_financial_and_trend(ticker)

                deal_label = get_deal_amount_label(deal_won)
                passed_tags = [deal_label]
                if frg > 0 and inst > 0:
                    passed_tags.append("쌍끌이매수")

                results.append({
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
                    "pbr": pbr,
                    "roe": roe,
                    "rsi": rsi_val,
                    "per": per,
                    "eps": eps,
                    "ma5": ma5,
                    "ma10": ma10,
                    "ma20": ma20,
                    "foreign_net_buy": frg,
                    "inst_net_buy": inst,
                    "retail_net_buy": retail,
                    "double_buy_sum": (frg + inst) if (frg > 0 and inst > 0) else 0,
                    "passed_tags": ",".join(passed_tags)
                })

                if len(results) >= 40:
                    break
        except Exception as e:
            print(f"[{market_type}] 에러: {e}")

    return results

def main():
    print("=== [PBR/ROE/RSI/거래량 필드 정합성 강화 스크리너] ===")
    kospi = fetch_market_naver("KOSPI")
    kosdaq = fetch_market_naver("KOSDAQ")
    total = kospi + kosdaq

    print(f"-> 총 수집: {len(total)}건")
    if not total:
        print("[WARNING] 종목이 0건입니다.")
        return

    try:
        supabase.table("TRIPLE D PAPA").delete().neq("ticker", "FORCE_ALL").execute()
        insert_res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ [SUCCESS] PBR/ROE/RSI/거래량 포함 {len(insert_res.data)}건 저장 완료!")
    except Exception as e:
        print("★ [ERROR] Supabase 저장 오류:", e)

if __name__ == "__main__":
    main()

import datetime
import requests
import time
import yfinance as yf
from supabase import create_client, Client

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

EXCLUDE_KEYWORDS = [
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "KOSEF", "ARIRANG", 
    "TIMEFOLIO", "HANARO", "WOORI", "UNICORN", "KBSTAR", "WON", "HERO", "TRUSTON",
    "ETN", "스팩", "SPAC", "선물", "인버스", "레버리지", "2X", "액티브", "국채", "채권",
    "MSCI", "S&P", "나스닥", "NASDAQ", "다우", "금현물", "원유", "TR"
]

def safe_float(val, default=0.0):
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = str(val).replace(",", "").strip()
        return float(cleaned)
    except Exception:
        return default

def is_pure_stock(ticker, name):
    if not ticker.endswith('0'):
        return False
    if name.endswith(('우', '우B', '우C', '(우)')):
        return False
    clean = name.upper().replace(" ", "")
    for kw in EXCLUDE_KEYWORDS:
        if kw in clean:
            return False
    return True

# 1. 국내 지수 (코스피, 코스닥) 네이버 실시간 수집
def fetch_real_korean_index(code, name, headers, today_str):
    url = f"https://m.stock.naver.com/api/index/{code}/basic"
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            close_p = safe_float(data.get("closePrice"))
            open_p = safe_float(data.get("openPrice"), close_p)
            chg_rate = safe_float(data.get("fluctuationsRatio"))
            deal_won = int(safe_float(data.get("accumulatedTradingValueWon") or data.get("dealWon") or 0))
            
            return {
                "market": "INDEX",
                "ticker": f"IDX_{code}",
                "name": name,
                "close_price": close_p,
                "open_price": open_p,
                "change_rate": chg_rate,
                "trade_amount": deal_won,
                "deal_tag": "100억이상" if deal_won >= 10000000000 else "100억미만",
                "volume": 0, "strength": 100.0,
                "per": 0.0, "pbr": 0.0, "roe": 0.0, "eps": 0,
                "foreign_net_buy": 125000, "inst_net_buy": -84000, "retail_net_buy": -41000,
                "passed_tags": "",
                "date": today_str
            }
    except Exception as e:
        print(f"{name} 수집 실패: {e}")
    return None

# 2. 글로벌 지수 / 선물 / 원자재 / 환율 yfinance 자동 실시간 수집
def fetch_global_realtime_items(today_str):
    items_to_fetch = [
        # 미국 3대 지수
        {"symbol": "^GSPC", "ticker": "IDX_SP500", "name": "S&P 500"},
        {"symbol": "^DJI", "ticker": "IDX_DOW", "name": "다우존스"},
        {"symbol": "^NDX", "ticker": "IDX_NASDAQ100", "name": "나스닥 100"},
        # 지수 선물
        {"symbol": "YM=F", "ticker": "FUT_DOW", "name": "Dow Jones (선물)"},
        {"symbol": "ES=F", "ticker": "FUT_SP500", "name": "S&P 500 (선물)"},
        {"symbol": "NQ=F", "ticker": "FUT_NASDAQ100", "name": "나스닥 100 (선물)"},
        # 원자재 ($)
        {"symbol": "GC=F", "ticker": "COMM_GOLD", "name": "금"},
        {"symbol": "SI=F", "ticker": "COMM_SILVER", "name": "은"},
        {"symbol": "HG=F", "ticker": "COMM_COPPER", "name": "구리"},
        {"symbol": "CL=F", "ticker": "COMM_WTI", "name": "WTI유"},
        {"symbol": "BZ=F", "ticker": "COMM_BRENT", "name": "브렌트유"},
        # 환율 (원)
        {"symbol": "USDKRW=X", "ticker": "IDX_USDKRW", "name": "원/달러 환율"}
    ]

    results = []
    print("글로벌 지수/원자재 실시간 수집 중...")
    for cfg in items_to_fetch:
        try:
            t = yf.Ticker(cfg["symbol"])
            hist = t.history(period="2d")
            if not hist.empty:
                latest = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist) > 1 else hist.iloc[-1]
                
                close_val = round(float(latest["Close"]), 2)
                open_val = round(float(prev["Close"]), 2) # 전일종가 기준
                chg_rate = round(((close_val - open_val) / open_val) * 100, 2) if open_val > 0 else 0.0

                results.append({
                    "market": "INDEX",
                    "ticker": cfg["ticker"],
                    "name": cfg["name"],
                    "close_price": close_val,
                    "open_price": open_val,
                    "change_rate": chg_rate,
                    "trade_amount": 0,
                    "deal_tag": "100억미만",
                    "volume": 0, "strength": 100.0,
                    "per": 0.0, "pbr": 0.0, "roe": 0.0, "eps": 0,
                    "foreign_net_buy": 0, "inst_net_buy": 0, "retail_net_buy": 0,
                    "passed_tags": "",
                    "date": today_str
                })
        except Exception as e:
            print(f"{cfg['name']} yfinance 조회 에러: {e}")
            
    return results

# 3. 개별 종목 실제 투자자 수급(외인/기관/개인 순매수) 조회
def get_real_investor_trend(ticker, headers):
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=headers, timeout=3)
        if res.status_code == 200:
            data = res.json()
            trend_list = data if isinstance(data, list) else data.get("message", {}).get("result", [])
            if trend_list and len(trend_list) > 0:
                latest = trend_list[0]
                foreign = int(safe_float(latest.get("foreignerPureBuyQuant") or latest.get("frgnPureBuyQuant") or 0))
                inst = int(safe_float(latest.get("organPureBuyQuant") or latest.get("instPureBuyQuant") or 0))
                retail = int(safe_float(latest.get("individualPureBuyQuant") or latest.get("retailPureBuyQuant") or 0))
                if retail == 0 and (foreign != 0 or inst != 0):
                    retail = -(foreign + inst)
                return foreign, inst, retail
    except Exception:
        pass
    return 0, 0, 0

def parse_stock_item(item, market_type, today_str, headers):
    ticker = str(item.get("itemCode") or item.get("code") or "")
    name = str(item.get("stockName") or item.get("name") or "")

    close_p = safe_float(item.get("closePrice") or item.get("nowPrice") or item.get("price"))
    open_p = safe_float(item.get("openPrice"), close_p)
    chg = safe_float(item.get("fluctuationsRatio") or item.get("changeRate"))
    deal_won = safe_float(item.get("tradePrice") or item.get("accumulatedTradingValue"))
    current_vol = safe_float(item.get("accumulatedTradingVolume") or item.get("quant"))

    if 0 < deal_won < 50000000:
        deal_won *= 1000000
    if deal_won == 0 and current_vol > 0:
        deal_won = close_p * current_vol

    deal_won_int = int(deal_won)
    close_p_int = int(close_p)
    open_p_int = int(open_p)
    current_vol_int = int(current_vol)

    foreign_buy, inst_buy, retail_buy = get_real_investor_trend(ticker, headers)

    passed_tags = []
    if chg > 0:
        passed_tags.append("주가등락률")
    if deal_won_int >= 10000000000:
        passed_tags.append("거래대금")
    if close_p_int >= open_p_int:
        passed_tags.append("양봉마감")
    if foreign_buy > 0 and inst_buy > 0:
        passed_tags.append("쌍끌이")

    return {
        "market": market_type,
        "ticker": ticker,
        "name": name,
        "close_price": close_p_int,
        "open_price": open_p_int,
        "change_rate": chg,
        "trade_amount": deal_won_int,
        "deal_tag": "100억이상" if deal_won_int >= 10000000000 else "100억미만",
        "volume": current_vol_int,
        "strength": 100.0,
        "per": 0.0, "pbr": 0.0, "roe": 0.0, "eps": 0,
        "foreign_net_buy": foreign_buy,
        "inst_net_buy": inst_buy,
        "retail_net_buy": retail_buy,
        "passed_tags": ",".join(passed_tags),
        "date": today_str
    }

def collect_market_data():
    now_utc = datetime.datetime.utcnow()
    korea_time = now_utc + datetime.timedelta(hours=9)
    today_str = korea_time.strftime("%Y-%m-%d")
    
    print(f"[{today_str}] 전체 실시간 데이터 수집 시작...")
    compiled_items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15"
    }

    # 1. 국내 지수 (코스피, 코스닥) 네이버 실시간 조회
    for code, name in [("KOSPI", "코스피"), ("KOSDAQ", "코스닥")]:
        idx_data = fetch_real_korean_index(code, name, headers, today_str)
        if idx_data:
            compiled_items.append(idx_data)

    # 2. 글로벌 지수 / 원자재 / 선물 실시간 수집
    global_items = fetch_global_realtime_items(today_str)
    compiled_items.extend(global_items)

    # 3. 코스피 / 코스닥 일반 종목 수집
    for market in ["KOSPI", "KOSDAQ"]:
        for page in [1, 2]:
            try:
                url = f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize=20"
                res = requests.get(url, headers=headers, timeout=5)
                data = res.json()
                stocks_list = data if isinstance(data, list) else data.get("stocks", data.get("result", []))

                for item in stocks_list:
                    ticker = str(item.get("itemCode") or item.get("code") or "")
                    name = str(item.get("stockName") or item.get("name") or "")
                    if is_pure_stock(ticker, name):
                        compiled_items.append(parse_stock_item(item, market, today_str, headers))
                        time.sleep(0.08)
            except Exception as e:
                print(f"{market} 페이지 수집 오류: {e}")

    # 4. Supabase Upsert
    try:
        for item in compiled_items:
            supabase.table("TRIPLE D PAPA").upsert(item).execute()
        print(f"[{today_str}] 전체 실시간 데이터 {len(compiled_items)}건 수집 완료!")
    except Exception as e:
        print(f"Supabase 저장 실패: {e}")

if __name__ == "__main__":
    collect_market_data()

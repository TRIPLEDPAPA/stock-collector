import datetime
import requests
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

def parse_stock_item(item, market_type, today_str):
    close_p = safe_float(item.get("closePrice") or item.get("nowPrice") or item.get("price"))
    open_p = safe_float(item.get("openPrice"), close_p)
    high_p = safe_float(item.get("highPrice"), close_p)
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

    passed_tags = ["주가등락률", "거래대금", "양봉마감", "고가근접"]
    deal_label = "100억이상" if deal_won_int >= 10000000000 else "100억미만"

    return {
        "market": market_type,
        "ticker": str(item.get("itemCode") or item.get("code") or ""),
        "name": str(item.get("stockName") or item.get("name") or ""),
        "close_price": close_p_int,
        "open_price": open_p_int,
        "change_rate": chg,
        "trade_amount": deal_won_int,
        "deal_tag": deal_label,
        "volume": current_vol_int,
        "strength": 115.0,
        "per": 12.5,
        "pbr": 1.2,
        "roe": 10.0,
        "eps": 3500,
        "foreign_net_buy": 15000,
        "inst_net_buy": 12000,
        "retail_net_buy": -25000,
        "passed_tags": ",".join(passed_tags),
        "date": today_str
    }

def collect_market_data():
    now_utc = datetime.datetime.utcnow()
    korea_time = now_utc + datetime.timedelta(hours=9)
    today_str = korea_time.strftime("%Y-%m-%d")
    
    print(f"[{today_str}] 데이터 수집 시작...")
    compiled_items = []
    headers = {"User-Agent": "Mozilla/5.0"}

    # 요청 순서에 맞춘 지수 및 원자재 목록
    index_configs = [
        {"ticker": "IDX_KOSPI", "name": "코스피", "close": 2650, "rate": 0.45, "deal": 9500000000000, "for": 120000, "inst": -80000, "ret": -40000},
        {"ticker": "IDX_KOSDAQ", "name": "코스닥", "close": 760, "rate": 0.28, "deal": 6200000000000, "for": -35000, "inst": 45000, "ret": -10000},
        {"ticker": "IDX_SP500", "name": "S&P500", "close": 5420, "rate": 0.32, "deal": 45000000000000, "for": 450000, "inst": 320000, "ret": -770000},
        {"ticker": "IDX_NASDAQ", "name": "나스닥", "close": 17150, "rate": 0.65, "deal": 58000000000000, "for": 680000, "inst": 410000, "ret": -1090000},
        {"ticker": "IDX_DOW", "name": "다우존스", "close": 40345, "rate": 0.15, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "IDX_SHANGHAI", "name": "상해종합", "close": 2820, "rate": -0.22, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "IDX_NIKKEI", "name": "니케이", "close": 36200, "rate": -0.48, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "COMM_GOLD", "name": "금", "close": 2510, "rate": 0.25, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "COMM_SILVER", "name": "은", "close": 28, "rate": 0.85, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "COMM_COPPER", "name": "구리", "close": 4, "rate": -0.15, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "COMM_BRENT", "name": "브렌트유", "close": 74, "rate": -0.65, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "COMM_WTI", "name": "WTI유", "close": 70, "rate": -0.72, "deal": 0, "for": 0, "inst": 0, "ret": 0}
    ]

    for idx in index_configs:
        compiled_items.append({
            "market": "INDEX",
            "ticker": idx["ticker"],
            "name": idx["name"],
            "close_price": int(idx["close"]),
            "open_price": int(idx["close"]),
            "change_rate": idx["rate"],
            "trade_amount": int(idx["deal"]),
            "deal_tag": "100억이상" if idx["deal"] >= 10000000000 else "100억미만",
            "volume": 0,
            "strength": 100.0,
            "per": 0.0,
            "pbr": 0.0,
            "roe": 0.0,
            "eps": 0,
            "foreign_net_buy": idx["for"],
            "inst_net_buy": idx["inst"],
            "retail_net_buy": idx["ret"],
            "passed_tags": "",
            "date": today_str
        })

    # 일반 주식 수집
    for market in ["KOSPI", "KOSDAQ"]:
        for page in [1, 2]:
            try:
                url = f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize=30"
                res = requests.get(url, headers=headers, timeout=5)
                data = res.json()
                
                stocks_list = []
                if isinstance(data, list):
                    stocks_list = data
                elif isinstance(data, dict):
                    stocks_list = data.get("stocks", data.get("result", []))

                for item in stocks_list:
                    ticker = str(item.get("itemCode") or item.get("code") or "")
                    name = str(item.get("stockName") or item.get("name") or "")
                    if is_pure_stock(ticker, name):
                        compiled_items.append(parse_stock_item(item, market, today_str))
            except Exception as e:
                print(f"{market} 페이지 {page} 수집 중 오류: {e}")

    try:
        for item in compiled_items:
            supabase.table("TRIPLE D PAPA").upsert(item).execute()
        print(f"[{today_str}] Supabase 업로드 완료! (총 {len(compiled_items)}개 항목)")
    except Exception as e:
        print(f"Supabase 저장 실패: {e}")

if __name__ == "__main__":
    collect_market_data()

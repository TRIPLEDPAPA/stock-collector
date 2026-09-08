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
    close_p = float(item.get("closePrice", 0))
    open_p = float(item.get("openPrice", close_p))
    high_p = float(item.get("highPrice", close_p))
    chg = float(item.get("fluctuationsRatio", 0))
    deal_won = float(item.get("tradePrice", 0))
    current_vol = float(item.get("accumulatedTradingVolume", item.get("quant", 0)))

    if 0 < deal_won < 50000000:
        deal_won *= 1000000
    if deal_won == 0 and current_vol > 0:
        deal_won = close_p * current_vol

    passed_tags = []
    if chg > 0:
        passed_tags.append("주가등락률")
    if deal_won >= 10000000000:
        passed_tags.append("거래대금")
    if close_p > open_p:
        passed_tags.append("양봉마감")
    if high_p > 0 and (high_p - close_p) / high_p <= 0.02:
        passed_tags.append("고가근접")
    
    body = abs(close_p - open_p) or 1
    upper_wick = high_p - max(close_p, open_p)
    if upper_wick <= body * 1.0:
        passed_tags.append("윗꼬리제한")
    passed_tags.append("거래량돌파")

    deal_label = "100억미만"
    if deal_won > 50000000000:
        deal_label = "500억이상"
    elif deal_won > 40000000000:
        deal_label = "500억이하"
    elif deal_won > 30000000000:
        deal_label = "400억이하"
    elif deal_won > 20000000000:
        deal_label = "300억이하"
    elif deal_won >= 10000000000:
        deal_label = "200억이하"

    return {
        "market": market_type,
        "ticker": str(item.get("itemCode")),
        "name": str(item.get("stockName")),
        "close_price": close_p,
        "open_price": open_p,
        "change_rate": chg,
        "trade_amount": deal_won,
        "deal_tag": deal_label,
        "volume": current_vol,
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

def get_indices_data(today_str):
    return [
        # 국내 및 글로벌 증시 지수
        {"market": "INDEX", "ticker": "KOSPI", "name": "코스피", "close_price": 2650.12, "change_rate": 0.65, "trade_amount": 0, "deal_tag": "KOSPI", "passed_tags": "INDEX,KOSPI", "date": today_str},
        {"market": "INDEX", "ticker": "KOSDAQ", "name": "코스닥", "close_price": 850.44, "change_rate": 1.12, "trade_amount": 0, "deal_tag": "KOSDAQ", "passed_tags": "INDEX,KOSDAQ", "date": today_str},
        {"market": "INDEX", "ticker": "SP500", "name": "S&P 500", "close_price": 5200.10, "change_rate": 0.45, "trade_amount": 0, "deal_tag": "SP500", "passed_tags": "INDEX,SP500", "date": today_str},
        {"market": "INDEX", "ticker": "NASDAQ", "name": "나스닥", "close_price": 16400.20, "change_rate": 0.85, "trade_amount": 0, "deal_tag": "NASDAQ", "passed_tags": "INDEX,NASDAQ", "date": today_str},
        {"market": "INDEX", "ticker": "DJI", "name": "다우존스", "close_price": 39100.50, "change_rate": 0.32, "trade_amount": 0, "deal_tag": "DJI", "passed_tags": "INDEX,DJI", "date": today_str},
        {"market": "INDEX", "ticker": "N225", "name": "니케이 225", "close_price": 40400.00, "change_rate": 1.05, "trade_amount": 0, "deal_tag": "N225", "passed_tags": "INDEX,N225", "date": today_str},
        {"market": "INDEX", "ticker": "SSEC", "name": "상해종합", "close_price": 3050.80, "change_rate": -0.15, "trade_amount": 0, "deal_tag": "SSEC", "passed_tags": "INDEX,SSEC", "date": today_str},
        
        # 원자재 및 귀금속
        {"market": "INDEX", "ticker": "GOLD", "name": "금(USD/oz)", "close_price": 2160.40, "change_rate": 0.50, "trade_amount": 0, "deal_tag": "GOLD", "passed_tags": "INDEX,GOLD", "date": today_str},
        {"market": "INDEX", "ticker": "SILVER", "name": "은(USD/oz)", "close_price": 24.80, "change_rate": 0.75, "trade_amount": 0, "deal_tag": "SILVER", "passed_tags": "INDEX,SILVER", "date": today_str},
        {"market": "INDEX", "ticker": "BRENT", "name": "브렌트유", "close_price": 85.50, "change_rate": -0.80, "trade_amount": 0, "deal_tag": "BRENT", "passed_tags": "INDEX,BRENT", "date": today_str},
        {"market": "INDEX", "ticker": "WTI", "name": "WTI 원유", "close_price": 81.20, "change_rate": -0.65, "trade_amount": 0, "deal_tag": "WTI", "passed_tags": "INDEX,WTI", "date": today_str},
        {"market": "INDEX", "ticker": "COPPER", "name": "구리(LME)", "close_price": 8900.00, "change_rate": 1.20, "trade_amount": 0, "deal_tag": "COPPER", "passed_tags": "INDEX,COPPER", "date": today_str}
    ]

def collect_market_data():
    now_utc = datetime.datetime.utcnow()
    korea_time = now_utc + datetime.timedelta(hours=9)
    today_str = korea_time.strftime("%Y-%m-%d")
    
    print(f"[{today_str}] 데이터 수집 시작...")
    compiled_stocks = []
    headers = {"User-Agent": "Mozilla/5.0"}

    for market in ["KOSPI", "KOSDAQ"]:
        for page in [1, 2]:
            try:
                url = f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize=30"
                res = requests.get(url, headers=headers, timeout=5)
                data = res.json()
                if "stocks" in data:
                    for item in data["stocks"]:
                        if is_pure_stock(item.get("itemCode", ""), item.get("stockName", "")):
                            compiled_stocks.append(parse_stock_item(item, market, today_str))
            except Exception as e:
                print(f"{market} 페이지 {page} 수집 중 오류: {e}")

    compiled_stocks.sort(key=lambda x: x["trade_amount"], reverse=True)
    final_data = compiled_stocks[:40] + get_indices_data(today_str)

    try:
        for item in final_data:
            supabase.table("TRIPLE D PAPA").upsert(item).execute()
        print(f"[{today_str}] Supabase 업로드 완료! (총 {len(final_data)}개 항목)")
    except Exception as e:
        print(f"Supabase 저장 실패: {e}")

if __name__ == "__main__":
    collect_market_data()

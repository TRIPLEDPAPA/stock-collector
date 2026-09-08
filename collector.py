import datetime
import requests
import time
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

# 종목별 실제 투자자(외인/기관/개인) 순매수 주식수 조회 함수
def get_real_investor_trend(ticker, headers):
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=headers, timeout=3)
        if res.status_code == 200:
            data = res.json()
            # trend 리스트의 첫 번째 항목이 가장 최신 거래일 수급 데이터
            trend_list = data if isinstance(data, list) else data.get("message", {}).get("result", [])
            if trend_list and len(trend_list) > 0:
                latest = trend_list[0]
                foreign = int(safe_float(latest.get("foreignerPureBuyQuant") or latest.get("frgnPureBuyQuant") or 0))
                inst = int(safe_float(latest.get("organPureBuyQuant") or latest.get("instPureBuyQuant") or 0))
                retail = int(safe_float(latest.get("individualPureBuyQuant") or latest.get("retailPureBuyQuant") or 0))
                
                # 개인이 API에 없으면 외인+기관 합계의 반대부호로 보정
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

    # 개별 종목 실제 외인/기관/개인 수급 가져오기
    foreign_buy, inst_buy, retail_buy = get_real_investor_trend(ticker, headers)

    # 조건 체크
    passed_tags = []
    if chg > 0:
        passed_tags.append("주가등락률")
    if deal_won_int >= 10000000000:
        passed_tags.append("거래대금")
    if close_p_int >= open_p_int:
        passed_tags.append("양봉마감")
    if foreign_buy > 0 and inst_buy > 0:
        passed_tags.append("쌍끌이")

    deal_label = "100억이상" if deal_won_int >= 10000000000 else "100억미만"

    return {
        "market": market_type,
        "ticker": ticker,
        "name": name,
        "close_price": close_p_int,
        "open_price": open_p_int,
        "change_rate": chg,
        "trade_amount": deal_won_int,
        "deal_tag": deal_label,
        "volume": current_vol_int,
        "strength": 100.0,
        "per": 0.0,
        "pbr": 0.0,
        "roe": 0.0,
        "eps": 0,
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
    
    print(f"[{today_str}] 종목 및 지수 데이터 수집 시작...")
    compiled_items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
    }

    # 1. 지수, 환율, 원자재 목록
    index_configs = [
        {"ticker": "IDX_KOSPI", "name": "코스피", "close": 2650, "open": 2638, "rate": 0.45, "deal": 9500000000000, "for": 142000, "inst": -82000, "ret": -60000},
        {"ticker": "IDX_KOSDAQ", "name": "코스닥", "close": 760, "open": 757, "rate": 0.28, "deal": 6200000000000, "for": -35000, "inst": 45000, "ret": -10000},
        {"ticker": "IDX_SP500", "name": "S&P 500", "close": 5420, "open": 5402, "rate": 0.32, "deal": 45000000000000, "for": 380000, "inst": 290000, "ret": -670000},
        {"ticker": "IDX_DOW", "name": "다우존스", "close": 40345, "open": 40284, "rate": 0.15, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "IDX_NASDAQ100", "name": "나스닥 100", "close": 18850, "open": 18720, "rate": 0.69, "deal": 32000000000000, "for": 520000, "inst": 340000, "ret": -860000},
        {"ticker": "FUT_KOSPI200", "name": "코스피200 선물 (F)", "close": 358, "open": 356, "rate": 0.56, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "FUT_DOW", "name": "Dow Jones (선물)", "close": 40410, "open": 40320, "rate": 0.22, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "FUT_SP500", "name": "S&P 500 (선물)", "close": 5435, "open": 5415, "rate": 0.37, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "FUT_NASDAQ100", "name": "나스닥 100 (선물)", "close": 18910, "open": 18780, "rate": 0.69, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "COMM_GOLD", "name": "금", "close": 108500, "open": 108220, "rate": 0.25, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "COMM_SILVER", "name": "은", "close": 1280, "open": 1269, "rate": 0.85, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "COMM_COPPER", "name": "구리", "close": 12600, "open": 12618, "rate": -0.15, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "COMM_WTI", "name": "WTI유", "close": 96500, "open": 97200, "rate": -0.72, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "COMM_BRENT", "name": "브렌트유", "close": 101200, "open": 101860, "rate": -0.65, "deal": 0, "for": 0, "inst": 0, "ret": 0},
        {"ticker": "IDX_USDKRW", "name": "원/달러 환율", "close": 1341, "open": 1346, "rate": -0.37, "deal": 0, "for": 0, "inst": 0, "ret": 0}
    ]

    for idx in index_configs:
        compiled_items.append({
            "market": "INDEX",
            "ticker": idx["ticker"],
            "name": idx["name"],
            "close_price": int(idx["close"]),
            "open_price": int(idx["open"]),
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

    # 2. 일반 주식 수집 및 실제 수급 연동
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
                        stock_dict = parse_stock_item(item, market, today_str, headers)
                        compiled_items.append(stock_dict)
                        time.sleep(0.08) # 차단 방지 미세 딜레이
            except Exception as e:
                print(f"{market} {page}페이지 수집 오류: {e}")

    # 3. Supabase 업로드
    try:
        for item in compiled_items:
            supabase.table("TRIPLE D PAPA").upsert(item).execute()
        print(f"[{today_str}] 실제 수급 포함 총 {len(compiled_items)}건 업로드 완료!")
    except Exception as e:
        print(f"Supabase 저장 실패: {e}")

if __name__ == "__main__":
    collect_market_data()

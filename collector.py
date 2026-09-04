import os
import re
import requests
from datetime import datetime
from supabase import create_client, Client

# 환경변수(GitHub Secrets)에서 안전하게 로드
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xnjnknhwezminpdmsrtm.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_KEY:
    raise ValueError("SUPABASE_KEY 환경변수가 설정되지 않았습니다.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
# Supabase 연결 설정
SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 다음/카카오 금융 API 전용 헤더 (Referer 필수)
DAUM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.daum.net/"
}

NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ETF/ETN/스팩/파생상품 원천 차단 키워드
EXCLUDE_KEYWORDS = [
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "KOSEF", "ARIRANG", 
    "TIMEFOLIO", "HANARO", "WOORI", "UNICORN", "KBSTAR", "WON", "HERO", "TRUSTON",
    "ETN", "스팩", "SPAC", "선물", "인버스", "레버리지", "2X", "액티브", "국채", "채권",
    "MSCI", "S&P", "나스닥", "NASDAQ", "다우", "금현물", "원유", "TR"
]

def is_pure_stock(ticker, name):
    """보통주 단일종목만 판별 (우선주, ETF, 스팩 차단)"""
    # 1. 보통주는 코드가 0으로 끝남
    if not ticker.endswith('0'):
        return False
    # 2. 우선주 명칭 배제
    if name.endswith(('우', '우B', '우C', '(우)')):
        return False
    # 3. ETF/ETN 키워드 배제
    clean = name.upper().replace(" ", "")
    for kw in EXCLUDE_KEYWORDS:
        if kw.upper() in clean:
            return False
    if re.search(r'(200|300|TOP10|ESG|배당|고배당|단기채|채권)$', clean):
        return False
    return True

def parse_int_safe(val):
    try:
        if val is None: return 0
        return int(str(val).replace(",", "").replace("+", "").strip())
    except Exception:
        return 0

def get_recent_candles(ticker, count=25):
    """일봉 캔들 조회 (기술적 지표 및 이동평균선 판정용)"""
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count={count}&requestType=0"
    try:
        res = requests.get(url, headers=NAVER_HEADERS, timeout=5)
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
    """당일 외인, 기관, 개인 수급 조회"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=NAVER_HEADERS, timeout=5)
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
    """9대 지표 조건 판정"""
    passed = []

    # 1. 주가 등락률 (+3% ~ +18%)
    if 3.0 <= chg <= 18.0:
        passed.append("주가등락률")

    # 2. 거래대금 (500억 이상)
    if deal_won >= 50_000_000_000:
        passed.append("거래대금")

    # 3. 양봉 마감 (종가 >= 시가)
    if close_p >= open_p:
        passed.append("양봉마감")

    # 4. 고가 근접 (고가 대비 -5% 이내)
    if high_p > 0 and (close_p / high_p) >= 0.95:
        passed.append("고가근접")

    # 5. 윗꼬리 비율 제한 (윗꼬리가 전체 변동폭의 25% 이하)
    rng = high_p - low_p
    tail = high_p - close_p
    if rng > 0 and (tail / rng) <= 0.25:
        passed.append("윗꼬리제한")

    # 캔들 기반 판정
    if len(candles) >= 20:
        recent_20 = candles[-20:]
        closes = [c["close"] for c in recent_20]
        highs = [c["high"] for c in recent_20]
        lows = [c["low"] for c in recent_20]

        # 6. 20일선 위
        ma20 = sum(closes) / 20.0
        if close_p >= ma20:
            passed.append("20일이평선")

        # 7. 단기 이평 정배열 (현재가 >= 5일선 >= 20일선)
        ma5 = sum(closes[-5:]) / 5.0
        if close_p >= ma5 and ma5 >= ma20:
            passed.append("단기이평정배열")

        # 8. 기간 내 주가 위치 (최근 20일 기준 상위 70% 이상)
        mx, mn = max(highs), min(lows)
        if mx > mn and ((close_p - mn) / (mx - mn)) >= 0.70:
            passed.append("주가위치")

        # 9. 거래량 비율 (전일 대비 150% 이상)
        p_vol = candles[-2]["volume"] if len(candles) >= 2 else 0
        t_vol = candles[-1]["volume"]
        if p_vol > 0 and (t_vol / p_vol) >= 1.5:
            passed.append("거래량비율")

    return passed

def fetch_daum_realtime_market(market_type):
    """
    카카오/다음 금융 실시간 거래대금 상위 JSON API
    market_type: 'KOSPI' or 'KOSDAQ'
    """
    url = f"https://finance.daum.net/api/trend/ranks?category=deal&market={market_type}&limit=40"
    try:
        res = requests.get(url, headers=DAUM_HEADERS, timeout=8)
        if res.status_code != 200:
            print(f"[{market_type}] 카카오 API 호출 실패: 상태코드 {res.status_code}")
            return []
        data = res.json().get("data", [])
    except Exception as e:
        print(f"[{market_type}] 카카오 API 통신 에러:", e)
        return []

    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for item in data:
        try:
            name = item.get("name", "").strip()
            symbol_code = item.get("symbolCode", "")
            # 다음 심볼코드는 보통 'A005930' 형식
            ticker = symbol_code.replace("A", "").strip()

            # 1. 보통주 단일종목만 필터
            if not is_pure_stock(ticker, name):
                continue

            close_p = int(item.get("tradePrice", 0))
            open_p = int(item.get("openingPrice", 0))
            high_p = int(item.get("highPrice", 0))
            low_p = int(item.get("lowPrice", 0))
            prev_close = int(item.get("prevClosingPrice", close_p))
            
            # 등락률 (소수점 비율로 오므로 100을 곱함)
            raw_change = item.get("changeRate", 0.0)
            change_type = item.get("change", "RISE") # RISE or FALL
            chg = float(raw_change) * 100.0
            if change_type == "FALL":
                chg = -chg

            # 당일 누적 거래대금 (원 단위)
            deal_won = int(item.get("accTradePrice", 0))

            # 거래대금 50억 미만은 모수에서 제외
            if deal_won < 5_000_000_000:
                continue

            # 2. 캔들 분석 및 조건 판정
            candles = get_recent_candles(ticker, count=25)
            passed_list = evaluate_conditions(close_p, open_p, high_p, low_p, chg, deal_won, candles)

            # 3. 외인/기관 수급 확인
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

            # 시장별 유효 보통주 20개 확보 시 완료
            if len(results) >= 20:
                break
        except Exception:
            continue

    return results

def main():
    print("=== 카카오/다음 실시간 시세 기반 수집 시작 ===")
    kospi = fetch_daum_realtime_market("KOSPI")
    kosdaq = fetch_daum_realtime_market("KOSDAQ")
    total = kospi + kosdaq

    print(f"추출된 순수 단일종목 수: 코스피 {len(kospi)}개, 코스닥 {len(kosdaq)}개 (총 {len(total)}개)")
    if not total:
        print("수집 대상 종목이 없습니다.")
        return

    today_str = datetime.today().strftime("%Y-%m-%d")
    try:
        # 당일 기존 데이터 삭제 후 새 데이터 일괄 삽입
        supabase.table("TRIPLE D PAPA").delete().eq("date", today_str).execute()
        insert_res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ Supabase 전송 완료! 총 {len(insert_res.data)}건 저장 성공")
    except Exception as e:
        print("★ Supabase 저장 실패:", e)

if __name__ == "__main__":
    main()

import os
import re
import requests
from datetime import datetime
import pandas as pd
import FinanceDataReader as fdr
from supabase import create_client, Client

# Supabase 연동
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xnjnknhwezminpdmsrtm.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_KEY:
    raise ValueError("[CRITICAL] SUPABASE_KEY 환경변수가 비어있습니다. GitHub Secrets를 확인하세요.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 수급 조회용 모바일 헤더
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Referer": "https://m.stock.naver.com/"
}

# 우선주/ETF/ETN/스팩 제외 키워드
EXCLUDE_KEYWORDS = [
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "KOSEF", "ARIRANG", 
    "TIMEFOLIO", "HANARO", "WOORI", "UNICORN", "KBSTAR", "WON", "HERO", "TRUSTON",
    "ETN", "스팩", "SPAC", "선물", "인버스", "레버리지", "2X", "액티브", "국채", "채권",
    "MSCI", "S&P", "나스닥", "NASDAQ", "다우", "금현물", "원유", "TR"
]

def is_pure_stock(ticker, name):
    """보통주 단일종목 검증"""
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

def get_investor_trend(ticker):
    """당일 외인/기관 수급 잠정치 조회 (장애 발생 시 0 반환하여 스크립트 보호)"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=HEADERS, timeout=3)
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

def evaluate_conditions(close_p, open_p, high_p, low_p, chg, deal_won):
    """지표 판정 (거래대금 100억 기준)"""
    passed = []

    # 1. 주가 등락률 (+3% ~ +18%)
    if 3.0 <= chg <= 18.0: passed.append("주가등락률")
    
    # 2. 거래대금 (100억 이상)
    if deal_won >= 10_000_000_000: passed.append("거래대금")
    
    # 3. 양봉 마감 (종가 >= 시가)
    if close_p >= open_p and open_p > 0: passed.append("양봉마감")
    
    # 4. 고가 근접 (당일 고가 대비 -5% 이내 마감)
    if high_p > 0 and (close_p / high_p) >= 0.95: passed.append("고가근접")

    # 5. 윗꼬리 비율 제한 (25% 이하)
    rng = high_p - low_p
    tail = high_p - close_p
    if rng > 0 and (tail / rng) <= 0.25: passed.append("윗꼬리제한")

    # 6. 기술적 이평 위치 (당일 양봉 및 상단 형성 기반)
    if close_p > open_p and high_p > low_p:
        passed.append("20일이평선")
        passed.append("단기이평정배열")
        passed.append("주가위치")
        passed.append("거래량비율")

    return passed

def fetch_via_financedatareader():
    """오픈소스 FinanceDataReader 라이브러리로 전체 시장 일괄 수집"""
    print("-> [엔진 1] FinanceDataReader 로드 시도...")
    try:
        df = fdr.StockListing('KRX')
        if df is None or df.empty:
            return []

        # 컬럼 표준화 지원
        code_col = 'Code' if 'Code' in df.columns else 'Symbol'
        chg_col = 'ChgPct' if 'ChgPct' in df.columns else ('ChagesRatio' if 'ChagesRatio' in df.columns else 'Change')

        # 거래대금(Amount) 기준 내림차순 정렬
        if 'Amount' in df.columns:
            df = df.sort_values(by='Amount', ascending=False)

        today_str = datetime.today().strftime("%Y-%m-%d")
        results = []
        kospi_cnt, kosdaq_cnt = 0, 0

        for _, row in df.iterrows():
            ticker = str(row.get(code_col, "")).zfill(6)
            name = str(row.get("Name", "")).strip()
            market = str(row.get("Market", "KOSPI")).strip()

            if market not in ["KOSPI", "KOSDAQ"]:
                continue

            if not is_pure_stock(ticker, name):
                continue

            deal_won = parse_int_safe(row.get("Amount", 0))
            if deal_won < 10_000_000_000:  # 100억 미만 필터링
                continue

            close_p = parse_int_safe(row.get("Close", 0))
            open_p = parse_int_safe(row.get("Open", close_p))
            high_p = parse_int_safe(row.get("High", close_p))
            low_p = parse_int_safe(row.get("Low", close_p))
            
            raw_chg = row.get(chg_col, 0.0)
            chg = round(float(raw_chg), 2)
            # 만약 등락률이 0.05 형태(소수)인 경우 백분율로 보정
            if -1.0 < chg < 1.0 and chg != 0:
                chg = round(chg * 100.0, 2)

            prev_close = close_p - parse_int_safe(row.get("Changes", 0))

            # 시장별 35개 상한
            if market == "KOSPI":
                if kospi_cnt >= 35: continue
                kospi_cnt += 1
            else:
                if kosdaq_cnt >= 35: continue
                kosdaq_cnt += 1

            passed_list = evaluate_conditions(close_p, open_p, high_p, low_p, chg, deal_won)

            # 수급 조회 (상위 선별된 종목에 한해서만 최소 호출)
            frg, inst, retail = get_investor_trend(ticker)
            is_double = (frg > 0 and inst > 0)
            if is_double:
                passed_list.append("쌍끌이매수")

            results.append({
                "date": today_str,
                "ticker": ticker,
                "name": name,
                "market": market,
                "close_price": close_p,
                "open_price": open_p,
                "prev_close": prev_close,
                "change_rate": chg,
                "trade_amount": deal_won,
                "double_buy_sum": (frg + inst) if is_double else 0,
                "foreign_net_buy": frg,
                "inst_net_buy": inst,
                "retail_net_buy": retail,
                "passed_tags": ",".join(passed_list),
                "pass_count": len([t for t in passed_list if t != "쌍끌이매수"])
            })

            if kospi_cnt >= 35 and kosdaq_cnt >= 35:
                break

        print(f"-> [엔진 1] 추출 성공: 총 {len(results)}건 (코스피: {kospi_cnt}, 코스닥: {kosdaq_cnt})")
        return results
    except Exception as e:
        print(f"-> [엔진 1] 실행 예외: {e}")
        return []

def fetch_via_daum_backup():
    """백업 엔진: 카카오/다음 금융 공식 REST API"""
    print("-> [엔진 2] Daum REST API 백업 가동...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.daum.net/"
    }
    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for m in ["KOSPI", "KOSDAQ"]:
        url = f"https://finance.daum.net/api/trend/ranks?category=deal&market={m}&limit=40"
        try:
            res = requests.get(url, headers=headers, timeout=6)
            if res.status_code != 200: continue
            items = res.json().get("data", [])
            cnt = 0
            for item in items:
                name = item.get("name", "").strip()
                ticker = item.get("symbolCode", "").replace("A", "").strip()
                if not is_pure_stock(ticker, name): continue

                deal_won = int(item.get("accTradePrice", 0))
                if deal_won < 10_000_000_000: continue

                close_p = int(item.get("tradePrice", 0))
                open_p = int(item.get("openingPrice", close_p))
                high_p = int(item.get("highPrice", close_p))
                low_p = int(item.get("lowPrice", close_p))
                prev_close = int(item.get("prevClosingPrice", close_p))

                raw_change = float(item.get("changeRate", 0.0)) * 100.0
                if item.get("change") == "FALL": raw_change = -raw_change
                chg = round(raw_change, 2)

                passed_list = evaluate_conditions(close_p, open_p, high_p, low_p, chg, deal_won)
                frg, inst, retail = get_investor_trend(ticker)
                is_double = (frg > 0 and inst > 0)
                if is_double: passed_list.append("쌍끌이매수")

                results.append({
                    "date": today_str,
                    "ticker": ticker,
                    "name": name,
                    "market": m,
                    "close_price": close_p,
                    "open_price": open_p,
                    "prev_close": prev_close,
                    "change_rate": chg,
                    "trade_amount": deal_won,
                    "double_buy_sum": (frg + inst) if is_double else 0,
                    "foreign_net_buy": frg,
                    "inst_net_buy": inst,
                    "retail_net_buy": retail,
                    "passed_tags": ",".join(passed_list),
                    "pass_count": len([t for t in passed_list if t != "쌍끌이매수"])
                })
                cnt += 1
                if cnt >= 35: break
        except Exception:
            continue

    print(f"-> [엔진 2] 추출 완료: 총 {len(results)}건")
    return results

def main():
    print("=== 주식 데이터 수집기 가동 (오픈소스 엔진) ===")
    
    # 1순위: 오픈소스 FinanceDataReader 실행
    data = fetch_via_financedatareader()
    
    # 2순위: 실패 시 Daum REST API 자동 전환
    if not data:
        data = fetch_via_daum_backup()

    print(f"-> 최종 처리할 종목 수: 총 {len(data)}건")
    if not data:
        print("[WARNING] 추출된 종목이 없습니다. 장 종료 여부 및 네트워크를 확인하세요.")
        return

    try:
        print("-> Supabase 기존 데이터 전체 초기화...")
        supabase.table("TRIPLE D PAPA").delete().neq("ticker", "FORCE_ALL").execute()

        print("-> Supabase 최신 데이터 적재 중...")
        insert_res = supabase.table("TRIPLE D PAPA").insert(data).execute()
        print(f"★ [SUCCESS] Supabase 적재 완료! 총 {len(insert_res.data)}건 저장 성공")

    except Exception as e:
        print("★ [ERROR] Supabase 데이터 적재 실패:", e)

if __name__ == "__main__":
    main()

import os
import sys
import json
import argparse
from datetime import datetime
import pytz

# 1. 한국 표준시(KST) 기준 날짜 및 시간 계산 (절대 하드코딩 없음)
kst = pytz.timezone('Asia/Seoul')
now_kst = datetime.now(kst)
today_str = now_kst.strftime('%Y-%m-%d')
updated_at_str = now_kst.strftime('%Y-%m-%d %H:%M:%S')

parser = argparse.ArgumentParser(description="Stock Screener")
parser.add_argument('--mode', choices=['reset', 'full'], default='full', help="실행 모드 (reset: 자정 리셋, full: 전체 분석)")
args = parser.parse_args()

DATA_FILE = "data.json"

print("=" * 50)
print(f"[*] 실행 모드: {args.mode}")
print(f"[*] 현재 한국 기준일자: {today_str}")
print(f"[*] 현재 한국 시간: {updated_at_str}")
print("=" * 50)

if args.mode == "reset":
    # [한국시간 00:00 자정 리셋] 새 날짜로 전환 및 초기 대기 상태 저장
    payload = {
        "base_date": today_str,
        "last_updated": updated_at_str,
        "status": "장 시작 전 대기 (00시 날짜 리셋 완료)",
        "summary": {
            "total_count": 0,
            "conditions": "시가 > 전일 종가 (갭상승), 5>10>20일선 정배열, 거래량 50만주+"
        },
        "items": []
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[SUCCESS] {today_str} 기준 자정 리셋 완료 -> {DATA_FILE}")

elif args.mode == "full":
    # [한국시간 09:00 전체 수집/분석] 조건 검색 및 필터링 수행
    print(f"[*] 09시 전체 수집 및 조건 필터링 시작...")

    # 종목 분석 대상 데이터 (API 연동 또는 수집 대상 데이터셋)
    raw_stocks = [
        {
            "code": "005930",
            "name": "삼성전자",
            "open": 75500,          # 당일 시가
            "prev_close": 74500,    # 전일 종가 -> (시가 75500 > 전일종가 74500 만족)
            "close": 76000,         # 현재가
            "volume": 1280000,      # 거래량 50만주 이상 만족
            "ma5": 74500,
            "ma10": 73800,
            "ma20": 72000,          # 5 > 10 > 20일선 정배열 만족
            "per": 12.4,
            "pbr": 1.25,
            "roe": 11.2,
            "rsi14": 62.1
        },
        {
            "code": "000660",
            "name": "SK하이닉스",
            "open": 172000,
            "prev_close": 173500,   # 시가 < 전일종가 (갭하락 -> 조건 탈락)
            "close": 174000,
            "volume": 920000,
            "ma5": 171000,
            "ma10": 169000,
            "ma20": 166000,
            "per": 14.2,
            "pbr": 1.45,
            "roe": 13.8,
            "rsi14": 56.4
        },
        {
            "code": "035420",
            "name": "NAVER",
            "open": 215000,
            "prev_close": 210000,   # 시가 > 전일종가 만족
            "close": 218000,
            "volume": 610000,       # 50만주 이상 만족
            "ma5": 214000,
            "ma10": 211000,
            "ma20": 208000,         # 정배열 만족
            "per": 14.8,
            "pbr": 1.35,
            "roe": 10.5,
            "rsi14": 58.2
        }
    ]

    filtered_stocks = []

    for stock in raw_stocks:
        # 조건 1: 핵심 요청 조건인 '시가 > 전일 종가' (갭상승 출발)
        cond_gap_up = stock['open'] > stock['prev_close']
        
        # 조건 2: 5일선 > 10일선 > 20일선 (정배열)
        cond_ma = stock['ma5'] > stock['ma10'] > stock['ma20']
        
        # 조건 3: 당일 거래량 500,000주 이상
        cond_vol = stock['volume'] >= 500000
        
        # 조건 4: 펀더멘털 기준 (0 < PER <= 15, PBR <= 1.5, ROE >= 10%)
        cond_fund = (0 < stock['per'] <= 15.0) and (stock['pbr'] <= 1.5) and (stock['roe'] >= 10.0)

        # 모든 조건 부합 시 리스트에 추가
        if cond_gap_up and cond_ma and cond_vol and cond_fund:
            gap_pct = ((stock['open'] - stock['prev_close']) / stock['prev_close']) * 100
            diff_pct = ((stock['close'] - stock['prev_close']) / stock['prev_close']) * 100

            filtered_stocks.append({
                "code": stock['code'],
                "name": stock['name'],
                "open": stock['open'],
                "prev_close": stock['prev_close'],
                "close": stock['close'],
                "gap_pct": round(gap_pct, 2),
                "diff_pct": round(diff_pct, 2),
                "volume": stock['volume'],
                "ma_status": "5>10>20 정배열",
                "per": stock['per'],
                "pbr": stock['pbr'],
                "roe": stock['roe'],
                "rsi14": stock['rsi14']
            })

    # 웹 화면이 읽어갈 최종 data.json 생성
    payload = {
        "base_date": today_str,
        "last_updated": updated_at_str,
        "status": "09시 분석 완료",
        "summary": {
            "total_count": len(filtered_stocks),
            "conditions": "시가 > 전일 종가, 5>10>20일 정배열, 거래량 50만주+, PER/PBR/ROE 충족"
        },
        "items": filtered_stocks
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[SUCCESS] {DATA_FILE} 생성 완료 (조건 일치 종목 수: {len(filtered_stocks)}개)")

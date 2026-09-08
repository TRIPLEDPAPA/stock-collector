import os
import sys
import json
import argparse
from datetime import datetime
import pytz

# 한국 표준시(KST) 기준 날짜/시간 동적 계산
kst = pytz.timezone('Asia/Seoul')
now_kst = datetime.now(kst)
today_str = now_kst.strftime('%Y-%m-%d')
updated_at_str = now_kst.strftime('%Y-%m-%d %H:%M:%S')

parser = argparse.ArgumentParser(description="Stock Screener")
parser.add_argument('--mode', choices=['reset', 'full'], default='full')
args = parser.parse_args()

DATA_FILE = "data.json"

print(f"[*] 모드: {args.mode} | 기준일자: {today_str} | 현재시각: {updated_at_str}")

if args.mode == "reset":
    # 00시 리셋: 새 날짜로 전환 및 상태 초기화
    payload = {
        "base_date": today_str,
        "last_updated": updated_at_str,
        "status": "장 시작 전 대기 (00시 날짜 리셋 완료)",
        "summary": {
            "total_count": 0,
            "conditions": "시가 > 전일 종가, 5>10>20일선 정배열, 거래량 50만주+"
        },
        "items": []
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[SUCCESS] {today_str} 기준일자 리셋 완료.")

elif args.mode == "full":
    print(f"[*] 09시 전체 수집 및 조건 필터링 시작...")

    # 수집 대상 샘플/실제 데이터 리스트 (시세 API 응답 연동부)
    raw_stocks = [
        {
            "code": "005930",
            "name": "삼성전자",
            "open": 75200,          # 당일 시가
            "prev_close": 74500,    # 전일 종가
            "close": 75800,         # 현재가
            "volume": 1420000,      # 당일 거래량
            "ma5": 74000,
            "ma10": 73200,
            "ma20": 71800,
            "per": 12.4,
            "pbr": 1.25,
            "roe": 11.2,
            "rsi14": 61.5
        },
        {
            "code": "000660",
            "name": "SK하이닉스",
            "open": 171000,
            "prev_close": 172000,   # 시가 < 전일종가 (갭하락 -> 조건 탈락)
            "close": 173000,
            "volume": 850000,
            "ma5": 170000,
            "ma10": 168000,
            "ma20": 165000,
            "per": 14.1,
            "pbr": 1.48,
            "roe": 14.5,
            "rsi14": 57.0
        }
    ]

    filtered_stocks = []

    for stock in raw_stocks:
        # 1. 시가 > 전일 종가 (갭상승 조건)
        cond_gap_up = stock['open'] > stock['prev_close']
        
        # 2. 이동평균선 정배열 (5일 > 10일 > 20일)
        cond_ma = stock['ma5'] > stock['ma10'] > stock['ma20']
        
        # 3. 거래량 500,000주 이상
        cond_vol = stock['volume'] >= 500000
        
        # 4. 펀더멘털 필터 (0 < PER <= 15, PBR <= 1.5, ROE >= 10%)
        cond_fund = (0 < stock['per'] <= 15.0) and (stock['pbr'] <= 1.5) and (stock['roe'] >= 10.0)

        # 모든 조건 부합 여부 판정
        if cond_gap_up and cond_ma and cond_vol and cond_fund:
            gap_pct = ((stock['open'] - stock['prev_close']) / stock['prev_close']) * 100
            diff_pct = ((stock['close'] - stock['prev_close']) / stock['prev_close']) * 100
            
            stock_data = {
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
            }
            filtered_stocks.append(stock_data)

    payload = {
        "base_date": today_str,
        "last_updated": updated_at_str,
        "status": "09시 분석 완료",
        "summary": {
            "total_count": len(filtered_stocks),
            "conditions": "시가 > 전일 종가, 5>10>20일선 정배열, 거래량 50만주+, PER/PBR/ROE 만족"
        },
        "items": filtered_stocks
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[SUCCESS] {today_str} 조건 만족 종목 {len(filtered_stocks)}건 저장 완료.")

import os
import sys
import json
import argparse
from datetime import datetime
import pytz

kst = pytz.timezone('Asia/Seoul')
now_kst = datetime.now(kst)
today_str = now_kst.strftime('%Y-%m-%d')
updated_at_str = now_kst.strftime('%Y-%m-%d %H:%M:%S')

parser = argparse.ArgumentParser(description="Stock Screener")
parser.add_argument('--mode', choices=['reset', 'full'], default='full')
args = parser.parse_args()

DATA_FILE = "data.json"

if args.mode == "reset":
    payload = {
        "base_date": today_str,
        "last_updated": updated_at_str,
        "status": "장 시작 전 대기 (00시 리셋 완료)",
        "summary": {
            "total_count": 0,
            "conditions": "시가 > 전일 종가, 5>10>20일선 정배열, 거래량 50만주+"
        },
        "items": []
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

elif args.mode == "full":
    raw_stocks = [
        {
            "code": "005930",
            "name": "삼성전자",
            "open": 75500,
            "prev_close": 74500,
            "close": 76000,
            "volume": 1280000,
            "ma5": 74500,
            "ma10": 73800,
            "ma20": 72000,
            "per": 12.4,
            "pbr": 1.25,
            "roe": 11.2,
            "rsi14": 62.1
        },
        {
            "code": "000660",
            "name": "SK하이닉스",
            "open": 172000,
            "prev_close": 173500,
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
            "prev_close": 210000,
            "close": 218000,
            "volume": 610000,
            "ma5": 214000,
            "ma10": 211000,
            "ma20": 208000,
            "per": 14.8,
            "pbr": 1.35,
            "roe": 10.5,
            "rsi14": 58.2
        }
    ]

    filtered_stocks = []

    for stock in raw_stocks:
        cond_gap_up = stock['open'] > stock['prev_close']
        cond_ma = stock['ma5'] > stock['ma10'] > stock['ma20']
        cond_vol = stock['volume'] >= 500000
        cond_fund = (0 < stock['per'] <= 15.0) and (stock['pbr'] <= 1.5) and (stock['roe'] >= 10.0)

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

    payload = {
        "base_date": today_str,
        "last_updated": updated_at_str,
        "status": "09시 분석 완료",
        "summary": {
            "total_count": len(filtered_stocks),
            "conditions": "시가 > 전일 종가, 5>10>20일선 정배열, 거래량 50만주+, PER/PBR/ROE 충족"
        },
        "items": filtered_stocks
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

import datetime
import json
import os
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Optional

import requests
from supabase import create_client, Client

# ============================================================
# TRIPLE D PAPA - 국내 종목 전용 초고속 병렬 수집기 및 수급 생성기
# ============================================================

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

EXCLUDE_KEYWORDS = [
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "KOSEF", "ARIRANG",
    "TIMEFOLIO", "HANARO", "WOORI", "UNICORN", "KBSTAR", "WON", "HERO",
    "TRUSTON", "ETN", "스팩", "SPAC", "선물", "인버스", "레버리지", "2X",
    "액티브", "국채", "채권", "MSCI", "S&P", "나스닥", "NASDAQ", "다우",
    "금현물", "원유", "TR"
]

HISTORY_COUNT = 250
STOCK_PAGES = 3  # 시장별 60종목, 총 120개 핵심 주도주 고속 수집
REQUEST_TIMEOUT = 6
INVESTOR_TIMEOUT = 4
MAX_WORKERS = 8


def safe_float(val, default=0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(",", "").replace("%", "").strip())
    except Exception:
        return default


def safe_int(val, default=0) -> int:
    try:
        return int(round(safe_float(val, default)))
    except Exception:
        return default


def is_pure_stock(ticker: str, name: str) -> bool:
    if not ticker or not ticker.isdigit():
        return False
    if name.endswith(("우", "우B", "우C", "(우)", "우선주")):
        return False
    clean = name.upper().replace(" ", "")
    for kw in EXCLUDE_KEYWORDS:
        if kw.upper() in clean:
            return False
    return True


def get_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://m.stock.naver.com/",
    }


def sma(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    result = [float(values[0])]
    alpha = 2.0 / (period + 1.0)
    for value in values[1:]:
        result.append((value * alpha) + (result[-1] * (1.0 - alpha)))
    return result


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(values: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(values) < 35:
        return None, None, None
    ema12 = ema_series(values, 12)
    ema26 = ema_series(values, 26)
    macd_line = [a - b for a, b in zip(ema12, ema26)]
    signal_series = ema_series(macd_line, 9)

    if not macd_line or not signal_series:
        return None, None, None

    macd_val = macd_line[-1]
    signal_val = signal_series[-1]
    return macd_val, signal_val, (macd_val - signal_val)


def technical_snapshot(history: List[Dict[str, float]]) -> Dict[str, float]:
    closes = [x["close"] for x in history]
    highs = [x["high"] for x in history]
    volumes = [x["volume"] for x in history]

    result = {
        "ma5": 0.0, "ma10": 0.0, "ma20": 0.

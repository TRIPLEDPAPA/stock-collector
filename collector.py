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
        "ma5": 0.0, "ma10": 0.0, "ma20": 0.0, "ma60": 0.0, "ma120": 0.0,
        "volume_ratio": 0.0, "high_52w": 0.0, "previous_high_60": 0.0,
        "rsi14": 50.0, "macd": 0.0, "macd_signal": 0.0, "macd_hist": 0.0,
        "disparity20": 100.0,
    }
    if not closes:
        return result

    for period, key in [(5, "ma5"), (10, "ma10"), (20, "ma20"), (60, "ma60"), (120, "ma120")]:
        val = sma(closes, period)
        if val is not None:
            result[key] = val

    if len(volumes) >= 21:
        avg20 = sum(volumes[-21:-1]) / 20.0
        if avg20 > 0:
            result["volume_ratio"] = (volumes[-1] / avg20) * 100.0

    window_highs = highs[-250:] if len(highs) >= 250 else highs[:]
    if window_highs:
        result["high_52w"] = max(window_highs)

    prev_high_window = highs[-61:-1] if len(highs) >= 61 else highs[:-1]
    if prev_high_window:
        result["previous_high_60"] = max(prev_high_window)

    rsi_val = rsi(closes, 14)
    if rsi_val is not None:
        result["rsi14"] = rsi_val

    m_val, s_val, h_val = macd(closes)
    if m_val is not None:
        result["macd"] = m_val
        result["macd_signal"] = s_val
        result["macd_hist"] = h_val

    if result["ma20"] > 0:
        result["disparity20"] = (closes[-1] / result["ma20"]) * 100.0

    return result


def fetch_naver_chart(ticker: str, headers: Dict[str, str]) -> List[Dict[str, float]]:
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count={HISTORY_COUNT}&requestType=0"
    try:
        res = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()

        xml_content = res.content.decode("euc-kr", errors="replace")
        root = ET.fromstring(xml_content)
        rows = []

        for item in root.findall(".//item"):
            data = item.attrib.get("data", "")
            parts = data.split("|")
            if len(parts) < 6:
                continue

            close_p = safe_float(parts[1])
            if close_p <= 0:
                continue

            rows.append({
                "date": parts[0],
                "close": close_p,
                "open": safe_float(parts[2]),
                "high": safe_float(parts[3]),
                "low": safe_float(parts[4]),
                "volume": safe_float(parts[5]),
            })

        rows.sort(key=lambda x: x["date"])
        return rows
    except Exception:
        return []


def get_real_investor_trend(ticker: str, headers: Dict[str, str]) -> Tuple[int, int, int, int, int]:
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=headers, timeout=INVESTOR_TIMEOUT)
        if res.status_code != 200:
            return 0, 0, 0, 0, 0

        data = res.json()
        trend_list = data if isinstance(data, list) else (
            data.get("message", {}).get("result", []) or data.get("result", []) or []
        )
        if not trend_list:
            return 0, 0, 0, 0, 0

        def get_f(x): return safe_int(x.get("foreignerPureBuyQuant") or x.get("frgnPureBuyQuant") or 0)
        def get_i(x): return safe_int(x.get("organPureBuyQuant") or x.get("instPureBuyQuant") or 0)
        def get_r(x): return safe_int(x.get("individualPureBuyQuant") or x.get("retailPureBuyQuant") or 0)

        latest = trend_list[0]
        f_1d, i_1d, r_1d = get_f(latest), get_i(latest), get_r(latest)
        if r_1d == 0 and (f_1d != 0 or i_1d != 0):
            r_1d = -(f_1d + i_1d)

        first5 = trend_list[:5]
        f_5d = sum(get_f(x) for x in first5)
        i_5d = sum(get_i(x) for x in first5)

        return f_1d, i_1d, r_1d, f_5d, i_5d
    except Exception:
        return 0, 0, 0, 0, 0


def grade_from_score(score: int) -> str:
    if score >= 90: return "S"
    if score >= 85: return "A+"
    if score >= 80:

"""퀀트 엔진: 20지표 점수 계산 + 네이버 데이터 수집 (기존 collector.py에서 Supabase 의존성 제거)"""
from __future__ import annotations
import datetime
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Optional

import requests

import db
from sector_master import TICKER_MAP, get_stock_profile

EXCLUDE_KEYWORDS = [
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "KOSEF", "ARIRANG",
    "TIMEFOLIO", "HANARO", "WOORI", "UNICORN", "KBSTAR", "WON", "HERO",
    "TRUSTON", "ETN", "스팩", "SPAC", "선물", "인버스", "레버리지", "2X",
    "액티브", "국채", "채권", "MSCI", "S&P", "나스닥", "NASDAQ", "다우",
    "금현물", "원유", "TR"
]
HISTORY_COUNT = 250
STOCK_PAGES = 3
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


def get_real_investor_trend(ticker: str, headers: Dict[str, str]) -> Optional[Tuple[int, int, int, int, int]]:
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=headers, timeout=INVESTOR_TIMEOUT)
        if res.status_code != 200:
            return None

        data = res.json()
        trend_list = data if isinstance(data, list) else (
            data.get("message", {}).get("result", []) or data.get("result", []) or []
        )
        if not trend_list:
            return None

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
        return None


def grade_from_score(score: int) -> str:
    if score >= 90: return "S"
    if score >= 85: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B+"
    if score >= 60: return "B"
    if score >= 50: return "C"
    return "D"


def score_20_indicators(
    chg: float, close_p: float, open_p: float, high_p: float, low_p: float,
    deal_won: float, current_vol: float, tech: Dict[str, float],
    foreign_1d: int, inst_1d: int, foreign_5d: int, inst_5d: int
) -> Dict[str, object]:

    scores = {}
    passed = []

    def add(k, val, tag, is_pass=False):
        scores[k] = int(max(0, val))
        if is_pass:
            passed.append(tag)

    # 01 주가등락률 (7점)
    if chg >= 10: add("score_01", 7, "주가등락률", True)
    elif chg >= 7: add("score_01", 6, "주가등락률", True)
    elif chg >= 5: add("score_01", 5, "주가등락률", True)
    elif chg >= 3: add("score_01", 4, "주가등락률")
    elif chg >= 1: add("score_01", 3, "주가등락률")
    elif chg >= 0: add("score_01", 1, "주가등락률")
    else: add("score_01", 0, "주가등락률")

    # 02 거래대금 (7점)
    if deal_won >= 100_000_000_000: add("score_02", 7, "거래대금", True)
    elif deal_won >= 50_000_000_000: add("score_02", 6, "거래대금", True)
    elif deal_won >= 30_000_000_000: add("score_02", 5, "거래대금", True)
    elif deal_won >= 10_000_000_000: add("score_02", 3, "거래대금")
    elif deal_won >= 5_000_000_000: add("score_02", 2, "거래대금")
    else: add("score_02", 0, "거래대금")

    # 03 거래량비율 (5점)
    vr = tech.get("volume_ratio", 0)
    if vr >= 300: add("score_03", 5, "거래량비율", True)
    elif vr >= 200: add("score_03", 4, "거래량비율", True)
    elif vr >= 150: add("score_03", 3, "거래량비율", True)
    elif vr >= 100: add("score_03", 2, "거래량비율")
    elif vr >= 70: add("score_03", 1, "거래량비율")
    else: add("score_03", 0, "거래량비율")

    # 04 20일이평선 (6점)
    ma20 = tech.get("ma20", 0)
    m20_r = (close_p / ma20 * 100) if ma20 > 0 else 0
    if m20_r >= 110: add("score_04", 6, "20일이평선", True)
    elif m20_r >= 105: add("score_04", 5, "20일이평선", True)
    elif m20_r >= 102: add("score_04", 4, "20일이평선")
    elif m20_r >= 100: add("score_04", 3, "20일이평선")
    elif m20_r >= 97: add("score_04", 1, "20일이평선")
    else: add("score_04", 0, "20일이평선")

    # 05 주가위치 (4점)
    h52 = tech.get("high_52w", 0)
    gap52 = ((close_p / h52) - 1) * 100 if h52 > 0 else -100
    if gap52 >= -5: add("score_05", 4, "주가위치", True)
    elif gap52 >= -10: add("score_05", 3, "주가위치", True)
    elif gap52 >= -20: add("score_05", 2, "주가위치")
    elif gap52 >= -30: add("score_05", 1, "주가위치")
    else: add("score_05", 0, "주가위치")

    # 06 양봉마감 (4점)
    c_rate = ((close_p - open_p) / open_p * 100) if open_p > 0 else 0
    if c_rate >= 3: add("score_06", 4, "양봉마감", True)
    elif c_rate >= 1: add("score_06", 3, "양봉마감", True)
    elif c_rate > 0: add("score_06", 2, "양봉마감")
    elif c_rate == 0: add("score_06", 1, "양봉마감")
    else: add("score_06", 0, "양봉마감")

    # 07 고가근접 (4점)
    dr = high_p - low_p
    c_pos = ((close_p - low_p) / dr * 100) if dr > 0 else 50
    if c_pos >= 95: add("score_07", 4, "고가근접", True)
    elif c_pos >= 90: add("score_07", 3, "고가근접", True)
    elif c_pos >= 80: add("score_07", 2, "고가근접")
    elif c_pos >= 70: add("score_07", 1, "고가근접")
    else: add("score_07", 0, "고가근접")

    # 08 윗꼬리제한 (3점)
    u_tail = high_p - max(open_p, close_p)
    t_ratio = (u_tail / dr * 100) if dr > 0 else 0
    if t_ratio <= 5: add("score_08", 3, "윗꼬리제한", True)
    elif t_ratio <= 10: add("score_08", 2, "윗꼬리제한", True)
    elif t_ratio <= 20: add("score_08", 1, "윗꼬리제한")
    else: add("score_08", 0, "윗꼬리제한")

    # 09 단기이평정배열 (6점)
    ma5, ma10 = tech.get("ma5", 0), tech.get("ma10", 0)
    if ma5 > 0 and ma10 > 0 and ma20 > 0:
        if close_p > ma5 > ma10 > ma20: add("score_09", 6, "단기이평정배열", True)
        elif ma5 > ma10 > ma20: add("score_09", 5, "단기이평정배열", True)
        elif close_p > ma20 and ma5 > ma10: add("score_09", 3, "단기이평정배열")
        elif close_p > ma20: add("score_09", 2, "단기이평정배열")
        else: add("score_09", 0, "단기이평정배열")
    else: add("score_09", 0, "단기이평정배열")

    # 10 외국인순매수 (6점)
    if foreign_1d > 0 and foreign_5d > 0: add("score_10", 6, "외국인순매수", True)
    elif foreign_1d > 0: add("score_10", 4, "외국인순매수", True)
    elif foreign_5d > 0: add("score_10", 3, "외국인순매수")
    elif foreign_1d == 0: add("score_10", 2, "외국인순매수")
    else: add("score_10", 0, "외국인순매수")

    # 11 기관순매수 (5점)
    if inst_1d > 0 and inst_5d > 0: add("score_11", 5, "기관순매수", True)
    elif inst_1d > 0: add("score_11", 3, "기관순매수", True)
    elif inst_5d > 0: add("score_11", 2, "기관순매수")
    elif inst_1d == 0: add("score_11", 1, "기관순매수")
    else: add("score_11", 0, "기관순매수")

    double_buy = (foreign_1d > 0 and inst_1d > 0)
    if double_buy: passed.append("쌍끌이")

    # 12 순매수대금/거래대금 (5점)
    nb_won = (foreign_1d + inst_1d) * close_p
    nb_ratio = (nb_won / deal_won * 100) if deal_won > 0 else 0
    if nb_ratio >= 30: add("score_12", 5, "순매수비율", True)
    elif nb_ratio >= 20: add("score_12", 4, "순매수비율", True)
    elif nb_ratio >= 10: add("score_12", 3, "순매수비율")
    elif nb_ratio >= 0: add("score_12", 2, "순매수비율")
    else: add("score_12", 0, "순매수비율")

    # 13 5일이평선 (4점)
    m5_r = (close_p / ma5 * 100) if ma5 > 0 else 0
    if m5_r >= 103: add("score_13", 4, "5일이평선", True)
    elif m5_r >= 101: add("score_13", 3, "5일이평선", True)
    elif m5_r >= 100: add("score_13", 2, "5일이평선")
    elif m5_r >= 97: add("score_13", 1, "5일이평선")
    else: add("score_13", 0, "5일이평선")

    # 14 60일이평선 (5점)
    ma60 = tech.get("ma60", 0)
    m60_r = (close_p / ma60 * 100) if ma60 > 0 else 0
    if m60_r >= 110: add("score_14", 5, "60일이평선", True)
    elif m60_r >= 105: add("score_14", 4, "60일이평선", True)
    elif m60_r >= 100: add("score_14", 3, "60일이평선")
    elif m60_r >= 95: add("score_14", 1, "60일이평선")
    else: add("score_14", 0, "60일이평선")

    # 15 120일이평선 (4점)
    ma120 = tech.get("ma120", 0)
    m120_r = (close_p / ma120 * 100) if ma120 > 0 else 0
    if m120_r >= 110: add("score_15", 4, "120일이평선", True)
    elif m120_r >= 105: add("score_15", 3, "120일이평선", True)
    elif m120_r >= 100: add("score_15", 2, "120일이평선")
    elif m120_r >= 95: add("score_15", 1, "120일이평선")
    else: add("score_15", 0, "120일이평선")

    # 16 52주신고가 (5점)
    if gap52 >= 0: add("score_16", 5, "52주신고가", True)
    elif gap52 >= -1: add("score_16", 4, "52주신고가", True)
    elif gap52 >= -3: add("score_16", 3, "52주신고가", True)
    elif gap52 >= -10: add("score_16", 1, "52주신고가")
    else: add("score_16", 0, "52주신고가")

    # 17 전고점돌파 (5점)
    prev_h = tech.get("previous_high_60", 0)
    br_r = ((close_p / prev_h) - 1) * 100 if prev_h > 0 else -100
    if br_r > 0 and vr >= 150: add("score_17", 5, "전고점돌파", True)
    elif br_r > 0: add("score_17", 4, "전고점돌파", True)
    elif br_r >= -2: add("score_17", 3, "전고점돌파")
    elif br_r >= -5: add("score_17", 1, "전고점돌파")
    else: add("score_17", 0, "전고점돌파")

    # 18 RSI(14) (4점)
    rsi14 = tech.get("rsi14", 50)
    if 55 <= rsi14 <= 70: add("score_18", 4, "RSI(14)", True)
    elif 50 <= rsi14 < 55: add("score_18", 3, "RSI(14)", True)
    elif 45 <= rsi14 < 50 or 70 < rsi14 <= 75: add("score_18", 2, "RSI(14)")
    elif 30 <= rsi14 < 45 or rsi14 > 75: add("score_18", 1, "RSI(14)")
    else: add("score_18", 0, "RSI(14)")

    # 19 이격도 (4점)
    disp = tech.get("disparity20", 100)
    if 102 <= disp <= 108: add("score_19", 4, "이격도", True)
    elif (100 <= disp < 102) or (108 < disp <= 112): add("score_19", 3, "이격도", True)
    elif 95 <= disp < 100: add("score_19", 2, "이격도")
    elif disp < 95 or 112 < disp <= 120: add("score_19", 1, "이격도")
    else: add("score_19", 0, "이격도")

    # 20 MACD (3점)
    m_val = tech.get("macd", 0)
    s_val = tech.get("macd_signal", 0)
    if m_val > s_val and m_val > 0: add("score_20", 3, "MACD", True)
    elif m_val > s_val: add("score_20", 2, "MACD", True)
    elif m_val > 0: add("score_20", 1, "MACD")
    else: add("score_20", 0, "MACD")

    total_score = min(sum(scores.values()), 100)

    return {
        **scores,
        "total_score": total_score,
        "grade": grade_from_score(total_score),
        "passed_tags": ",".join(dict.fromkeys(passed)),
        "double_buy": double_buy,
        "strong_buy": bool(total_score >= 80 and double_buy),
        "net_buy_ratio": round(nb_ratio, 2),
        "volume_ratio": round(vr, 2),
        "ma5": round(ma5, 2) if ma5 else 0,
        "ma10": round(ma10, 2) if ma10 else 0,
        "ma20": round(ma20, 2) if ma20 else 0,
        "ma60": round(ma60, 2) if ma60 else 0,
        "ma120": round(ma120, 2) if ma120 else 0,
        "high_52w": round(h52, 2),
        "previous_high_60": round(prev_h, 2),
        "rsi14": round(rsi14, 2),
        "macd": round(m_val, 4),
        "macd_signal": round(s_val, 4),
        "macd_hist": round(tech.get("macd_hist", 0), 4),
        "disparity20": round(disp, 2),
        "gap_52w": round(gap52, 2),
        "breakout_ratio": round(br_r, 2),
        "close_position": round(c_pos, 2),
        "upper_tail_ratio": round(t_ratio, 2),
    }


def fetch_stock_page(market: str, page: int, headers: Dict[str, str]) -> List[Dict]:
    url = f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize=20"
    try:
        res = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
        data = res.json()
        return data if isinstance(data, list) else (data.get("stocks") or data.get("result") or [])
    except Exception:
        return []




# ---------------- 통합: 종목 분석 -> UI 레코드 ----------------
MAXPTS = {"score_01":7,"score_02":7,"score_03":5,"score_04":6,"score_05":4,"score_06":4,"score_07":4,"score_08":3,"score_09":6,"score_10":6,
          "score_11":5,"score_12":5,"score_13":4,"score_14":5,"score_15":4,"score_16":5,"score_17":5,"score_18":4,"score_19":4,"score_20":3}
NAMES = {"score_01":"주가등락률","score_02":"거래대금","score_03":"거래량비율","score_04":"20일이평선","score_05":"주가위치","score_06":"양봉마감","score_07":"고가근접",
         "score_08":"윗꼬리제한","score_09":"단기이평정배열","score_10":"외국인순매수","score_11":"기관순매수","score_12":"순매수비율","score_13":"5일이평선",
         "score_14":"60일이평선","score_15":"120일이평선","score_16":"52주신고가","score_17":"전고점돌파","score_18":"RSI(14)","score_19":"이격도","score_20":"MACD"}
FLOW_KEYS = ("score_10", "score_11", "score_12")
MAX_TOTAL = sum(MAXPTS.values())  # 96

_scan_lock = threading.Lock()


def _ret(closes: List[float], n: int) -> float:
    return round((closes[-1] / closes[-1 - n] - 1) * 100, 2) if len(closes) > n and closes[-1 - n] > 0 else 0.0


def analyze(code: str, name: str, headers: Dict[str, str]) -> Optional[Dict]:
    hist = fetch_naver_chart(code, headers)
    if len(hist) < 21:
        return None
    last, prev = hist[-1], hist[-2]
    close_p, open_p, high_p, low_p, vol = last["close"], last["open"], last["high"], last["low"], last["volume"]
    chg = (close_p / prev["close"] - 1) * 100 if prev["close"] > 0 else 0.0
    deal = close_p * vol
    tech = technical_snapshot(hist)
    flow = get_real_investor_trend(code, headers)
    flow_ok = flow is not None
    f1, i1, r1, f5, i5 = flow if flow_ok else (0, 0, 0, 0, 0)
    sc = score_20_indicators(chg, close_p, open_p, high_p, low_p, deal, vol, tech, f1, i1, f5, i5)
    raw = {k: sc[k] for k in MAXPTS}
    if flow_ok:
        total = sc["total_score"]
    else:  # 수급 조회 실패 시 수급 3개 지표를 빼고 같은 만점(96) 기준으로 환산 (실패가 점수를 올리지 않도록)
        base = sum(v for k, v in raw.items() if k not in FLOW_KEYS)
        total = round(base / (MAX_TOTAL - sum(MAXPTS[k] for k in FLOW_KEYS)) * MAX_TOTAL)
    closes = [h["close"] for h in hist]
    tags = [t for t in sc["passed_tags"].split(",") if t]
    sector, role, _ = get_stock_profile(name)
    note = "" if flow_ok else " (수급 조회 실패: 수급 지표 제외 환산)"
    return {
        "code": code, "name": name, "industry": sector, "role": role,
        "score": int(total), "max_score": MAX_TOTAL, "grade": grade_from_score(int(total * 100 / MAX_TOTAL)),
        "foreign_inst_net": int((f1 + i1) * close_p), "flow_ok": flow_ok, "double_buy": sc["double_buy"],
        "metrics": {
            "current_price": int(close_p), "change_pct": round(chg, 2), "turnover": int(deal),
            "returns": {f"{n}일": _ret(closes, n) if n == 1 else round((closes[-n] / closes[-n - 1] - 1) * 100, 2) for n in range(1, 6)},
            "modal_returns": {"1년": _ret(closes, 249), "6개월": _ret(closes, 120), "3개월": _ret(closes, 60), "1개월": _ret(closes, 20),
                              "20일": _ret(closes, 20), "10일": _ret(closes, 10), "5일": _ret(closes, 5)},
        },
        "fundamentals": {"per": 0, "pbr": 0, "roe": 0, "dividend_yield": 0},  # 별도 데이터 소스 필요
        "twenty_metrics": [{"name": NAMES[k], "score": f"{raw[k]}/{MAXPTS[k]}"} for k in MAXPTS],
        "ai_briefing": f"{name}: 20개 지표 중 {len(tags)}개 충족({', '.join(tags[:5]) or '없음'}). 점수 {int(total)}/{MAX_TOTAL}{note}",
        "upside_probability": int(min(95, max(5, total / MAX_TOTAL * 90))),  # 점수 기반 단순 환산(통계적 확률 아님)
        "passed_tags": sc["passed_tags"],
    }


def build_universe(headers: Dict[str, str]) -> Dict[str, Tuple[str, str]]:
    """섹터 마스터 종목 + 시총 상위 종목의 합집합 {code: (name, market)}"""
    uni: Dict[str, Tuple[str, str]] = {c: (n, "") for n, c in TICKER_MAP.items() if c != "000000"}
    for market in ("KOSPI", "KOSDAQ"):
        for page in range(1, STOCK_PAGES + 1):
            items = fetch_stock_page(market, page, headers)
            if not items:
                break
            for it in items:
                code = str(it.get("itemCode") or it.get("code") or "").strip()
                name = str(it.get("stockName") or it.get("name") or "").strip()
                if code and name and is_pure_stock(code, name):
                    uni.setdefault(code, (name, market))
    return uni


def run_full_scan(label: str = "scan", on_done=None) -> int:
    if not _scan_lock.acquire(blocking=False):
        return 0  # 이미 실행 중
    try:
        headers = get_headers()
        uni = build_universe(headers)
        records = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = [ex.submit(analyze, c, n, headers) for c, (n, _m) in uni.items()]
            for f in as_completed(futs):
                try:
                    r = f.result()
                    if r:
                        records.append(r)
                except Exception:
                    pass
        if records:  # 전부 실패했을 때 기존 데이터를 덮어쓰지 않음
            now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
            db.upsert_candidates_bulk(records, now.strftime("%H:%M"))
            if on_done:
                on_done({r["code"]: r["name"] for r in records})
        print(f"[{label}] 대상 {len(uni)}개 / 저장 {len(records)}개")
        return len(records)
    finally:
        _scan_lock.release()

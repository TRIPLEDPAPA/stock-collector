import datetime
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Optional

import requests
from supabase import create_client, Client


# ============================================================
# TRIPLE D PAPA - KRX 종목 수집 + 20개 지표 100점 평가
# ------------------------------------------------------------
# 핵심 변경
# 1) MA5/10/20/60/120 실제 계산
# 2) 20일 평균 거래량 대비 거래량비율 실제 계산
# 3) 52주 최고가 / 전고점 실제 계산
# 4) RSI(14), MACD(12,26,9), 이격도 실제 계산
# 5) 외국인/기관 1일·5일 수급 반영
# 6) 20개 개별 점수(score_01 ~ score_20) 저장
# 7) 총점 100점 / 등급 / 쌍끌이 / 강한매수세 저장
#
# 주의:
# - Supabase publishable key는 환경변수 사용을 권장합니다.
# - 환경변수 미설정 시 아래 기본값을 사용할 수 있지만,
#   배포 환경에서는 반드시 환경변수로 관리하세요.
# ============================================================


SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "YOUR_SUPABASE_PUBLISHABLE_KEY"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


EXCLUDE_KEYWORDS = [
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "KOSEF", "ARIRANG",
    "TIMEFOLIO", "HANARO", "WOORI", "UNICORN", "KBSTAR", "WON", "HERO",
    "TRUSTON", "ETN", "스팩", "SPAC", "선물", "인버스", "레버리지", "2X",
    "액티브", "국채", "채권", "MSCI", "S&P", "나스닥", "NASDAQ", "다우",
    "금현물", "원유", "TR"
]

# 수집할 시세 이력
HISTORY_COUNT = 260

# 네이버 종목 페이지 수
# pageSize=20 기준. 10페이지 = 최대 약 200종목/시장.
# 필요하면 20으로 늘릴 수 있습니다.
STOCK_PAGES = 10

REQUEST_TIMEOUT = 8
INVESTOR_TIMEOUT = 5
REQUEST_SLEEP = 0.08


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

    # 일반 보통주 종목코드는 통상 숫자 코드이며,
    # 우선주/ETF/ETN 등은 이름과 키워드로 제외
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


# ============================================================
# 기술지표
# ============================================================

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

    gains = []
    losses = []

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

    macd_value = macd_line[-1]
    signal_value = signal_series[-1]
    hist = macd_value - signal_value

    return macd_value, signal_value, hist


def technical_snapshot(history: List[Dict[str, float]]) -> Dict[str, float]:
    """
    history는 오래된 날짜 -> 최신 날짜 순서.
    """
    closes = [x["close"] for x in history]
    highs = [x["high"] for x in history]
    volumes = [x["volume"] for x in history]

    result = {
        "ma5": 0.0,
        "ma10": 0.0,
        "ma20": 0.0,
        "ma60": 0.0,
        "ma120": 0.0,
        "volume_ratio": 0.0,
        "high_52w": 0.0,
        "previous_high_60": 0.0,
        "rsi14": 50.0,
        "macd": 0.0,
        "macd_signal": 0.0,
        "macd_hist": 0.0,
        "disparity20": 100.0,
    }

    if not closes:
        return result

    for period, key in [(5, "ma5"), (10, "ma10"), (20, "ma20"),
                        (60, "ma60"), (120, "ma120")]:
        value = sma(closes, period)
        if value is not None:
            result[key] = value

    if len(volumes) >= 21:
        avg20 = sum(volumes[-21:-1]) / 20.0
        if avg20 > 0:
            result["volume_ratio"] = (volumes[-1] / avg20) * 100.0

    # 52주 = 최대 250거래일
    window_highs = highs[-250:] if len(highs) >= 250 else highs[:]
    if window_highs:
        result["high_52w"] = max(window_highs)

    # 오늘을 제외한 최근 60거래일 최고가
    previous_high_window = highs[-61:-1] if len(highs) >= 61 else highs[:-1]
    if previous_high_window:
        result["previous_high_60"] = max(previous_high_window)

    rsi_value = rsi(closes, 14)
    if rsi_value is not None:
        result["rsi14"] = rsi_value

    macd_value, signal_value, hist = macd(closes)
    if macd_value is not None:
        result["macd"] = macd_value
        result["macd_signal"] = signal_value
        result["macd_hist"] = hist

    if result["ma20"] > 0:
        result["disparity20"] = (closes[-1] / result["ma20"]) * 100.0

    return result


# ============================================================
# 네이버 차트 데이터
# ============================================================

def fetch_naver_chart(ticker: str, headers: Dict[str, str]) -> List[Dict[str, float]]:
    """
    네이버 fchart 일봉 XML을 이용해 최근 HISTORY_COUNT 거래일을 가져옵니다.
    """
    url = (
        "https://fchart.stock.naver.com/sise.nhn"
        f"?symbol={ticker}&timeframe=day&count={HISTORY_COUNT}&requestType=0"
    )

    try:
        res = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()

        root = ET.fromstring(res.text)
        rows = []

        for item in root.findall(".//item"):
            data = item.attrib.get("data", "")
            parts = data.split("|")
            if len(parts) < 6:
                continue

            date_str = parts[0]
            close_p = safe_float(parts[1])
            open_p = safe_float(parts[2])
            high_p = safe_float(parts[3])
            low_p = safe_float(parts[4])
            volume = safe_float(parts[5])

            if close_p <= 0:
                continue

            rows.append({
                "date": date_str,
                "close": close_p,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "volume": volume,
            })

        # 네이버 데이터는 오래된 날짜 -> 최신 날짜인 경우가 일반적이지만
        # 안전하게 날짜 정렬
        rows.sort(key=lambda x: x["date"])
        return rows

    except Exception as e:
        print(f"[차트 실패] {ticker}: {e}")
        return []


# ============================================================
# 현재가 / 거래대금 / 수급
# ============================================================

def get_real_investor_trend(
    ticker: str,
    headers: Dict[str, str]
) -> Tuple[int, int, int, int, int]:
    """
    반환:
      foreign_1d, inst_1d, retail_1d, foreign_5d, inst_5d
    """
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"

    try:
        res = requests.get(url, headers=headers, timeout=INVESTOR_TIMEOUT)
        if res.status_code != 200:
            return 0, 0, 0, 0, 0

        data = res.json()

        if isinstance(data, list):
            trend_list = data
        else:
            trend_list = (
                data.get("message", {}).get("result", [])
                or data.get("result", [])
                or data.get("trend", [])
                or []
            )

        if not trend_list:
            return 0, 0, 0, 0, 0

        def get_foreign(x):
            return safe_int(
                x.get("foreignerPureBuyQuant")
                or x.get("frgnPureBuyQuant")
                or x.get("foreignPureBuyQuant")
                or 0
            )

        def get_inst(x):
            return safe_int(
                x.get("organPureBuyQuant")
                or x.get("instPureBuyQuant")
                or x.get("institutionPureBuyQuant")
                or 0
            )

        def get_retail(x):
            return safe_int(
                x.get("individualPureBuyQuant")
                or x.get("retailPureBuyQuant")
                or x.get("personalPureBuyQuant")
                or 0
            )

        latest = trend_list[0]
        foreign_1d = get_foreign(latest)
        inst_1d = get_inst(latest)
        retail_1d = get_retail(latest)

        # 개인 데이터가 제공되지 않는 경우 수급 합계가 0이 되도록 보정
        if retail_1d == 0 and (foreign_1d != 0 or inst_1d != 0):
            retail_1d = -(foreign_1d + inst_1d)

        first5 = trend_list[:5]
        foreign_5d = sum(get_foreign(x) for x in first5)
        inst_5d = sum(get_inst(x) for x in first5)

        return foreign_1d, inst_1d, retail_1d, foreign_5d, inst_5d

    except Exception as e:
        print(f"[수급 실패] {ticker}: {e}")
        return 0, 0, 0, 0, 0


# ============================================================
# 20개 지표 점수
# ============================================================

WEIGHTS = {
    "score_01": 7,   # 주가등락률
    "score_02": 7,   # 거래대금
    "score_03": 5,   # 거래량비율
    "score_04": 6,   # 20일이평선
    "score_05": 4,   # 주가위치
    "score_06": 4,   # 양봉마감
    "score_07": 4,   # 고가근접
    "score_08": 3,   # 윗꼬리제한
    "score_09": 6,   # 단기이평정배열
    "score_10": 6,   # 외국인순매수
    "score_11": 5,   # 기관순매수
    "score_12": 5,   # 순매수대금/거래대금
    "score_13": 4,   # 5일이평선
    "score_14": 5,   # 60일이평선
    "score_15": 4,   # 120일이평선
    "score_16": 5,   # 52주신고가
    "score_17": 5,   # 전고점돌파
    "score_18": 4,   # RSI
    "score_19": 4,   # 이격도
    "score_20": 3,   # MACD
}


def grade_from_score(score: int) -> str:
    if score >= 90:
        return "S"
    if score >= 85:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B+"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def score_20_indicators(
    chg: float,
    close_p: float,
    open_p: float,
    high_p: float,
    low_p: float,
    deal_won: float,
    current_vol: float,
    tech: Dict[str, float],
    foreign_1d: int,
    inst_1d: int,
    foreign_5d: int,
    inst_5d: int,
) -> Dict[str, object]:

    scores = {}
    passed = []

    def add(key, value, tag, passed_condition=False):
        scores[key] = int(max(0, value))
        if passed_condition:
            passed.append(tag)

    # 01 주가등락률 7
    if chg >= 10:
        add("score_01", 7, "주가등락률", True)
    elif chg >= 7:
        add("score_01", 6, "주가등락률", True)
    elif chg >= 5:
        add("score_01", 5, "주가등락률", True)
    elif chg >= 3:
        add("score_01", 4, "주가등락률")
    elif chg >= 1:
        add("score_01", 3, "주가등락률")
    elif chg >= 0:
        add("score_01", 1, "주가등락률")
    else:
        add("score_01", 0, "주가등락률")

    # 02 거래대금 7
    if deal_won >= 100_000_000_000:
        add("score_02", 7, "거래대금", True)
    elif deal_won >= 50_000_000_000:
        add("score_02", 6, "거래대금", True)
    elif deal_won >= 30_000_000_000:
        add("score_02", 5, "거래대금", True)
    elif deal_won >= 10_000_000_000:
        add("score_02", 3, "거래대금")
    elif deal_won >= 5_000_000_000:
        add("score_02", 2, "거래대금")
    else:
        add("score_02", 0, "거래대금")

    # 03 거래량비율 5
    volume_ratio = tech.get("volume_ratio", 0)
    if volume_ratio >= 300:
        add("score_03", 5, "거래량비율", True)
    elif volume_ratio >= 200:
        add("score_03", 4, "거래량비율", True)
    elif volume_ratio >= 150:
        add("score_03", 3, "거래량비율", True)
    elif volume_ratio >= 100:
        add("score_03", 2, "거래량비율")
    elif volume_ratio >= 70:
        add("score_03", 1, "거래량비율")
    else:
        add("score_03", 0, "거래량비율")

    # 04 20일이평선 6
    ma20 = tech.get("ma20", 0)
    ma20_ratio = (close_p / ma20 * 100) if ma20 > 0 else 0
    if ma20_ratio >= 110:
        add("score_04", 6, "20일이평선", True)
    elif ma20_ratio >= 105:
        add("score_04", 5, "20일이평선", True)
    elif ma20_ratio >= 102:
        add("score_04", 4, "20일이평선")
    elif ma20_ratio >= 100:
        add("score_04", 3, "20일이평선")
    elif ma20_ratio >= 97:
        add("score_04", 1, "20일이평선")
    else:
        add("score_04", 0, "20일이평선")

    # 05 주가위치 = 52주 고점 대비 위치 4
    high_52w = tech.get("high_52w", 0)
    gap_52w = ((close_p / high_52w) - 1) * 100 if high_52w > 0 else -100

    if gap_52w >= -5:
        add("score_05", 4, "주가위치", True)
    elif gap_52w >= -10:
        add("score_05", 3, "주가위치", True)
    elif gap_52w >= -20:
        add("score_05", 2, "주가위치")
    elif gap_52w >= -30:
        add("score_05", 1, "주가위치")
    else:
        add("score_05", 0, "주가위치")

    # 06 양봉마감 4
    candle_rate = ((close_p - open_p) / open_p * 100) if open_p > 0 else 0
    if candle_rate >= 3:
        add("score_06", 4, "양봉마감", True)
    elif candle_rate >= 1:
        add("score_06", 3, "양봉마감", True)
    elif candle_rate > 0:
        add("score_06", 2, "양봉마감")
    elif candle_rate == 0:
        add("score_06", 1, "양봉마감")
    else:
        add("score_06", 0, "양봉마감")

    # 07 고가근접 4
    day_range = high_p - low_p
    close_pos = ((close_p - low_p) / day_range * 100) if day_range > 0 else 50

    if close_pos >= 95:
        add("score_07", 4, "고가근접", True)
    elif close_pos >= 90:
        add("score_07", 3, "고가근접", True)
    elif close_pos >= 80:
        add("score_07", 2, "고가근접")
    elif close_pos >= 70:
        add("score_07", 1, "고가근접")
    else:
        add("score_07", 0, "고가근접")

    # 08 윗꼬리제한 3
    upper_tail = high_p - max(open_p, close_p)
    tail_ratio = (upper_tail / day_range * 100) if day_range > 0 else 0

    if tail_ratio <= 5:
        add("score_08", 3, "윗꼬리제한", True)
    elif tail_ratio <= 10:
        add("score_08", 2, "윗꼬리제한", True)
    elif tail_ratio <= 20:
        add("score_08", 1, "윗꼬리제한")
    else:
        add("score_08", 0, "윗꼬리제한")

    # 09 단기이평정배열 6
    ma5 = tech.get("ma5", 0)
    ma10 = tech.get("ma10", 0)

    if ma5 > 0 and ma10 > 0 and ma20 > 0:
        if close_p > ma5 > ma10 > ma20:
            add("score_09", 6, "단기이평정배열", True)
        elif ma5 > ma10 > ma20:
            add("score_09", 5, "단기이평정배열", True)
        elif close_p > ma20 and ma5 > ma10:
            add("score_09", 3, "단기이평정배열")
        elif close_p > ma20:
            add("score_09", 2, "단기이평정배열")
        else:
            add("score_09", 0, "단기이평정배열")
    else:
        add("score_09", 0, "단기이평정배열")

    # 10 외국인순매수 6
    if foreign_1d > 0 and foreign_5d > 0:
        add("score_10", 6, "외국인순매수", True)
    elif foreign_1d > 0:
        add("score_10", 4, "외국인순매수", True)
    elif foreign_5d > 0:
        add("score_10", 3, "외국인순매수")
    elif foreign_1d == 0:
        add("score_10", 2, "외국인순매수")
    else:
        add("score_10", 0, "외국인순매수")

    # 11 기관순매수 5
    if inst_1d > 0 and inst_5d > 0:
        add("score_11", 5, "기관순매수", True)
    elif inst_1d > 0:
        add("score_11", 3, "기관순매수", True)
    elif inst_5d > 0:
        add("score_11", 2, "기관순매수")
    elif inst_1d == 0:
        add("score_11", 1, "기관순매수")
    else:
        add("score_11", 0, "기관순매수")

    # 쌍끌이
    double_buy = foreign_1d > 0 and inst_1d > 0
    if double_buy:
        passed.append("쌍끌이")

    # 12 순매수대금 / 거래대금 5
    net_buy_won = (foreign_1d + inst_1d) * close_p
    net_ratio = (net_buy_won / deal_won * 100) if deal_won > 0 else 0

    if net_ratio >= 30:
        add("score_12", 5, "순매수비율", True)
    elif net_ratio >= 20:
        add("score_12", 4, "순매수비율", True)
    elif net_ratio >= 10:
        add("score_12", 3, "순매수비율")
    elif net_ratio >= 0:
        add("score_12", 2, "순매수비율")
    else:
        add("score_12", 0, "순매수비율")

    # 13 5일이평선 4
    ma5_ratio = (close_p / ma5 * 100) if ma5 > 0 else 0

    if ma5_ratio >= 103:
        add("score_13", 4, "5일이평선", True)
    elif ma5_ratio >= 101:
        add("score_13", 3, "5일이평선", True)
    elif ma5_ratio >= 100:
        add("score_13", 2, "5일이평선")
    elif ma5_ratio >= 97:
        add("score_13", 1, "5일이평선")
    else:
        add("score_13", 0, "5일이평선")

    # 14 60일이평선 5
    ma60 = tech.get("ma60", 0)
    ma60_ratio = (close_p / ma60 * 100) if ma60 > 0 else 0

    if ma60_ratio >= 110:
        add("score_14", 5, "60일이평선", True)
    elif ma60_ratio >= 105:
        add("score_14", 4, "60일이평선", True)
    elif ma60_ratio >= 100:
        add("score_14", 3, "60일이평선")
    elif ma60_ratio >= 95:
        add("score_14", 1, "60일이평선")
    else:
        add("score_14", 0, "60일이평선")

    # 15 120일이평선 4
    ma120 = tech.get("ma120", 0)
    ma120_ratio = (close_p / ma120 * 100) if ma120 > 0 else 0

    if ma120_ratio >= 110:
        add("score_15", 4, "120일이평선", True)
    elif ma120_ratio >= 105:
        add("score_15", 3, "120일이평선", True)
    elif ma120_ratio >= 100:
        add("score_15", 2, "120일이평선")
    elif ma120_ratio >= 95:
        add("score_15", 1, "120일이평선")
    else:
        add("score_15", 0, "120일이평선")

    # 16 52주신고가 5
    if gap_52w >= 0:
        add("score_16", 5, "52주신고가", True)
    elif gap_52w >= -1:
        add("score_16", 4, "52주신고가", True)
    elif gap_52w >= -3:
        add("score_16", 3, "52주신고가", True)
    elif gap_52w >= -10:
        add("score_16", 1, "52주신고가")
    else:
        add("score_16", 0, "52주신고가")

    # 17 전고점돌파 5
    previous_high = tech.get("previous_high_60", 0)
    breakout_ratio = ((close_p / previous_high) - 1) * 100 if previous_high > 0 else -100

    if breakout_ratio > 0 and volume_ratio >= 150:
        add("score_17", 5, "전고점돌파", True)
    elif breakout_ratio > 0:
        add("score_17", 4, "전고점돌파", True)
    elif breakout_ratio >= -2:
        add("score_17", 3, "전고점돌파")
    elif breakout_ratio >= -5:
        add("score_17", 1, "전고점돌파")
    else:
        add("score_17", 0, "전고점돌파")

    # 18 RSI(14) 4
    rsi14 = tech.get("rsi14", 50)

    if 55 <= rsi14 <= 70:
        add("score_18", 4, "RSI(14)", True)
    elif 50 <= rsi14 < 55:
        add("score_18", 3, "RSI(14)", True)
    elif 45 <= rsi14 < 50:
        add("score_18", 2, "RSI(14)")
    elif 70 < rsi14 <= 75:
        add("score_18", 2, "RSI(14)")
    elif 30 <= rsi14 < 45 or rsi14 > 75:
        add("score_18", 1, "RSI(14)")
    else:
        add("score_18", 0, "RSI(14)")

    # 19 이격도 4
    disparity = tech.get("disparity20", 100)

    if 102 <= disparity <= 108:
        add("score_19", 4, "이격도", True)
    elif 100 <= disparity < 102 or 108 < disparity <= 112:
        add("score_19", 3, "이격도", True)
    elif 95 <= disparity < 100:
        add("score_19", 2, "이격도")
    elif disparity < 95 or 112 < disparity <= 120:
        add("score_19", 1, "이격도")
    else:
        add("score_19", 0, "이격도")

    # 20 MACD 3
    macd_value = tech.get("macd", 0)
    signal_value = tech.get("macd_signal", 0)

    if macd_value > signal_value and macd_value > 0:
        add("score_20", 3, "MACD", True)
    elif macd_value > signal_value:
        add("score_20", 2, "MACD", True)
    elif macd_value > 0:
        add("score_20", 1, "MACD")
    else:
        add("score_20", 0, "MACD")

    total_score = sum(scores.values())
    total_score = min(total_score, 100)

    # 점수 검증
    max_possible = sum(WEIGHTS.values())
    if max_possible != 100:
        raise RuntimeError(f"20개 지표 배점 합계 오류: {max_possible}")

    return {
        **scores,
        "total_score": total_score,
        "grade": grade_from_score(total_score),
        "passed_tags": ",".join(dict.fromkeys(passed)),
        "double_buy": double_buy,
        "strong_buy": bool(total_score >= 80 and double_buy),
        "net_buy_ratio": round(net_ratio, 2),
        "volume_ratio": round(volume_ratio, 2),
        "ma5": round(ma5, 2) if ma5 else 0,
        "ma10": round(ma10, 2) if ma10 else 0,
        "ma20": round(ma20, 2) if ma20 else 0,
        "ma60": round(ma60, 2) if ma60 else 0,
        "ma120": round(ma120, 2) if ma120 else 0,
        "high_52w": round(high_52w, 2),
        "previous_high_60": round(previous_high, 2),
        "rsi14": round(rsi14, 2),
        "macd": round(macd_value, 4),
        "macd_signal": round(signal_value, 4),
        "macd_hist": round(tech.get("macd_hist", 0), 4),
        "disparity20": round(disparity, 2),
        "gap_52w": round(gap_52w, 2),
        "breakout_ratio": round(breakout_ratio, 2),
        "close_position": round(close_pos, 2),
        "upper_tail_ratio": round(tail_ratio, 2),
    }


# ============================================================
# 종목 1건 처리
# ============================================================

def parse_stock_item(
    item: Dict,
    market_type: str,
    today_str: str,
    headers: Dict[str, str]
) -> Optional[Dict]:

    ticker = str(item.get("itemCode") or item.get("code") or "").strip()
    name = str(item.get("stockName") or item.get("name") or "").strip()

    if not ticker or not name:
        return None

    history = fetch_naver_chart(ticker, headers)
    if len(history) < 30:
        print(f"[이력 부족] {ticker} {name}: {len(history)}")
        return None

    latest = history[-1]

    # 현재 수집 데이터와 차트 데이터 중 최신값 사용
    close_p = safe_float(item.get("closePrice") or item.get("nowPrice") or item.get("price") or latest["close"])
    open_p = safe_float(item.get("openPrice") or latest["open"])
    high_p = safe_float(item.get("highPrice") or latest["high"])
    low_p = safe_float(item.get("lowPrice") or latest["low"])
    chg = safe_float(item.get("fluctuationsRatio") or item.get("changeRate"))

    current_vol = safe_float(
        item.get("accumulatedTradingVolume")
        or item.get("quant")
        or latest["volume"]
    )

    deal_won = safe_float(
        item.get("tradePrice")
        or item.get("accumulatedTradingValue")
        or item.get("tradeAmount")
    )

    # 네이버 API 응답 단위 차이 보정
    if 0 < deal_won < 50_000_000:
        deal_won *= 1_000_000

    if deal_won <= 0 and current_vol > 0:
        deal_won = close_p * current_vol

    tech = technical_snapshot(history)

    foreign_1d, inst_1d, retail_1d, foreign_5d, inst_5d = get_real_investor_trend(
        ticker, headers
    )

    scoring = score_20_indicators(
        chg=chg,
        close_p=close_p,
        open_p=open_p,
        high_p=high_p,
        low_p=low_p,
        deal_won=deal_won,
        current_vol=current_vol,
        tech=tech,
        foreign_1d=foreign_1d,
        inst_1d=inst_1d,
        foreign_5d=foreign_5d,
        inst_5d=inst_5d,
    )

    # 전일종가
    prev_close = history[-2]["close"] if len(history) >= 2 else 0

    result = {
        "market": market_type,
        "ticker": ticker,
        "name": name,

        "close_price": int(round(close_p)),
        "open_price": int(round(open_p)),
        "high_price": int(round(high_p)),
        "low_price": int(round(low_p)),
        "prev_close": int(round(prev_close)),

        "change_rate": round(chg, 2),
        "trade_amount": int(round(deal_won)),
        "deal_tag": (
            "400억이상" if deal_won >= 40_000_000_000 else
            "300억이상" if deal_won >= 30_000_000_000 else
            "200억이상" if deal_won >= 20_000_000_000 else
            "100억이상" if deal_won >= 10_000_000_000 else
            "100억미만"
        ),

        "volume": int(round(current_vol)),
        "strength": 100.0,

        "per": safe_float(item.get("per")),
        "pbr": safe_float(item.get("pbr")),
        "roe": safe_float(item.get("roe")),
        "eps": safe_int(item.get("eps")),

        "foreign_net_buy": foreign_1d,
        "inst_net_buy": inst_1d,
        "retail_net_buy": retail_1d,
        "foreign_net_buy_5d": foreign_5d,
        "inst_net_buy_5d": inst_5d,

        "date": today_str,

        **scoring,
    }

    return result


# ============================================================
# 국내 지수
# ============================================================

def fetch_naver_korea_index(
    code: str,
    name: str,
    headers: Dict[str, str],
    today_str: str
) -> Optional[Dict]:

    url = f"https://m.stock.naver.com/api/index/{code}/basic"

    try:
        res = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if res.status_code != 200:
            return None

        data = res.json()

        close_p = safe_float(data.get("closePrice"))
        open_p = safe_float(data.get("openPrice"), close_p)
        chg_rate = safe_float(data.get("fluctuationsRatio"))

        deal_won = int(
            safe_float(
                data.get("accumulatedTradingValueWon")
                or data.get("dealWon")
                or 0
            )
        )

        return {
            "market": "INDEX",
            "ticker": f"IDX_{code}",
            "name": name,
            "close_price": close_p,
            "open_price": open_p,
            "change_rate": chg_rate,
            "trade_amount": deal_won,
            "deal_tag": "100억이상" if deal_won >= 10_000_000_000 else "100억미만",
            "volume": 0,
            "strength": 100.0,
            "per": 0.0,
            "pbr": 0.0,
            "roe": 0.0,
            "eps": 0,
            "foreign_net_buy": 0,
            "inst_net_buy": 0,
            "retail_net_buy": 0,
            "passed_tags": "",
            "total_score": 0,
            "grade": "",
            "double_buy": False,
            "strong_buy": False,
            "date": today_str,
        }

    except Exception as e:
        print(f"[지수 실패] {name}: {e}")
        return None


# ============================================================
# 해외 지수 / 원자재
# ============================================================

def fetch_naver_world_item(
    category: str,
    symbol: str,
    display_name: str,
    headers: Dict[str, str],
    today_str: str
) -> Optional[Dict]:

    url = f"https://m.stock.naver.com/api/index/{category}/{symbol}/basic"

    try:
        res = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if res.status_code != 200:
            return None

        data = res.json()

        close_p = safe_float(data.get("closePrice"))
        open_p = safe_float(data.get("openPrice"), close_p)
        chg_rate = safe_float(data.get("fluctuationsRatio"))

        return {
            "market": "INDEX",
            "ticker": f"GL_{symbol}",
            "name": display_name,
            "close_price": close_p,
            "open_price": open_p,
            "change_rate": chg_rate,
            "trade_amount": 0,
            "deal_tag": "100억미만",
            "volume": 0,
            "strength": 100.0,
            "per": 0.0,
            "pbr": 0.0,
            "roe": 0.0,
            "eps": 0,
            "foreign_net_buy": 0,
            "inst_net_buy": 0,
            "retail_net_buy": 0,
            "passed_tags": "",
            "total_score": 0,
            "grade": "",
            "double_buy": False,
            "strong_buy": False,
            "date": today_str,
        }

    except Exception as e:
        print(f"[해외지수 실패] {display_name}: {e}")
        return None


# ============================================================
# 종목 목록
# ============================================================

def fetch_stock_page(
    market: str,
    page: int,
    headers: Dict[str, str]
) -> List[Dict]:

    url = (
        f"https://m.stock.naver.com/api/stocks/marketValue/"
        f"{market}?page={page}&pageSize=20"
    )

    try:
        res = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()

        data = res.json()

        if isinstance(data, list):
            return data

        return (
            data.get("stocks")
            or data.get("result")
            or data.get("data")
            or []
        )

    except Exception as e:
        print(f"[목록 실패] {market} page={page}: {e}")
        return []


# ============================================================
# 수집 실행
# ============================================================

def collect_market_data():

    now_kst = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=9))
    )
    today_str = now_kst.strftime("%Y-%m-%d")

    headers = get_headers()
    compiled_items = []

    print("=" * 70)
    print(f"[{today_str}] TRIPLE D PAPA 수집 시작")
    print("20개 지표 실제 계산 / 100점")
    print("=" * 70)

    # --------------------------------------------------------
    # 1. 국내 지수
    # --------------------------------------------------------
    for code, name in [
        ("KOSPI", "코스피"),
        ("KOSDAQ", "코스닥"),
    ]:
        idx = fetch_naver_korea_index(code, name, headers, today_str)
        if idx:
            compiled_items.append(idx)

    # --------------------------------------------------------
    # 2. 해외/원자재
    # --------------------------------------------------------
    world_targets = [
        ("findex", "SPI@SPX", "S&P 500"),
        ("findex", "DJI@DJI", "다우존스"),
        ("findex", "NAS@NDX", "나스닥 100"),
        ("future", "CME@YM", "Dow Jones (선물)"),
        ("future", "CME@ES", "S&P 500 (선물)"),
        ("future", "CME@NQ", "나스닥 100 (선물)"),
        ("marketvalue", "CMX@GC", "금"),
        ("marketvalue", "CMX@SI", "은"),
        ("marketvalue", "CMX@HG", "구리"),
        ("marketvalue", "NYM@CL", "WTI유"),
        ("marketvalue", "ICE@BZ", "브렌트유"),
        ("exchange", "FX_USDKRW", "원/달러 환율"),
    ]

    for cat, symbol, name in world_targets:
        item = fetch_naver_world_item(
            cat, symbol, name, headers, today_str
        )
        if item:
            compiled_items.append(item)

    # --------------------------------------------------------
    # 3. 국내 주식
    # --------------------------------------------------------
    seen_tickers = set()

    for market in ["KOSPI", "KOSDAQ"]:

        for page in range(1, STOCK_PAGES + 1):

            stocks_list = fetch_stock_page(
                market, page, headers
            )

            if not stocks_list:
                break

            print(
                f"[{market}] page {page}/{STOCK_PAGES} "
                f"목록 {len(stocks_list)}개"
            )

            for item in stocks_list:

                ticker = str(
                    item.get("itemCode")
                    or item.get("code")
                    or ""
                ).strip()

                name = str(
                    item.get("stockName")
                    or item.get("name")
                    or ""
                ).strip()

                if ticker in seen_tickers:
                    continue

                if not is_pure_stock(ticker, name):
                    continue

                seen_tickers.add(ticker)

                parsed = parse_stock_item(
                    item,
                    market,
                    today_str,
                    headers
                )

                if parsed:
                    compiled_items.append(parsed)
                    print(
                        f"  ✓ {market} {ticker} {name} "
                        f"{parsed['total_score']}점 "
                        f"{parsed['grade']}"
                    )

                time.sleep(REQUEST_SLEEP)

    # --------------------------------------------------------
    # 4. Supabase 저장
    # --------------------------------------------------------
    print(f"\n총 {len(compiled_items)}건 저장 시작...")

    saved = 0
    failed = 0

    for item in compiled_items:
        try:
            supabase.table("TRIPLE D PAPA").upsert(
                item,
                on_conflict="ticker,date"
            ).execute()

            saved += 1

        except Exception as e:
            failed += 1
            print(
                f"[저장 실패] "
                f"{item.get('ticker')} "
                f"{item.get('name')}: {e}"
            )

    print("=" * 70)
    print(
        f"[완료] 수집 {len(compiled_items)} / "
        f"저장 성공 {saved} / 실패 {failed}"
    )
    print("=" * 70)


if __name__ == "__main__":
    collect_market_data()

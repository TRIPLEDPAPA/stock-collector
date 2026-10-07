"""실시간 공시/공지 수집기 (DART OpenAPI). 환경변수 DART_API_KEY 필요: https://opendart.fss.or.kr"""
from __future__ import annotations
import datetime as dt
import os
import requests
import db

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
VIEW_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
KST = dt.timezone(dt.timedelta(hours=9))

C_RED = "text-red-400 bg-red-950/50 border-red-800/50"
C_BLUE = "text-blue-400 bg-blue-950/50 border-blue-800/50"
C_GREEN = "text-emerald-400 bg-emerald-950/50 border-emerald-800/50"
C_AMBER = "text-amber-300 bg-amber-950/50 border-amber-700/50"
C_GRAY = "text-slate-400 bg-slate-800/60 border-slate-700/50"

BAD = ("불성실공시", "상장폐지", "횡령", "배임", "거래정지", "감사의견", "관리종목", "회생", "부도", "감자결정", "투자경고", "투자위험")
PERF = ("영업(잠정)실적", "매출액또는손익구조", "단일판매", "공급계약", "수주")
MAJOR = ("최대주주", "합병", "분할", "유상증자", "무상증자", "전환사채", "신주인수권", "교환사채", "자기주식", "배당", "특허", "자금조달")


def classify(report_nm: str, flr_nm: str = "") -> tuple[str, str, str, int]:
    """-> (category, tag, tag_color, is_alert)"""
    t = report_nm.replace(" ", "")
    if "국민연금" in flr_nm or "연금" in t:
        return "연금관련", "연금", C_AMBER, 1
    if "시장안내" in t or "시장조치" in t:
        return "시장안내", "시장안내", C_GRAY, 0
    if any(k in t for k in BAD):
        return "주요공시", "악재", C_RED, 1
    if any(k in t for k in PERF):
        return "실적·수주", "실적·수주", C_GREEN, 0
    if any(k in t for k in MAJOR):
        return "주요공시", "주요", C_BLUE, 0
    return "기타", "공시", C_GRAY, 0


def _fetch(key: str, day: str, page: int, count: int = 100) -> dict:
    r = requests.get(LIST_URL, params={"crtfc_key": key, "bgn_de": day, "end_de": day, "page_no": page,
                                       "page_count": count, "sort": "date", "sort_mth": "desc"}, timeout=8)
    r.raise_for_status()
    return r.json()


def sync(backfill: bool = False) -> int:
    """오늘 공시를 가져와 DB에 저장. backfill=True면 전체 페이지, 아니면 최신 2페이지(200건)만. 새 건수 반환"""
    key = os.getenv("DART_API_KEY", "").strip()
    if not key:
        db.set_meta("dart_status", "no_key")
        return 0
    now = dt.datetime.now(KST)
    day = now.strftime("%Y%m%d")
    hhmm = now.strftime("%H:%M")
    new = 0
    try:
        page, total_page = 1, 1
        while page <= (min(total_page, 30) if backfill else min(total_page, 2)):
            js = _fetch(key, day, page)
            if js.get("status") == "013":  # 조회된 데이터 없음
                break
            if js.get("status") != "000":
                db.set_meta("dart_status", f"error:{js.get('status')} {js.get('message','')}")
                return new
            total_page = int(js.get("total_page") or 1)
            rows = []
            for it in js.get("list", []):
                if it.get("corp_cls") not in ("Y", "K"):  # 코스피/코스닥만
                    continue
                rep, flr, corp = it.get("report_nm", "").strip(), it.get("flr_nm", ""), it.get("corp_name", "")
                cat, tag, color, alert = classify(rep, flr)
                dtp = it.get("rcept_dt", day)
                rows.append({"date_md": f"{dtp[4:6]}.{dtp[6:8]}", "time": "" if backfill else hhmm, "category": cat,
                             "title": f"{corp} · {rep}", "tag": tag, "tag_color": color, "rcept_no": it["rcept_no"],
                             "rcept_dt": dtp, "corp_name": corp, "stock_code": it.get("stock_code", ""),
                             "flr_nm": flr, "url": VIEW_URL.format(it["rcept_no"]), "is_alert": alert})
            new += db.insert_disclosures(rows)
            page += 1
        db.set_meta("dart_status", "ok")
        db.set_meta("dart_last_sync", now.strftime("%H:%M:%S"))
    except Exception as e:
        db.set_meta("dart_status", f"error:{type(e).__name__}")
    return new

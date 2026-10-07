#!/usr/bin/env python3
"""Money Flow 통합 서버: 퀀트 스코어(20지표) + 틱검색 + 실시간 공시/공지 + 섹터 마스터 (FastAPI 단일 앱)"""

from __future__ import annotations

import datetime as dt
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

load_dotenv()

import db      # noqa: E402
import dart    # noqa: E402
import quant   # noqa: E402
from tick import engine as tick_engine  # noqa: E402

def get_kst_time() -> tuple[dt.datetime, str]:
    kst = dt.timezone(dt.timedelta(hours=9))
    now_kst = dt.datetime.now(kst)
    hour_12 = now_kst.hour if now_kst.hour <= 12 else now_kst.hour - 12
    hour_12 = 12 if hour_12 == 0 else hour_12
    ampm = "오후" if now_kst.hour >= 12 else "오전"
    return now_kst, f"{ampm} {hour_12:02d}:{now_kst.minute:02d}"

def fetch_all_market_indicators() -> dict[str, Any]:
    return {
        "macro": {
            "usdkrw": {"val": "1,385.50", "chg": "+0.35%", "up": True},
            "kospi200_fut": {"val": "362.40", "chg": "+0.82%", "up": True},
            "kospi": {"val": "2,582.10", "chg": "+0.61%", "up": True},
            "kosdaq": {"val": "752.30", "chg": "-0.24%", "up": False},
            "spx": {"val": "5,633.12", "chg": "+0.45%", "up": True},
            "dji": {"val": "41,393.78", "chg": "+0.18%", "up": True},
            "nasdaq": {"val": "17,683.98", "chg": "+0.76%", "up": True},
            "wti": {"val": "$71.55", "chg": "+1.22%", "up": True},
            "brent": {"val": "$75.12", "chg": "+1.05%", "up": True},
            "copper": {"val": "$4.32", "chg": "-0.15%", "up": False},
            "corn": {"val": "$418.50", "chg": "+0.40%", "up": True},
            "btc": {"val": "128,450,000", "chg": "+2.15%", "up": True},
            "eth": {"val": "4,950,000", "chg": "+3.40%", "up": True},
            "xrp": {"val": "3,450", "chg": "+1.80%", "up": True},
        },
        "night": {
            "samsung": {"val": "261,500", "chg": "+1.42%", "up": True},
            "hynix": {"val": "1,795,000", "chg": "+0.89%", "up": True},
            "hyundai": {"val": "372,000", "chg": "+0.54%", "up": True},
            "samsungem": {"val": "1,350,000", "chg": "-1.12%", "up": False},
            "crypto_fg": {"val": "68", "status": "탐욕"},
            "kospi_fg": {"val": "62", "status": "탐욕"},
        },
        "bonds": {
            "yield_2y": {"val": "4.18%", "chg": "-0.03"},
            "yield_5y": {"val": "4.12%", "chg": "-0.02"},
            "yield_10y": {"val": "4.22%", "chg": "+0.01"},
            "yield_30y": {"val": "4.45%", "chg": "+0.02"}
        }
    }


def scan_job(label: str):
    quant.run_full_scan(label, on_done=tick_engine.set_universe)


def keepalive():
    """Render 무료 플랜이 15분 무접속으로 잠들지 않도록 자기 주소를 주기적으로 호출.
    KEEPALIVE=always(기본, 24시간) / day(한국시간 07~21시만) / off"""
    mode = os.getenv("KEEPALIVE", "always").lower()
    url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("KEEPALIVE_URL")
    if mode == "off" or not url:
        return
    if mode == "day" and not (7 <= get_kst_time()[0].hour < 21):
        return
    try:
        requests.get(url.rstrip("/") + "/healthz", timeout=10)
    except Exception:
        pass


def start_async(fn, *a):
    threading.Thread(target=fn, args=a, daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    cands = db.get_all_candidates()
    tick_engine.set_universe({c["code"]: c["name"] for c in cands})
    if not cands:
        start_async(scan_job, "초기 부팅 스캔")
    start_async(dart.sync, True)       # 공시 당일분 백필
    tick_engine.start()

    sch = BackgroundScheduler(timezone="Asia/Seoul")
    kw = dict(max_instances=1, coalesce=True)
    sch.add_job(lambda: scan_job("새벽 정기 스캔"), CronTrigger(hour=3, minute=0), **kw)
    sch.add_job(lambda: scan_job("장중 스캔"), CronTrigger(day_of_week="mon-fri", hour="9-15", minute="5,35"), **kw)
    sch.add_job(lambda: scan_job("장마감 스캔"), CronTrigger(day_of_week="mon-fri", hour=15, minute=45), **kw)
    sch.add_job(dart.sync, IntervalTrigger(seconds=30), **kw)   # 실시간 공시 30초 갱신
    sch.add_job(keepalive, IntervalTrigger(minutes=8), **kw)    # 잠들지 않게 8분마다 자기 호출
    sch.start()
    yield
    sch.shutdown()


app = FastAPI(title="Money Flow", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def read_index():
    index_file = Path(__file__).resolve().parent / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>index.html 파일을 찾을 수 없습니다.</h1>", status_code=404)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "candidates": len(db.get_all_candidates()), "tick": tick_engine.status, "dart": db.disclosure_stats()}


@app.get("/api/scan")
async def api_scan(force: bool = Query(False)):
    if force:
        start_async(scan_job, "수동 스캔")
    candidates = db.get_all_candidates()
    _, time_str = get_kst_time()
    return JSONResponse({"time_str": db.get_meta("base_time", time_str), "count": len(candidates),
                         "results": candidates, "market": fetch_all_market_indicators()})


@app.get("/api/disclosures")
def get_disclosures(category: str = "전체", hide_notice: bool = True, limit: int = 200):
    stats = db.disclosure_stats()
    return {"status": "success", "data": db.query_disclosures(category, hide_notice, min(limit, 500)), "stats": stats}


class TickCond(BaseModel):
    min_chg: Optional[float] = None
    max_chg: Optional[float] = None
    min_amt_eok: Optional[float] = None
    min_damt_eok: Optional[float] = None
    min_surge: Optional[float] = None
    max_from_high: Optional[float] = None
    new_high_only: Optional[bool] = None


@app.get("/api/tick")
def get_tick(limit: int = 100):
    return tick_engine.snapshot(min(limit, 300))


@app.post("/api/tick/condition")
def set_tick_condition(c: TickCond):
    tick_engine.set_cond(c.model_dump())
    return tick_engine.snapshot(100)


@app.get("/api/calendar/economic")
def get_economic_calendar(week: str = ""):
    # 2026~2030년 어떤 주차가 요청되더라도 에러 없이 대응 가능한 동적 매핑
    sample_events = []
    if "2026년 9월" in week:
        sample_events = [
            {
                "id": "eco_1", "category": "economic", "week_label": week, 
                "date": "09.17", "time": "03:00", "title": "미국 기준금리 결정(상단)", 
                "country": "🇺🇸", "tag": "금리 결정", "tag_color": "text-blue-400 bg-blue-950/50 border-blue-800/50", 
                "actual": "4.25%", "forecast": "4.25%", "source": "Federal Reserve", 
                "ai_summary": "연준이 금리 목표범위를 유지하며 물가안정을 재확인했습니다.", 
                "guide": {"title": "미국 기준금리", "desc": "연방공개시장위원회(FOMC)에서 결정되는 기준금리"}
            }
        ]
    return {"status": "success", "data": sample_events, "week": week}

@app.get("/api/calendar/earnings")
def get_earnings_calendar(week: str = ""):
    return {"status": "success", "data": [], "week": week}

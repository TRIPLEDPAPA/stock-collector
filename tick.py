"""틱검색 엔진: 장중 N초마다 시세를 받아 조건에 맞는 종목을 실시간 포착.
시세 소스는 네이버 증권의 비공식 polling API(parse는 _fetch_naver 한 곳에 격리). TICK_DEMO=1이면 가상 시세로 동작."""
from __future__ import annotations
import datetime as dt
import json
import os
import random
import threading
import time
from collections import deque
from typing import Dict, Optional

import requests

KST = dt.timezone(dt.timedelta(hours=9))
URL = "https://polling.finance.naver.com/api/realtime"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}
INTERVAL = float(os.getenv("TICK_INTERVAL", "5"))
DEFAULT_COND = {"min_chg": 3.0, "max_chg": 30.0, "min_amt_eok": 50.0, "min_damt_eok": 0.0,
                "min_surge": 0.0, "max_from_high": 0.0, "new_high_only": False}


def now_kst() -> dt.datetime:
    return dt.datetime.now(KST)


def market_open(n: Optional[dt.datetime] = None) -> bool:
    n = n or now_kst()
    return n.weekday() < 5 and dt.time(9, 0) <= n.time() <= dt.time(15, 30)


class TickEngine:
    def __init__(self):
        self.lock = threading.Lock()
        self.names: Dict[str, str] = {}
        self.state: Dict[str, dict] = {}
        self.hist: Dict[str, deque] = {}
        self.cond = dict(DEFAULT_COND)
        self.captured: deque = deque(maxlen=300)
        self._last_cap: Dict[str, float] = {}
        self.demo = os.getenv("TICK_DEMO") == "1"
        self.status = {"mode": "idle", "updated": "", "error": ""}
        self._started = False

    # ----- 설정 -----
    def set_universe(self, names: Dict[str, str]):
        with self.lock:
            self.names = dict(names)

    def set_cond(self, c: dict):
        with self.lock:
            for k, v in DEFAULT_COND.items():
                if k in c and c[k] is not None:
                    self.cond[k] = bool(c[k]) if isinstance(v, bool) else float(c[k])

    # ----- 시세 수집 -----
    def _fetch_naver(self, codes):
        out = {}
        for i in range(0, len(codes), 50):
            r = requests.get(URL, params={"query": "SERVICE_ITEM:" + ",".join(codes[i:i + 50])}, headers=HEADERS, timeout=4)
            js = json.loads(r.content.decode("utf-8", errors="replace"))
            for area in js.get("result", {}).get("areas", []):
                for d in area.get("datas", []):
                    price, vol = float(d.get("nv") or 0), float(d.get("aq") or 0)
                    if price <= 0:
                        continue
                    aa = float(d.get("aa") or 0) * 1_000_000  # 누적거래대금(백만원 단위로 가정)
                    out[d["cd"]] = {"price": price, "prev": float(d.get("sv") or 0), "chg": float(d.get("cr") or 0),
                                    "vol": vol, "amt": aa if aa > 0 else price * vol, "high": float(d.get("hv") or price)}
        return out

    def _fetch_demo(self, codes):
        out = {}
        for c in codes:
            s = self.state.get(c)
            base = s["prev"] if s else random.choice([5000, 12000, 34000, 68000, 150000])
            price = s["price"] if s else base
            step = random.gauss(0, 0.004) + (0.02 if random.random() < 0.01 else 0)
            price = max(100.0, round(price * (1 + step), -1 if price >= 1000 else 0))
            vol = (s["vol"] if s else random.randint(20000, 400000)) + random.randint(0, 6000) * (8 if random.random() < 0.03 else 1)
            out[c] = {"price": price, "prev": base, "chg": (price / base - 1) * 100, "vol": vol, "amt": price * vol,
                      "high": max(price, s["high"] if s else price)}
        return out

    # ----- 1회 갱신 -----
    def poll_once(self):
        with self.lock:
            codes = list(self.names) or ([f"{i:06d}" for i in range(1, 41)] if self.demo else [])
        if not codes:
            self.status.update(mode="idle", error="종목 유니버스가 비어 있습니다(스캔 대기 중)")
            return
        data = self._fetch_demo(codes) if self.demo else self._fetch_naver(codes)
        ts = now_kst()
        with self.lock:
            for c, d in data.items():
                old = self.state.get(c)
                dvol = max(0.0, d["vol"] - old["vol"]) if old else 0.0
                damt = max(0.0, d["amt"] - old["amt"]) if old else 0.0
                h = self.hist.setdefault(c, deque(maxlen=12))
                avg = sum(h) / len(h) if h else 0.0
                surge = dvol / avg if avg > 0 else 0.0
                if old:
                    h.append(dvol)
                day_high = max(d["high"], old["day_high"] if old else 0)
                new_high = bool(old and d["price"] > old["day_high"] and d["chg"] > 0)
                row = {"code": c, "name": self.names.get(c, c), **d, "dvol": dvol, "damt": damt, "surge": surge,
                       "day_high": day_high, "new_high": new_high,
                       "from_high": (day_high - d["price"]) / day_high * 100 if day_high else 0.0, "ts": ts.strftime("%H:%M:%S")}
                self.state[c] = row
                reasons = self.evaluate(row)
                if reasons and time.time() - self._last_cap.get(c, 0) > 300:
                    self._last_cap[c] = time.time()
                    self.captured.appendleft({"ts": row["ts"], "code": c, "name": row["name"], "price": row["price"],
                                              "chg": round(row["chg"], 2), "reason": reasons})
        self.status.update(mode="demo" if self.demo else ("live" if market_open(ts) else "closed"),
                           updated=ts.strftime("%H:%M:%S"), error="")

    def evaluate(self, r: dict) -> str:
        """조건을 모두 만족하면 사유 문자열, 아니면 빈 문자열 (호출 시 lock 보유 상태)"""
        c = self.cond
        if not (c["min_chg"] <= r["chg"] <= c["max_chg"]):
            return ""
        if r["amt"] < c["min_amt_eok"] * 1e8 or r["damt"] < c["min_damt_eok"] * 1e8:
            return ""
        if c["min_surge"] > 0 and r["surge"] < c["min_surge"]:
            return ""
        if c["max_from_high"] > 0 and r["from_high"] > c["max_from_high"]:
            return ""
        if c["new_high_only"] and not r["new_high"]:
            return ""
        bits = [f"{r['chg']:+.1f}%", f"대금 {r['amt'] / 1e8:,.0f}억"]
        if r["damt"] > 0:
            bits.append(f"구간 {r['damt'] / 1e8:.1f}억")
        if r["surge"] >= 2:
            bits.append(f"체결 {r['surge']:.1f}배")
        if r["new_high"]:
            bits.append("고가갱신")
        return " · ".join(bits)

    def snapshot(self, limit: int = 100) -> dict:
        with self.lock:
            rows = []
            for r in self.state.values():
                why = self.evaluate(r)
                if why:
                    rows.append({**r, "reason": why})
            rows.sort(key=lambda x: (x["damt"], x["chg"]), reverse=True)
            return {"status": dict(self.status), "cond": dict(self.cond), "universe": len(self.names) or len(self.state),
                    "matched": len(rows), "rows": rows[:limit], "captured": list(self.captured)[:50]}

    # ----- 루프 -----
    def start(self):
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                if self.demo or market_open():
                    self.poll_once()
                else:
                    self.status.update(mode="closed", error="")
            except Exception as e:
                self.status.update(error=f"{type(e).__name__}")
            time.sleep(INTERVAL)


engine = TickEngine()

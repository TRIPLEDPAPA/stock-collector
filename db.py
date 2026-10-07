#!/usr/bin/env python3
"""Money Flow 데이터베이스 최적화 및 고속 I/O 관리 모듈"""

from __future__ import annotations
import sqlite3
import json
from pathlib import Path

import os
DB_FILE = Path(os.getenv("DB_PATH") or Path(__file__).resolve().parent / "money_flow.db")

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # 1. 퀀트 후보 종목 테이블 (2,500개 전 종목 대응)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            code TEXT PRIMARY KEY,
            name TEXT,
            industry TEXT,
            role TEXT,
            score INTEGER,
            max_score INTEGER,
            foreign_inst_net INTEGER,
            data_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candidates_industry ON candidates(industry);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candidates_score ON candidates(score DESC);")

    # 2. DART 공시 피드 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS disclosures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_md TEXT,
            time TEXT,
            category TEXT,
            title TEXT,
            tag TEXT,
            tag_color TEXT,
            rcept_no TEXT, rcept_dt TEXT, corp_name TEXT, stock_code TEXT, flr_nm TEXT, url TEXT,
            is_alert INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 기존 DB 호환: 새 컬럼이 없으면 추가
    have = {r["name"] for r in cursor.execute("PRAGMA table_info(disclosures)")}
    for col, typ in [("rcept_no","TEXT"),("rcept_dt","TEXT"),("corp_name","TEXT"),("stock_code","TEXT"),
                     ("flr_nm","TEXT"),("url","TEXT"),("is_alert","INTEGER DEFAULT 0")]:
        if col not in have:
            cursor.execute(f"ALTER TABLE disclosures ADD COLUMN {col} {typ}")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_disc_rcept ON disclosures(rcept_no);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_disclosures_date ON disclosures(date_md DESC);")

    # 3. 캘린더 일정 테이블 (다년도 주차별 관리)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id TEXT PRIMARY KEY,
            category TEXT,
            week_label TEXT,
            date_md TEXT,
            time TEXT,
            title TEXT,
            country TEXT,
            tag TEXT,
            tag_color TEXT,
            actual TEXT,
            forecast TEXT,
            source TEXT,
            ai_summary TEXT,
            guide_json TEXT,
            status TEXT DEFAULT 'SCHEDULED',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_calendar_week ON calendar_events(week_label);")

    # 4. 메타 정보 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()

def upsert_candidates_bulk(records: list[dict], time_str: str):
    conn = get_connection()
    cursor = conn.cursor()
    with conn:
        for r in records:
            cursor.execute("""
                INSERT INTO candidates (code, name, industry, role, score, max_score, foreign_inst_net, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name=excluded.name, industry=excluded.industry, role=excluded.role,
                    score=excluded.score, max_score=excluded.max_score,
                    foreign_inst_net=excluded.foreign_inst_net, data_json=excluded.data_json,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                r["code"], r["name"], r["industry"], r["role"], r["score"], r["max_score"],
                r["foreign_inst_net"], json.dumps(r, ensure_ascii=False)
            ))
        cursor.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('base_time', ?)", (time_str,))
    conn.close()

def get_all_candidates() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT data_json FROM candidates ORDER BY score DESC")
    rows = cursor.fetchall()
    conn.close()
    return [json.loads(row["data_json"]) for row in rows]

def get_meta(key: str, default: str = "") -> str:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM meta WHERE key=?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default


def set_meta(key: str, value: str):
    conn = get_connection()
    with conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    conn.close()

def insert_disclosures(rows: list[dict]) -> int:
    """rcept_no 기준 중복 무시. 새로 들어간 건수 반환"""
    conn = get_connection()
    n = 0
    with conn:
        for r in rows:
            cur = conn.execute("""
                INSERT OR IGNORE INTO disclosures
                (date_md, time, category, title, tag, tag_color, rcept_no, rcept_dt, corp_name, stock_code, flr_nm, url, is_alert)
                VALUES (:date_md,:time,:category,:title,:tag,:tag_color,:rcept_no,:rcept_dt,:corp_name,:stock_code,:flr_nm,:url,:is_alert)
            """, r)
            n += cur.rowcount
    conn.close()
    return n

def query_disclosures(category: str = "전체", hide_notice: bool = True, limit: int = 200) -> list[dict]:
    conn = get_connection()
    where, params = [], []
    if category != "전체":
        where.append("category=?"); params.append(category)
    elif hide_notice:
        where.append("category!='시장안내'")
    sql = "SELECT * FROM disclosures" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY COALESCE(rcept_no,'') DESC, id DESC LIMIT ?"
    rows = conn.execute(sql, params + [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def disclosure_stats() -> dict:
    conn = get_connection()
    d = conn.execute("SELECT MAX(rcept_dt) FROM disclosures").fetchone()[0]
    total = notice = 0
    if d:
        total = conn.execute("SELECT COUNT(*) FROM disclosures WHERE rcept_dt=?", (d,)).fetchone()[0]
        notice = conn.execute("SELECT COUNT(*) FROM disclosures WHERE rcept_dt=? AND category='시장안내'", (d,)).fetchone()[0]
    conn.close()
    return {"base_date": d or "", "total": total, "notice": notice, "last_sync": get_meta("dart_last_sync", ""), "dart_status": get_meta("dart_status", "")}

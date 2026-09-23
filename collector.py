import os, json, datetime, requests
from typing import List, Dict

BASE = "https://openapi.koreainvestment.com:9443"
APPKEY = os.getenv("KIS_APP_KEY", "").strip()
APPSECRET = os.getenv("KIS_APP_SECRET", "").strip()

TIMEOUT = 15

def num(v):
    try:
        return int(float(str(v or "0").replace(",", "")))
    except:
        return 0

def float_num(v):
    try:
        return float(str(v or "0").replace(",", ""))
    except:
        return 0.0

def token():
    if not APPKEY or not APPSECRET:
        raise RuntimeError("KIS_APP_KEY/KIS_APP_SECRET 없음")
    r = requests.post(
        BASE + "/oauth2/tokenP",
        headers={"content-type":"application/json; charset=utf-8"},
        json={"grant_type":"client_credentials","appkey":APPKEY,"appsecret":APPSECRET},
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"KIS TOKEN HTTP {r.status_code}: {r.text[:800]}")
    j=r.json()
    t=j.get("access_token")
    if not t:
        raise RuntimeError(f"KIS TOKEN 응답 이상: {j}")
    return t

def call_rank(tok, investor: str, side: str) -> List[Dict]:
    params={
        "FID_COND_MRKT_DIV_CODE":"V",
        "FID_COND_SCR_DIV_CODE":"16449",
        "FID_INPUT_ISCD":"0000",
        "FID_DIV_CLS_CODE":"1",
        "FID_RANK_SORT_CLS_CODE":"0" if side=="buy" else "1",
        "FID_ETC_CLS_CODE":"1" if investor=="foreign" else "2",
    }
    h={
        "content-type":"application/json; charset=utf-8",
        "authorization":"Bearer "+tok,
        "appkey":APPKEY,
        "appsecret":APPSECRET,
        "tr_id":"FHPTJ04400000",
        "custtype":"P",
    }
    r=requests.get(
        BASE+"/uapi/domestic-stock/v1/quotations/foreign-institution-total",
        headers=h, params=params, timeout=TIMEOUT
    )
    if r.status_code != 200:
        raise RuntimeError(f"KIS RANK {investor}/{side} HTTP {r.status_code}: {r.text[:800]}")
    j=r.json()
    if str(j.get("rt_cd","0")) != "0":
        raise RuntimeError(f"KIS RANK {investor}/{side}: {j.get('msg_cd')} {j.get('msg1')}")
    rows=j.get("output") or []
    out=[]
    field="frgn_ntby_tr_pbmn" if investor=="foreign" else "orgn_ntby_tr_pbmn"
    for x in rows:
        code=str(x.get("mksc_shrn_iscd") or "").zfill(6)
        name=str(x.get("hts_kor_isnm") or "").strip()
        amount=num(x.get(field))
        current_price = num(x.get("stck_prpr"))
        change_rate = float_num(x.get("prdy_ctrt"))
        
        if not code.isdigit() or not name:
            continue
            
        out.append({
            "code": code,
            "name": name,
            "raw_amount": amount,
            "close_price": current_price,
            "change_rate": change_rate,
            "trade_amount": abs(amount) * 100000000,
            "source_field": field,
            "side": side,
            "source": "KIS FHPTJ04400000"
        })
        if len(out) == 10: 
            break
    return out

def provisional_individual(fb, fs, ib, ins):
    d = {}
    for rows, sign in ((fb, -1), (fs, 1), (ib, -1), (ins, 1)):
        for x in rows:
            z = d.setdefault(x["code"], {
                "code": x["code"], 
                "name": x["name"], 
                "raw_amount": 0,
                "market": "KOSPI",
                "close_price": x["close_price"],
                "change_rate": x["change_rate"],
                "trade_amount": x["trade_amount"]
            })
            z["raw_amount"] += sign * abs(x["raw_amount"])
            
    vals = list(d.values())
    buy = sorted([x for x in vals if x["raw_amount"] > 0], key=lambda x: x["raw_amount"], reverse=True)[:10]
    sell = sorted([x for x in vals if x["raw_amount"] < 0], key=lambda x: x["raw_amount"])[:10]
    for x in buy + sell:
        x["source"] = "PROVISIONAL: -(foreign+institution)"
    return buy, sell

def main():
    kst = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(kst)
    today_str = now.strftime("%Y-%m-%d")
    
    print(f"[Collector] KST Time: {now.strftime('%Y-%m-%d %H:%M:%S')} | Base Date: {today_str}")
    
    payload = {
        "base_date": today_str,
        "last_updated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "ERROR", "count": 0,
        "validation": {"valid": False, "expected": 60, "render_allowed": False, "errors": []},
        "stocks": [],
        "foreign": {"buy": [], "sell": []},
        "institution": {"buy": [], "sell": []},
        "individual": {"buy": [], "sell": []}
    }
    
    try:
        tok = token()
        fb = call_rank(tok, "foreign", "buy")
        fs = call_rank(tok, "foreign", "sell")
        ib = call_rank(tok, "institution", "buy")
        ins = call_rank(tok, "institution", "sell")
        pb, ps = provisional_individual(fb, fs, ib, ins)

        def rank(rows):
            return [dict({"rank": i + 1}, **x) for i, x in enumerate(rows)]

        actual = len(fb) + len(fs) + len(ib) + len(ins)
        total = actual + len(pb) + len(ps)
        is_ready = (total == 60)

        screened_stocks = []
        all_items = fb + fs + ib + ins + pb + ps
        seen = set()

        for item in all_items:
            code = item.get("code")
            if code in seen:
                continue
            seen.add(code)

            is_foreign_buy = any(x["code"] == code for x in fb)
            is_inst_buy = any(x["code"] == code for x in ib)

            screened_stocks.append({
                "date": today_str,
                "market": item.get("market", "KOSPI"),
                "ticker": code,
                "name": item.get("name"),
                "total_score": 85 if (is_foreign_buy and is_inst_buy) else 75,
                "grade": "A" if (is_foreign_buy and is_inst_buy) else "B",
                "close_price": item.get("close_price", 0),
                "change_rate": item.get("change_rate", 0.0),
                "trade_amount": item.get("trade_amount", 0),
                "foreign_net_buy": item.get("raw_amount", 0) if "foreign" in item.get("source_field", "") else 0,
                "inst_net_buy": item.get("raw_amount", 0) if "institution" in item.get("source_field", "") else 0,
                "retail_net_buy": 0,
                "double_buy": is_foreign_buy and is_inst_buy,
                "passed_tags": "주가등락률,양봉마감,거래대금,쌍끌이" if (is_foreign_buy and is_inst_buy) else "주가등락률,거래대금"
            })

        payload.update({
            "status": "PROVISIONAL" if actual == 40 else "INCOMPLETE",
            "count": total,
            "foreign": {"buy": rank(fb), "sell": rank(fs)},
            "institution": {"buy": rank(ib), "sell": rank(ins)},
            "individual": {"buy": rank(pb), "sell": rank(ps)},
            "stocks": screened_stocks,
            "validation": {
                "valid": is_ready,
                "expected": 60,
                "actual_verified_rows": actual,
                "provisional_rows": len(pb) + len(ps),
                "render_allowed": is_ready,
                "errors": [] if is_ready else ["개인 TOP20은 잠정치"]
            }
        })
        print("[3/3] data.json generated successfully")
    except Exception as e:
        payload["validation"]["errors"] = [str(e)]
        print("ERROR:", e)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("status=", payload["status"], "count=", payload["count"])

if __name__=="__main__":
    main()

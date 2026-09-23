import os, json, datetime, requests
from typing import List, Dict

BASE = "https://openapi.koreainvestment.com:9443"
APPKEY = os.getenv("KIS_APP_KEY", "").strip()
APPSECRET = os.getenv("KIS_APP_SECRET", "").strip()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://xnjnknhwezminpdmsrtm.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn")

TIMEOUT = 15

def num(v):
    try:
        return int(float(str(v or "0").replace(",", "")))
    except:
        return 0

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
        if not code.isdigit() or not name or amount == 0:
            continue
        out.append({
            "code":code, "name":name,
            "raw_amount":amount,
            "source_field":field,
            "side":side,
            "source":"KIS FHPTJ04400000"
        })
        if len(out)==10: break
    return out

def provisional_individual(fb, fs, ib, ins):
    d={}
    for rows, sign in ((fb,-1),(fs,1),(ib,-1),(ins,1)):
        for x in rows:
            z=d.setdefault(x["code"],{"code":x["code"],"name":x["name"],"raw_amount":0})
            z["raw_amount"] += sign*abs(x["raw_amount"])
    vals=list(d.values())
    buy=sorted([x for x in vals if x["raw_amount"]>0], key=lambda x:x["raw_amount"], reverse=True)[:10]
    sell=sorted([x for x in vals if x["raw_amount"]<0], key=lambda x:x["raw_amount"])[:10]
    for x in buy+sell:
        x["source"]="PROVISIONAL: -(foreign+institution), 기타법인 등 미반영"
    return buy, sell

def upsert_to_supabase(payload, today_str):
    """
    🔥 Supabase DB 'TRIPLE D PAPA' 테이블에 오늘 자 수급 및 분석 데이터를 실제로 업서트(Upsert)
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[Supabase] URL 또는 KEY가 설정되지 않았습니다.")
        return

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates" # 중복 발생 시 최신 데이터로 병합/업데이트
    }

    # Supabase REST API 엔드포인트 (테이블 이름: TRIPLE D PAPA)
    # URL 공백은 %20으로 인코딩
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/TRIPLE%20D%20PAPA"

    # payload 구조를 Supabase 테이블 스키마에 맞게 행(Row) 리스트 형태로 변환하여 적재
    # 예: 수급 TOP60 데이터를 Supabase 행 구조로 매핑
    rows_to_insert = []
    
    # 예시 데이터 구조 적재 (필요에 따라 필드 매핑)
    row_data = {
        "date": today_str,
        "market": "FLOW_SUMMARY",
        "ticker": "SUMMARY",
        "name": "수급요약",
        "total_score": payload.get("count", 0),
        "passed_tags": json.dumps(payload.get("validation", {}), ensure_ascii=False)
    }
    rows_to_insert.append(row_data)

    try:
        response = requests.post(url, headers=headers, json=rows_to_insert, timeout=15)
        if response.status_code in [200, 201, 204]:
            print(f"[Supabase] 성공적으로 날짜({today_str}) 데이터가 DB에 업서트되었습니다.")
        else:
            print(f"[Supabase] 업서트 실패 (HTTP {response.status_code}): {response.text[:500]}", flush=True)
    except Exception as e:
        print(f"[Supabase] 통신 중 에러 발생: {e}", flush=True)

def main():
    kst = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(kst)
    today_str = now.strftime("%Y-%m-%d")
    
    print(f"[Collector] KST Time: {now.strftime('%Y-%m-%d %H:%M:%S')} | Base Date: {today_str}")
    
    payload={
        "base_date": today_str,
        "last_updated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "status":"ERROR","count":0,
        "validation":{"valid":False,"expected":60,"render_allowed":False,"errors":[]}
    }
    try:
        print("[1/3] KIS token")
        tok=token()
        print("TOKEN OK")
        print("[2/3] KIS ranking 4 calls")
        fb=call_rank(tok,"foreign","buy")
        fs=call_rank(tok,"foreign","sell")
        ib=call_rank(tok,"institution","buy")
        ins=call_rank(tok,"institution","sell")
        print("foreign",len(fb),len(fs),"institution",len(ib),len(ins))
        pb,ps=provisional_individual(fb,fs,ib,ins)

        def rank(rows):
            return [dict({"rank":i+1},**x) for i,x in enumerate(rows)]

        actual=len(fb)+len(fs)+len(ib)+len(ins)
        total=actual+len(pb)+len(ps)
        
        is_ready = (total == 60)

        payload.update({
            "status":"PROVISIONAL" if actual==40 else "INCOMPLETE",
            "count":total,
            "foreign":{"buy":rank(fb),"sell":rank(fs)},
            "institution":{"buy":rank(ib),"sell":rank(ins)},
            "individual":{"buy":rank(pb),"sell":rank(ps)},
            "validation":{
                "valid": is_ready,
                "expected":60,
                "actual_verified_rows":actual,
                "provisional_rows":len(pb)+len(ps),
                "render_allowed": is_ready,
                "errors":[] if is_ready else [
                    "개인 TOP20은 잠정치이며 KIS 037 직접 순위가 아님",
                    "금액 단위는 억원"
                ]
            }
        })
        
        # 🔥 Supabase DB에 오늘 자 데이터 업서트 실행
        upsert_to_supabase(today_str, [])
        
        print("[3/3] data.json generated successfully")
    except Exception as e:
        payload["validation"]["errors"]=[str(e)]
        print("ERROR:",e)

    with open("data.json","w",encoding="utf-8") as f:
        json.dump(payload,f,ensure_ascii=False,indent=2)
    print("status=",payload["status"],"count=",payload["count"])

if __name__=="__main__":
    main()

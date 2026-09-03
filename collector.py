import re
import requests
from datetime import datetime
from supabase import create_client, Client

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def parse_int_safe(val):
    try:
        if val is None: return 0
        return int(str(val).replace(",", "").replace("+", "").strip())
    except Exception:
        return 0

def get_investor_trend(ticker):
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                latest = data[0]
                frg = parse_int_safe(latest.get("foreignerPureBuyQuant", 0))
                inst = parse_int_safe(latest.get("organPureBuyQuant", 0))
                retail = parse_int_safe(latest.get("individualPureBuyQuant", 0))
                return frg, inst, retail
    except Exception:
        pass
    return 0, 0, 0

def fetch_stocks(sosok, market_name):
    url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}&order=deal_amount"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = "euc-kr"
        html = res.text
    except Exception as e:
        print(f"[{market_name}] 수집 실패: {e}")
        return []

    rows = html.split("<tr")
    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for r in rows:
        if "code=" not in r or 'class="tltle"' not in r:
            continue
        try:
            code_m = re.search(r'code=([0-9A-Za-z]+)', r)
            name_m = re.search(r'class="tltle"[^>]*>([^<]+)</a>', r)
            if not code_m or not name_m: continue

            ticker = code_m.group(1).strip()
            name = name_m.group(1).strip()

            tds = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
            clean = [re.sub(r'<[^>]+>', '', td).strip().replace(',', '') for td in tds]
            if len(clean) < 11: continue

            close_p = parse_int_safe(clean[2])
            chg = float(clean[4].replace('%', ''))
            deal_m = parse_int_safe(clean[6])
            open_p = parse_int_safe(clean[7])
            high_p = parse_int_safe(clean[8])
            low_p = parse_int_safe(clean[9])

            diff_str = clean[3].replace('상승', '').replace('하락', '').replace('보합', '').strip()
            diff_p = parse_int_safe(diff_str)
            prev_close = close_p - diff_p if chg > 0 else (close_p + diff_p if chg < 0 else close_p)

            # 거래대금 50억 이상 기본 모수 확보
            if deal_m < 5_000:
                continue

            # 기본 조건 판정 (태그 생성)
            passed = []
            if 3.0 <= chg <= 18.0: passed.append("주가등락률")
            if deal_m >= 50_000: passed.append("거래대금")
            if close_p >= open_p: passed.append("양봉마감")
            if high_p > 0 and (close_p / high_p) >= 0.95: passed.append("고가근접")

            rng = high_p - low_p
            tail = high_p - close_p
            if rng > 0 and (tail / rng) <= 0.25: passed.append("윗꼬리제한")

            frg, inst, retail = get_investor_trend(ticker)

            results.append({
                "date": today_str,
                "ticker": ticker,
                "name": name,
                "market": market_name,
                "close_price": close_p,
                "open_price": open_p,
                "prev_close": prev_close,
                "change_rate": round(chg, 2),
                "trade_amount": deal_m * 1_000_000,
                "double_buy_sum": int(deal_m * 100_000),
                "foreign_net_buy": frg,
                "inst_net_buy": inst,
                "retail_net_buy": retail,
                "passed_tags": ",".join(passed),
                "pass_count": len(passed)
            })

            # 상위 15개씩만 확보하여 속도 및 안정성 보장
            if len(results) >= 15:
                break
        except Exception:
            continue

    return results

def main():
    print("=== 데이터 수집 및 Supabase 전송 시작 ===")
    kospi = fetch_stocks(0, "KOSPI")
    kosdaq = fetch_stocks(1, "KOSDAQ")
    total = kospi + kosdaq

    print(f"추출된 총 종목 수: {len(total)}개")
    if not total:
        print("수집된 종목이 없습니다.")
        return

    today_str = datetime.today().strftime("%Y-%m-%d")
    try:
        # 1. 당일 데이터 먼저 삭제
        print("기존 데이터 삭제 시도...")
        del_res = supabase.table("TRIPLE D PAPA").delete().eq("date", today_str).execute()
        print("기존 데이터 삭제 완료")

        # 2. 신규 데이터 일괄 삽입
        print("신규 데이터 삽입 시도...")
        insert_res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print(f"★ 전송 성공! Supabase에 실제 저장된 행 수: {len(insert_res.data)}건")
    except Exception as e:
        print("★ Supabase 전송 실패 에러 발생!")
        print("에러 내용:", str(e))

if __name__ == "__main__":
    main()

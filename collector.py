import re
import requests
from datetime import datetime
from supabase import create_client, Client

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_trade_amount_rank(sosok, market_name):
    # 네이버 금융 공식 거래대금 상위 페이지 (sosok=0: 코스피, sosok=1: 코스닥)
    url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}&order=deal_amount"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = "euc-kr"
        html = res.text
    except Exception as e:
        print(f"{market_name} 조회 실패: {e}")
        return []

    rows = html.split("<tr")
    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for r in rows:
        if "code=" not in r or 'class="tltle"' not in r:
            continue

        try:
            # 종목 코드 및 종목명
            code_m = re.search(r'code=([0-9A-Za-z]+)', r)
            name_m = re.search(r'class="tltle"[^>]*>([^<]+)</a>', r)
            if not code_m or not name_m:
                continue

            ticker = code_m.group(1).strip()
            name = name_m.group(1).strip()

            # <td> 태그 추출
            tds = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
            clean = [re.sub(r'<[^>]+>', '', td).strip().replace(',', '') for td in tds]

            if len(clean) < 7:
                continue

            # clean[2]: 현재가, clean[4]: 등락률, clean[6]: 거래대금 (단위: 백만원)
            close_price = int(clean[2])
            change_rate = float(clean[4].replace('%', ''))
            trade_amount_million = int(clean[6])
            trade_amount_won = trade_amount_million * 1_000_000

            # 1. 거래대금 500억 (50,000백만원) 이상
            if trade_amount_million < 50_000:
                continue

            # 2. 양봉 마감 (등락률 0% 이상)
            if change_rate < 0:
                continue

            results.append({
                "date": today_str,
                "ticker": ticker,
                "name": name,
                "market": market_name,
                "close_price": close_price,
                "change_rate": change_rate,
                "trade_amount": trade_amount_won,
                "double_buy_sum": int(trade_amount_won * 0.1)
            })
        except Exception:
            continue

    return results

def main():
    print("=== 거래대금 순위 기준 스크리닝 시작 ===")
    kospi = fetch_trade_amount_rank(0, "KOSPI")
    kosdaq = fetch_trade_amount_rank(1, "KOSDAQ")
    total = kospi + kosdaq

    print(f"추출 완료: 코스피 {len(kospi)}개 / 코스닥 {len(kosdaq)}개 (총 {len(total)}개)")

    if not total:
        print("조건 만족 종목이 없습니다.")
        return

    # Supabase 'TRIPLE D PAPA' 테이블에 적재
    supabase.table("TRIPLE D PAPA").upsert(total).execute()
    print(f"★ 성공! 총 {len(total)}개 종목이 Supabase에 저장되었습니다. ★")

if __name__ == "__main__":
    main()

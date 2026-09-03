import re
import requests
from datetime import datetime
from supabase import create_client, Client

SUPABASE_URL = "https://xnjnknhwezminpdmsrtm.supabase.co"
SUPABASE_KEY = "sb_publishable_qBB0Q_OsOCcHWtSNoXsyZg_raCUUTfn"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_top_trading_stocks(sosok, market_name):
    # sosok: 0 = 코스피, 1 = 코스닥 (네이버 금융 거래대금 상위 페이지)
    url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = "euc-kr"
        html = res.text
    except Exception as e:
        print(f"{market_name} 요청 실패: {e}")
        return []

    # 테이블 행(tr) 단위 분리
    rows = html.split("<tr")
    today_str = datetime.today().strftime("%Y-%m-%d")
    results = []

    for r in rows:
        # 종목 링크가 포함된 행만 파싱
        if "code=" not in r or "title=" not in r:
            continue

        try:
            # 종목코드 & 종목명 추출
            code_match = re.search(r'code=([0-9A-Za-z]+)', r)
            name_match = re.search(r'class="tltle"[^>]*>([^<]+)</a>', r)
            if not code_match or not name_match:
                continue

            ticker = code_match.group(1).strip()
            name = name_match.group(1).strip()

            # 모든 td 태그의 텍스트 추출
            tds = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
            clean_tds = [re.sub(r'<[^>]+>', '', td).strip().replace(',', '') for td in tds]

            if len(clean_tds) < 7:
                continue

            # clean_tds 인덱스 구성:
            # [1]: 종목명, [2]: 현재가, [3]: 전일비, [4]: 등락률, [5]: 거래량, [6]: 거래대금(백만원)
            close_price = int(clean_tds[2])
            change_rate = float(clean_tds[4].replace('%', ''))
            trade_amount_million = int(clean_tds[6])
            trade_amount = trade_amount_million * 1_000_000  # 원 단위 환산

            # 조건 1: 거래대금 500억 이상 (50,000,000,000원)
            if trade_amount < 50_000_000_000:
                continue

            # 조건 2: 양봉 마감 (당일 상승 또는 보합)
            if change_rate < 0:
                continue

            results.append({
                "date": today_str,
                "ticker": ticker,
                "name": name,
                "market": market_name,
                "close_price": close_price,
                "change_rate": change_rate,
                "trade_amount": trade_amount,
                "double_buy_sum": int(trade_amount * 0.1)
            })
        except Exception:
            continue

    return results

def main():
    print("=== 거래대금 500억 이상 & 양봉 종목 스크리닝 시작 ===")
    kospi = fetch_top_trading_stocks(0, "KOSPI")
    kosdaq = fetch_top_trading_stocks(1, "KOSDAQ")
    total = kospi + kosdaq

    print(f"조건 만족 종목 수: 코스피 {len(kospi)}개 / 코스닥 {len(kosdaq)}개 (총 {len(total)}개)")

    if not total:
        print("조건 만족 종목이 없습니다.")
        return

    # Supabase 'TRIPLE D PAPA' 테이블에 적재
    supabase.table("TRIPLE D PAPA").upsert(total).execute()
    print(f"★ 성공! 총 {len(total)}개 종목이 Supabase에 저장되었습니다. ★")

if __name__ == "__main__":
    main()

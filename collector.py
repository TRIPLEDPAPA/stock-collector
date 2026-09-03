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

def get_investor_trend(ticker):
    """네이버 모바일 API에서 당일 외인, 기관, 개인 순매수량(주) 한 번에 추출"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/trend"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                latest = data[0]
                
                frg = int(str(latest.get("foreignerPureBuyQuant", 0)).replace(",", ""))
                inst = int(str(latest.get("organPureBuyQuant", 0)).replace(",", ""))
                retail = int(str(latest.get("individualPureBuyQuant", 0)).replace(",", ""))
                
                return frg, inst, retail
    except Exception:
        pass
    return 0, 0, 0

def fetch_screened_stocks(sosok, market_name):
    url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}&order=deal_amount"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
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
            code_m = re.search(r'code=([0-9A-Za-z]+)', r)
            name_m = re.search(r'class="tltle"[^>]*>([^<]+)</a>', r)
            if not code_m or not name_m:
                continue

            ticker = code_m.group(1).strip()
            name = name_m.group(1).strip()

            tds = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
            clean = [re.sub(r'<[^>]+>', '', td).strip().replace(',', '') for td in tds]
            if len(clean) < 11:
                continue

            close_price = int(clean[2])
            change_rate = float(clean[4].replace('%', ''))
            trade_amount_million = int(clean[6])
            trade_amount_won = trade_amount_million * 1_000_000
            open_price = int(clean[7])
            high_price = int(clean[8])

            # 전일가 계산
            diff_str = clean[3].replace('상승', '').replace('하락', '').replace('보합', '').strip()
            diff_price = int(diff_str) if diff_str.isdigit() else 0
            if change_rate > 0:
                prev_close = close_price - diff_price
            elif change_rate < 0:
                prev_close = close_price + diff_price
            else:
                prev_close = close_price

            # 기본 필터: 거래대금 500억 이상, 당일 양봉, 등락률 3~18%
            if trade_amount_million < 50_000 or close_price < open_price or not (3.0 <= change_rate <= 18.0):
                continue

            # 개인, 외국인, 기관 수급 조회
            foreign_buy, inst_buy, retail_buy = get_investor_trend(ticker)

            item_data = {
                "date": today_str,
                "ticker": ticker,
                "name": name,
                "market": market_name,
                "close_price": int(close_price),
                "open_price": int(open_price),
                "prev_close": int(prev_close),
                "change_rate": float(change_rate),
                "trade_amount": int(trade_amount_won),
                "double_buy_sum": int(trade_amount_won * 0.1),
                "foreign_net_buy": int(foreign_buy),
                "inst_net_buy": int(inst_buy),
                "retail_net_buy": int(retail_buy)
            }
            results.append(item_data)
            print(f"[{market_name}] {name} (외인:{foreign_buy:,} / 기관:{inst_buy:,} / 개인:{retail_buy:,})")
        except Exception as err:
            continue

    return results

def main():
    print("=== 수급 3주체(개인/외인/기관) 데이터 수집 시작 ===")
    kospi = fetch_screened_stocks(0, "KOSPI")
    kosdaq = fetch_screened_stocks(1, "KOSDAQ")
    total = kospi + kosdaq

    print(f"총 만족 종목: {len(total)}개")
    if not total:
        print("조건 만족 종목 없음.")
        return

    # [핵심] 저장 전에 오늘 날짜 기존 데이터를 먼저 깨끗하게 비웁니다.
    today_str = datetime.today().strftime("%Y-%m-%d")
    supabase.table("TRIPLE D PAPA").delete().eq("date", today_str).execute()

    # 새 데이터 일괄 삽입
    supabase.table("TRIPLE D PAPA").insert(total).execute()
    print("★ 기존 데이터 정리 후 신규 수급 데이터 정상 적재 완료 ★")

if __name__ == "__main__":
    main()

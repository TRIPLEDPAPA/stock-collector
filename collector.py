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
        return int(str(val).replace(",", "").replace("+", "").strip())
    except Exception:
        return 0

def get_investor_trend(ticker):
    """네이버 모바일 API에서 당일 외인, 기관, 개인 순매수량(주) 추출"""
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

            close_price = parse_int_safe(clean[2])
            change_rate = float(clean[4].replace('%', ''))
            trade_amount_million = parse_int_safe(clean[6])
            trade_amount_won = trade_amount_million * 1_000_000
            open_price = parse_int_safe(clean[7])
            high_price = parse_int_safe(clean[8])

            # 전일 종가 계산
            diff_str = clean[3].replace('상승', '').replace('하락', '').replace('보합', '').strip()
            diff_price = parse_int_safe(diff_str)
            if change_rate > 0:
                prev_close = close_price - diff_price
            elif change_rate < 0:
                prev_close = close_price + diff_price
            else:
                prev_close = close_price

            # 조건: 거래대금 500억 이상, 양봉(종가 >= 시가), 등락률 3~18%
            if trade_amount_million < 50_000 or close_price < open_price or not (3.0 <= change_rate <= 18.0):
                continue

            # 수급 데이터 조회
            foreign_buy, inst_buy, retail_buy = get_investor_trend(ticker)

            item_data = {
                "date": today_str,
                "ticker": ticker,
                "name": name,
                "market": market_name,
                "close_price": close_price,
                "open_price": open_price,
                "prev_close": prev_close,
                "change_rate": round(change_rate, 2),
                "trade_amount": trade_amount_won,
                "double_buy_sum": int(trade_amount_won * 0.1),
                "foreign_net_buy": foreign_buy,
                "inst_net_buy": inst_buy,
                "retail_net_buy": retail_buy
            }
            results.append(item_data)
            print(f"[{market_name}] 추출: {name} (외인:{foreign_buy:,} / 기관:{inst_buy:,} / 개인:{retail_buy:,})")
        except Exception:
            continue

    return results

def main():
    print("=== 수급 및 주가 적재 파이프라인 시작 ===")
    kospi = fetch_screened_stocks(0, "KOSPI")
    kosdaq = fetch_screened_stocks(1, "KOSDAQ")
    total = kospi + kosdaq

    print(f"추출 종목 수: 총 {len(total)}개")
    if not total:
        print("조건 만족 종목이 없습니다.")
        return

    today_str = datetime.today().strftime("%Y-%m-%d")
    
    try:
        # 오늘자 중복 방지를 위해 삭제 후 삽입
        supabase.table("TRIPLE D PAPA").delete().eq("date", today_str).execute()
        res = supabase.table("TRIPLE D PAPA").insert(total).execute()
        print("★ Supabase 저장 성공! 총 저장 행 수:", len(res.data))
    except Exception as e:
        print("★ Supabase 적재 에러 발생! 원인:", str(e))

if __name__ == "__main__":
    main()

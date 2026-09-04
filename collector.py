def evaluate_conditions(close_p, open_p, high_p, low_p, chg, deal_won, ma5, ma10, ma20, candles, current_vol):
    passed = []

    # 거래대금 구간 태그
    deal_tag = get_deal_amount_label(deal_won)
    if deal_tag != "100억미만":
        passed.append(deal_tag)
        passed.append("거래대금")

    # 1. 등락률, 양봉, 고가근접, 윗꼬리
    if 3.0 <= chg <= 18.0: passed.append("주가등락률")
    if close_p >= open_p and open_p > 0: passed.append("양봉마감")
    if high_p > 0 and (close_p / high_p) >= 0.95: passed.append("고가근접")

    rng = high_p - low_p
    tail = high_p - close_p
    if rng > 0 and (tail / rng) <= 0.25: passed.append("윗꼬리제한")

    # 2. 이평선 3개 (5일선, 10일선, 20일선 개별 체크)
    if ma5 > 0 and close_p >= ma5:
        passed.append("5일이평선")
    if ma10 > 0 and close_p >= ma10:
        passed.append("10일이평선")
    if ma20 > 0 and close_p >= ma20:
        passed.append("20일이평선")

    # 3. 단기이평정배열 (종가 >= 5일선 >= 10일선 >= 20일선)
    if ma5 > 0 and ma10 > 0 and ma20 > 0:
        if close_p >= ma5 and ma5 >= ma10 and ma10 >= ma20:
            passed.append("단기이평정배열")

    # 4. 거래량 비율 세분화 (전일 거래량 대비 100%, 150%, 200%)
    if len(candles) >= 1:
        prev_vol = candles[-1]["volume"]
        if prev_vol > 0 and current_vol > 0:
            vol_ratio = (current_vol / prev_vol) * 100.0
            if vol_ratio >= 100.0:
                passed.append("거래량100%")
            if vol_ratio >= 150.0:
                passed.append("거래량150%")
            if vol_ratio >= 200.0:
                passed.append("거래량200%")

    # 5. 최근 20일 주가 위치
    if len(candles) >= 20:
        highs = [c["high"] for c in candles[-20:]] + [high_p]
        lows = [c["low"] for c in candles[-20:]] + [low_p]
        mx, mn = max(highs), min(lows)
        if mx > mn and ((close_p - mn) / (mx - mn)) >= 0.70:
            passed.append("주가위치")

    return passed

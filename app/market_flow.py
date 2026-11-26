"""Read-only inputs for the order flow and option volume panels."""
import math


def quote_result(result):
    ret, data = result
    if ret != 0:
        raise ValueError(str(data)[:220])
    return data.to_dict('records')


def option_profile(ctx, symbol, expiry, rate_limit):
    rate_limit()
    chain = quote_result(ctx.get_option_chain(symbol, start=expiry, end=expiry))
    rows = {}
    contracts = {}
    for item in chain:
        strike = float(item['strike_price'])
        side = str(item['option_type']).lower()
        if math.isfinite(strike) and strike > 0 and side in {'call', 'put'}:
            contracts[item['code']] = (strike, side)
            rows.setdefault(strike, {'strike': strike, 'call': None, 'put': None})
    codes = list(contracts)
    for offset in range(0, len(codes), 400):
        rate_limit()
        for item in quote_result(ctx.get_market_snapshot(codes[offset:offset + 400])):
            contract = contracts.get(item['code'])
            volume = item.get('volume')
            if contract is None or volume is None or not math.isfinite(volume) or volume < 0:
                continue
            strike, side = contract
            rows[strike][side] = (rows[strike][side] or 0) + int(volume)
    return [rows[strike] for strike in sorted(rows)]


def ticker_rows(ctx, symbol):
    result = []
    for row in quote_result(ctx.get_rt_ticker(symbol, num=1000)):
        price, volume = float(row['price']), float(row['volume'])
        if not (math.isfinite(price) and math.isfinite(volume) and price > 0 and volume > 0):
            continue
        result.append({'sequence': str(row['sequence']), 'time': str(row['time']),
                       'price': price, 'volume': volume, 'direction': str(row['ticker_direction'])})
    return result

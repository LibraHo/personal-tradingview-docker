"""Current chip summary in Qot_StockScreen (3252), fetched one page at a time."""
import math
import re
import threading
import time
from collections import OrderedDict, deque


# Property identifiers from moomoo.quote.stock_screen_const.
MARKET = {'US': 2, 'CN': 3}
CODE = 1101
MARKET_CAP = 2301
RATIOS = {5101: 'profit_ratio', 5102: 'interval_overlap'}


def fill_request(req, market, offset, limit):
    # Populate only the typed fields needed here. The 10.10 SDK's generic
    # dictionary converter depends on FieldDescriptor.label, removed in protobuf 7.
    c2s = req.c2s
    c2s.pageFrom, c2s.pageCount = offset, limit
    criterion = c2s.filterList.add().simpleFieldQuery
    criterion.simpleField = 1  # SimpleField.MARKET
    criterion.screenValueList.append(MARKET[market])
    c2s.sort.direction = 2  # ScrSortDir.DESC
    c2s.sort.simpleProperty.name = MARKET_CAP
    c2s.retrieveList.add().basicProperty.name = CODE
    for prop in RATIOS:
        c2s.retrieveList.add().featuredProperty.name = prop


def stock_symbol(market, code):
    if market == 'US' and re.fullmatch(r'[A-Z][A-Z0-9.]{0,11}', code):
        return 'US.' + code
    if market == 'CN' and re.fullmatch(r'[0-9]{6}', code):
        if code.startswith(('6', '900')):
            return 'SH.' + code
        if code.startswith(('0', '3', '200')):
            return 'SZ.' + code
    return None


def chip_page(response, market):
    if response.retType:
        return -1, response.retMsg, None
    if not response.HasField('s2c') or not response.s2c.HasField('allCount') or response.s2c.allCount < 0:
        return -1, 'OpenD 筹码分页缺少证券总数', None
    rows = []
    for item in response.s2c.dataList:
        code = ''
        ratios = dict.fromkeys(RATIOS.values())
        for result in item.results:
            if result.HasField('basicPropertyResult'):
                value = result.basicPropertyResult
                if value.property.name == CODE and value.valueType == 1 and value.HasField('sval'):
                    code = value.sval
            elif result.HasField('featuredPropertyResult'):
                value = result.featuredPropertyResult
                field = RATIOS.get(value.property.name)
                if field and value.valueType == 4 and value.HasField('dval'):
                    number = value.dval
                    if math.isfinite(number) and 0 <= number <= 1:
                        ratios[field] = number
        symbol = stock_symbol(market, code)
        if symbol:
            rows.append({'symbol': symbol, **ratios})
    return 0, '', {'rows': rows, 'total': response.s2c.allCount}


def request_page(ctx, market, offset, limit):
    from moomoo.common.pb.Qot_StockScreen_pb2 import Request
    from moomoo.quote.quote_query import ProtoId, pack_pb_req

    def pack(conn_id):
        req = Request()
        fill_request(req, market, offset, limit)
        return pack_pb_req(req, ProtoId.Qot_StockScreen, conn_id)

    # Use the same synchronized protocol transport as get_stock_screen, retaining
    # SDK framing and encryption. HasField handles optional proto2 scalars on all versions.
    query = ctx._get_sync_query_processor(pack, lambda response: chip_page(response, market))
    ret, detail, page = query(conn_id=ctx.get_sync_conn_id())
    if ret:
        raise RuntimeError(f'OpenD 筹码汇总不可用：{detail}')
    return page


class ChipPages:
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.requests = deque()

    def get(self, market, offset, limit, fetch):
        if market not in MARKET or type(offset) is not int or not 0 <= offset <= 2**31 - 1:
            raise ValueError('筹码查询需要 CN 或 US 市场及有效分页起点')
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('筹码单页证券数须在 1 至 200 之间')
        key = (market, offset, limit)
        with self.lock:
            now = time.monotonic()
            cached = self.cache.get(key)
            if cached and now - cached[0] < 60:
                self.cache.move_to_end(key)
                return cached[1]
            while self.requests and now - self.requests[0] >= 30:
                self.requests.popleft()
            if len(self.requests) >= 10:
                raise RuntimeError('OpenD 筹码筛选已达到每 30 秒 10 次的限额，请稍后重试')
            self.requests.append(now)
            page = fetch(market, offset, limit)
            self.cache[key] = time.monotonic(), page
            self.cache.move_to_end(key)
            if len(self.cache) > 64:
                self.cache.popitem(last=False)
            return page

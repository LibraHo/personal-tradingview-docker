"""Source-separated breadth and limit-pool statistics. Missing values stay missing."""
import asyncio
import json
import time
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo


def pool(endpoint, day):
    rows={}; total=None; page=0
    while True:
        params=dict(ut='7eea3edcaed734bea9cbfc24409ed989',dpt='wz.ztzt',Pageindex=page,pagesize=100,
                    sort='fund:asc' if endpoint=='getTopicDTPool' else 'zdp:desc' if endpoint=='getTopicQSPool' else 'fbt:asc',date=day.replace('-',''))
        url='https://push2ex.eastmoney.com/'+endpoint+'?'+urllib.parse.urlencode(params)
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'})
        with urllib.request.urlopen(req,timeout=15) as response: raw=json.load(response)
        data=raw.get('data')
        # qdate is the server's latest available date, not the requested historical
        # pool date (verified against OpenD historical closes on 2026-11-16).
        if raw.get('rc')!=0 or not isinstance(data,dict) or str(data.get('qdate',''))<day.replace('-',''):
            raise ValueError(endpoint+' 数据缺失或交易日期不符')
        total=int(data['tc']);before=len(rows)
        records=data.get('pool')
        if records is None and total==0:
            records=[]
        if not isinstance(records,list) or len(records)<min(100,max(0,total-page*100)):
            raise ValueError(endpoint+' 名单不完整')
        for r in records:
            code=str(r.get('c',''))
            if r.get('m') not in (0,1):continue
            symbol=('SH.' if r['m']==1 else 'SZ.')+code
            amount, float_cap, funds = r.get('amount'), r.get('ltsz'), r.get('fund')
            rows[symbol]={'symbol':symbol,'name':r.get('n',''),'change':r.get('zdp'),'streak':r.get('lbc'),
                          'reopen_count':r.get('zbc'),'industry':r.get('hybk'),
                          'turnover_amount':amount,'turnover_pct':r.get('hs'),'float_market_cap':float_cap,
                          'seal_to_turnover_pct':100*funds/amount if funds is not None and amount and amount>0 else None,
                          'seal_to_float_pct':100*funds/float_cap if funds is not None and float_cap and float_cap>0 else None,
                          'first_seal':r.get('fbt'),'last_seal':r.get('lbt'),'sealed_funds':r.get('fund'),'price':None if r.get('p') is None else r['p']/1000}
        if len(records)<100 or (page+1)*100>=total:break
        if len(rows)==before:raise ValueError('涨停池分页重复')
        page+=1
        if page>100:raise ValueError('涨停池分页超过上限')
        time.sleep(.3)
    return {'rows':list(rows.values()),'source_total':total,'trade_date':day,'upstream_latest_date':data.get('qdate'),'updated':time.time(),
            'coverage':len(rows)/total if total else 1,'source':'Eastmoney '+endpoint}


def ladder(current, previous, broken):
    now={r['symbol']:r for r in current};before={r['symbol']:r for r in previous}
    levels=[];advances=[]
    for level in sorted({r['streak'] for r in current if isinstance(r.get('streak'),int)},reverse=True):
        rows=[r for r in current if r.get('streak')==level]
        levels.append({'level':level,'count':len(rows),'stocks':rows})
    for level in sorted({r['streak'] for r in previous if isinstance(r.get('streak'),int)}):
        cohort=[r for r in previous if r['streak']==level]
        success=sum(1 for r in cohort if now.get(r['symbol'],{}).get('streak',0)>=level+1)
        advances.append({'from':level,'to':level+1,'denominator':len(cohort),'success':success,'rate':success/len(cohort)})
    failed={r['symbol'] for r in broken}-set(now)
    denominator=len(failed|set(now))
    return {'levels':levels,'max_streak':max([r.get('streak') or 1 for r in current] or [0]),'promotion':advances,
        'broken_count':len(failed),'broken_denominator':denominator,'broken_rate':len(failed)/denominator if denominator else None,
        'definition':'炸板为触及涨停但当前未封板的去重标的；炸板率=炸板/(炸板+当前封板)。晋级分母为上一交易日同高度涨停池，分子为今日连续高度增加者。按上游实际涨停池分类，不使用统一10%阈值。'}


class Analytics:
    def __init__(self,service):
        self.service=service;self.state={};self.tasks={}
        self.board_lock=threading.Lock()

    def limit_board(self, day=None):
        now=datetime.now(ZoneInfo('Asia/Shanghai'))
        today=now.date().isoformat()
        days=self.service.calendar.days('SH.600000')
        dates=sorted((d for d in days if d<today or (d==today and (now.hour,now.minute)>=(9,25))), reverse=True)[:5]
        if not dates:
            raise ValueError('暂无沪深交易日历')
        day=day or dates[0]
        if day not in dates:
            raise ValueError('请选择最近五个交易日')
        def fetch():
            sealed=pool('getTopicZTPool',day)['rows']
            opened=pool('getTopicZBPool',day)['rows']
            current={r['symbol'] for r in sealed}
            broken=[r for r in opened if r['symbol'] not in current]
            return {'trade_date':day,'sealed':sealed,'broken':broken}
        snapshot=self.service.radar.cached('limit-board:v2:'+day,120,fetch,lock=self.board_lock)
        return {**snapshot,'dates':dates,'source':'东方财富沪深涨停池、炸板池'}

    def get(self, market, refresh=False):
        if market not in ('CN','US'):raise ValueError('市场无效')
        state=self.state.get(market)
        if market not in self.tasks and (not state or refresh or time.time()-state.get('updated',0)>300):
            self.state[market]={'status':'running','done':0,'total':0,'updated':time.time(),'previous':state.get('result') if state else None}
            self.tasks[market]=self.service.launch(self.run(market))
        return self.state[market]

    async def run(self,market):
        state=self.state[market]
        try:
            result=await (self.cn(state) if market=='CN' else self.us(state))
            state.update(status='completed',result=result,updated=time.time())
        except Exception as e:state.update(status='failed',error=str(e),updated=time.time())
        finally:self.tasks.pop(market,None)

    async def cn(self,state):
        s=self.service;days=await asyncio.to_thread(s.calendar.days,'SH.600000')
        now=datetime.now(ZoneInfo('Asia/Shanghai'));today=str(now.date())
        eligible=sorted(d for d in days if d<today or (d==today and now.hour>=9))
        current,previous=eligible[-1],eligible[-2]
        pools={};state['total']=5
        for name,endpoint,day in [('up','getTopicZTPool',current),('broken','getTopicZBPool',current),('down','getTopicDTPool',current),('previous','getTopicZTPool',previous),('strong','getTopicQSPool',previous)]:
            try:pools[name]=await asyncio.to_thread(s.radar.cached,'pool:'+endpoint+':'+day,120,lambda ep=endpoint,d=day:pool(ep,d))
            except Exception as e:pools[name]={'error':str(e),'rows':None}
            state['done']+=1
        result={'market':'CN','trade_date':current,'previous_trade_date':previous,'pools':pools,'source':'Eastmoney limit pools + OpenD snapshots',
                'scope':'沪深证券，上游涨停/炸板/跌停/强势池；并非 OpenD 全市场分布的同一统计范围',
                'coverage_note':'覆盖率为返回去重沪深标的/数据源公布池总数；不能代表全市场覆盖率。停牌或未返回快照从反馈分母中排除。'}
        if all(pools[k].get('rows') is not None and not pools[k].get('stale') for k in ('up','broken')):
            result.update(ladder(pools['up']['rows'],pools['previous'].get('rows') or [],pools['broken']['rows']))
            if pools['previous'].get('rows') is None or pools['previous'].get('stale'):
                result['promotion']=[];result['promotion_error']='昨日涨停池缺失或过期，不能计算晋级'
        result['feedback']={}
        for key in ('previous','strong'):
            cohort=pools[key].get('rows')
            if cohort is None:result['feedback'][key]={'error':pools[key]['error']};continue
            values=[];missing=[];details=[]
            for start in range(0,len(cohort),100):
                codes=[r['symbol'] for r in cohort[start:start+100]]
                quotes,stale=await asyncio.to_thread(s.main.bridge.snapshots,codes)
                by={r['symbol']:r for r in quotes}
                for code in codes:
                    q=by.get(code,{})
                    if stale or q.get('change_percent') is None or not str(q.get('update_time','')).startswith(current):missing.append(code)
                    else:values.append(q['change_percent']);details.append(q)
            result['feedback'][key]={'cohort_date':previous,'trade_date':current,'expected':len(cohort),'denominator':len(values),
                'coverage':len(values)/len(cohort) if cohort else None,'average_change':sum(values)/len(values) if values else None,
                'up_ratio':sum(v>0 for v in values)/len(values) if values else None,'missing':missing,'quotes':details,
                'definition':'昨日数据源涨停池/强势池固定成分，今日快照涨跌幅等权平均；只纳入行情日期为今日的有效标的'}
        return result

    async def us(self,state):
        s=self.service;watch=s.watchlists()
        symbols=sorted({c for g in watch['groups'] for c in g.get('symbols',[]) if c.startswith('US.') and '.LIST' not in c and '.BK' not in c})
        state['total']=len(symbols)+13
        rows=[];failed=[]
        for symbol in symbols:
            try:
                bars=[b for b in await s.load(symbol,'1d') if b['confirmed']]
                if len(bars)<51:raise ValueError('MA50 与涨跌需要至少51根完整日线')
                close=bars[-1]['close'];prev=bars[-2]['close']
                rows.append({'symbol':symbol,'time':bars[-1]['time'],'change':(close/prev-1)*100,
                    'ma20':close>sum(b['close'] for b in bars[-20:])/20,'ma50':close>sum(b['close'] for b in bars[-50:])/50,
                    'new_high':close>max(b['close'] for b in bars[-253:-1]) if len(bars)>=253 else None,
                    'new_low':close<min(b['close'] for b in bars[-253:-1]) if len(bars)>=253 else None})
            except Exception as e:failed.append({'symbol':symbol,'error':str(getattr(e,'detail',e))})
            state['done']+=1
        from .radar import US_SECTORS
        proxies=[]
        for code,name in [*US_SECTORS,('SPY','市值加权'),('RSP','等权')]:
            try:
                bars=[b for b in await s.load('US.'+code,'1d') if b['confirmed']]
                proxies.append({'symbol':'US.'+code,'name':name,'change':(bars[-1]['close']/bars[-2]['close']-1)*100,'time':bars[-1]['time'],'instrument':'ETF proxy'})
            except Exception as e:proxies.append({'symbol':'US.'+code,'name':name,'error':str(getattr(e,'detail',e))})
            state['done']+=1
        n=len(rows);long=[r for r in rows if r['new_high'] is not None]
        return {'market':'US','scope':'NAS 美股关注列表去重样本（可能含 ETF），不是全市场或标普500成分股',
            'expected':len(symbols),'denominator':n,'coverage':n/len(symbols) if symbols else None,'rows':rows,'failures':failed,
            'above_ma20_ratio':sum(r['ma20'] for r in rows)/n if n else None,'above_ma50_ratio':sum(r['ma50'] for r in rows)/n if n else None,
            'high_low_denominator':len(long),'new_high':sum(r['new_high'] for r in long),'new_low':sum(r['new_low'] for r in long),
            'up':sum(r['change']>0 for r in rows),'down':sum(r['change']<0 for r in rows),'flat':sum(r['change']==0 for r in rows),
            'up_ratio':sum(r['change']>0 for r in rows)/n if n else None,'proxies':proxies,
            'trade_date':datetime.fromtimestamp(rows[0]['time'],ZoneInfo('America/New_York')).date().isoformat() if rows else None,
            'definition':'最近完成交易日；MA20/MA50含当日收盘；新高/新低为当日收盘严格超过/低于前252根日线收盘极值；不足253根从该指标分母排除。均采用与图表一致的不复权价格。',
            'industry_diffusion':{'up':sum(r.get('change',0)>0 for r in proxies[:11]),'denominator':sum('change' in r for r in proxies[:11]),'definition':'11行业ETF中当日上涨的ETF比例，不代表个股宽度'}}

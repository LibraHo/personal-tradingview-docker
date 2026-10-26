"""Small bounded monitor scheduler inside the TLS trading gateway."""
import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from fastapi import HTTPException, Request
from .strategy_rules import validate_strategy, PERIOD_SECONDS
from .strategy_store import StrategyStore


async def market_evaluate(config,lease=False):
    url=os.getenv('MARKET_INTERNAL_URL','http://market:8000').rstrip('/')+'/api/strategy/evaluate'
    def read():
        req=urllib.request.Request(url,data=json.dumps({'config':config,'lease':lease}).encode(),headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=25) as response:return json.load(response)
        except urllib.error.HTTPError as exc:
            try:message=json.load(exc).get('detail','指标计算失败')
            except Exception:message='指标计算失败'
            raise ValueError(str(message))
    try:return await asyncio.to_thread(read)
    except (OSError,urllib.error.URLError) as exc:raise ValueError('行情服务暂不可用，策略未下单') from exc


def register_strategy_api(app,root,sessions,rpc):
    store=StrategyStore(root/'strategies.sqlite3')
    app.state.strategies=store
    async def checked_config(body):
        try:return validate_strategy(body)
        except (ValueError,SyntaxError,TypeError) as exc:raise HTTPException(400,str(exc))

    @app.get('/api/trade/strategies')
    async def listing():return {'strategies':store.list()}

    @app.post('/api/trade/strategies/save')
    async def save(body:dict):
        await checked_config(body)
        try:return store.save(body)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/trade/strategies/test')
    async def test(body:dict):
        cfg=await checked_config(body)
        try:return await market_evaluate(cfg)
        except ValueError as exc:raise HTTPException(400,str(exc))

    def item(sid):
        try:return store.get(sid)
        except ValueError as exc:raise HTTPException(404,str(exc))

    @app.post('/api/trade/strategies/start')
    async def start(body:dict):
        sid=str(body.get('id',''));current=item(sid)
        try:
            if body.get('enabled') is not True:return store.start(sid,False)
            baseline=await market_evaluate(current['config'],True)
            if baseline.get('stale'):raise ValueError('行情为缓存，暂不能启动监控')
            if store.get(sid)['revision']!=current['revision']:raise ValueError('配置已变化，请重新启动')
            store.event(sid,'START','从当前收线开始监控，不补下历史订单',baseline)
            return store.start(sid,True,baseline)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/trade/strategies/delete')
    async def delete(body:dict):
        sid=str(body.get('id',''));item(sid);store.delete(sid);return {'ok':True}

    @app.get('/api/trade/strategies/events')
    async def events(id:str):item(id);return {'events':store.events(id)}

    @app.post('/api/trade/strategies/arm')
    async def arm(body:dict,request:Request):
        sid=str(body.get('id',''));current=item(sid)
        if body.get('confirm')!='ARM STRATEGY':raise HTTPException(400,'请确认关闭网页后策略仍可在授权期限内自动下单')
        acc=str(body.get('acc_id',''));env=body.get('env')
        if env not in {'REAL','SIMULATE'}:raise HTTPException(400,'请选择交易环境')
        if not current['enabled']:raise HTTPException(400,'请先启动信号监控')
        if current['config']['execution']['session']!='RTH':raise HTTPException(400,'首版自动策略仅支持 RTH，其他时段可监控信号')
        # Authorize using the existing account/grant checks, without placing anything.
        state=await rpc('strategy_authorize',request.state.owner,acc,env)
        expiry=min(time.time()+600,state['expires'])
        if store.get(sid)['revision']!=current['revision']:raise HTTPException(400,'策略已修改，请重新确认授权')
        try:store.arm(sid,request.state.owner,acc,env,expiry)
        except ValueError as exc:raise HTTPException(400,str(exc))
        return store.get(sid)

    @app.post('/api/trade/strategies/disarm')
    async def disarm(body:dict):
        sid=str(body.get('id',''));item(sid);store.disarm(sid);return store.get(sid)

    async def poll_once():
        for item_value in store.list():
            if not item_value['enabled']:continue
            sid=item_value['id'];cfg=item_value['config']
            try:
                result=await market_evaluate(cfg,True)
                current=store.get(sid)
                if not current['enabled'] or current['revision']!=item_value['revision']:continue
                if result.get('stale'):
                    if current['status']!='行情过期，暂停信号执行':store.event(sid,'STALE','行情过期，暂停信号执行')
                    continue
                stamp=result['bar_time']
                missed=stamp-current['last_bar']>PERIOD_SECONDS[cfg['period']]*1.5 or time.time()-result['bar_end']>90
                if not store.claim(sid,stamp,missed,current['revision']):continue
                if missed:continue
                side='BUY' if result['buy'] else 'SELL' if result['sell'] else None
                if result['buy'] and result['sell']:
                    store.event(sid,'CONFLICT','买卖条件同时满足，本根不执行',result);continue
                if side is None:
                    store.event(sid,'CHECK','已检查收线 · 条件未满足',result);continue
                store.event(sid,'SIGNAL',('买入' if side=='BUY' else '卖出')+'条件满足',result)
                arm_value=store.arms.get(sid)
                if not arm_value:continue
                owner_session=sessions.get(arm_value['owner'])
                if not owner_session or owner_session['expires']<=time.time() or arm_value['expires']<=time.time():
                    store.disarm(sid);continue
                if arm_value['executions']>=cfg['execution']['max_executions']:
                    store.disarm(sid);continue
                # Claiming the candle happened durably before any broker operation.
                operation=await rpc('strategy_execute',arm_value['owner'],cfg,side,result,arm_value)
                arm_value['executions']+=1
                store.event(sid,'ORDER','订单'+{'ACCEPTED':'接口已受理','REJECTED':'已拒绝','UNKNOWN':'结果待核对','SENDING':'发送中'}.get(operation['state'],operation['state']),
                            {'operation_id':operation['id'],'state':operation['state'],'bar_time':stamp})
                if operation['state']!='ACCEPTED' or arm_value['executions']>=cfg['execution']['max_executions']:
                    store.revoke(sid)
            except asyncio.CancelledError:raise
            except (ValueError,HTTPException) as exc:
                message=str(exc.detail if isinstance(exc,HTTPException) else exc)
                try:
                    store.revoke(sid)
                    if store.get(sid)['status']!=message:store.event(sid,'ERROR',message)
                except ValueError:pass
            except Exception:
                store.revoke(sid)
                try:store.event(sid,'ERROR','策略执行异常，自动执行已关闭；请核对流水')
                except Exception:pass
    app.state.strategy_poll_once=poll_once
    async def poll():
        while True:
            await poll_once()
            await asyncio.sleep(15)
    return poll

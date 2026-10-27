"""Durable, explicitly requested post-fill stops; never retry an ambiguous mutation."""
import json
import time
import uuid
from decimal import Decimal, ROUND_DOWN


def stop_config(raw):
    from .trading import TradeError, number
    if not isinstance(raw, dict):
        raise TradeError('止损方案格式不正确')
    name = str(raw.get('name', '')).strip()
    pct = number(raw.get('percent'), '止损比例')
    tolerance = number(raw.get('tolerance', 0), '美元容限', positive=False)
    mode = raw.get('mode', 'STOP')
    if not name or len(name) > 40 or pct >= 100 or mode not in {'STOP', 'STOP_LIMIT'}:
        raise TradeError('方案名称须为 1–40 字，止损比例须在 0 和 100 之间')
    if tolerance < 0 or tolerance > 100 or tolerance != tolerance.quantize(Decimal('.0001')):
        raise TradeError('美元容限须在 0–100 之间，最多四位小数')
    result=dict(name=name, percent=float(pct), mode=mode,
                tolerance=float(tolerance) if mode == 'STOP_LIMIT' else 0)
    if raw.get('trigger_price') is not None:
        trigger=number(raw['trigger_price'],'固定止损触发价')
        if trigger!=trigger.quantize(Decimal('.01')):
            raise TradeError('固定止损价格最多两位小数')
        result['trigger_price']=float(trigger)
    return result


def stop_prices(basis, config):
    from .trading import TradeError
    trigger = Decimal(str(config['trigger_price'])) if config.get('trigger_price') is not None else Decimal(str(basis)) * (1 - Decimal(str(config['percent'])) / 100)
    def rounded(value):
        return float(value.quantize(Decimal('.01') if config.get('option') or value >= 1 else Decimal('.0001'), rounding=ROUND_DOWN))
    trigger = rounded(trigger)
    limit = rounded(Decimal(str(trigger)) - Decimal(str(config['tolerance']))) if config['mode'] == 'STOP_LIMIT' else 0
    if trigger <= 0 or (config['mode'] == 'STOP_LIMIT' and limit <= 0):
        raise TradeError('止损比例或容限导致价格不大于零')
    return trigger, limit


class ProtectionMixin:
    def init_protection(self):
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS protection (id TEXT PRIMARY KEY, data TEXT)')
            rows = db.execute('SELECT id,data FROM protection').fetchall()
            for row in rows:
                p = json.loads(row['data'])
                if p['state'] == 'WAITING':
                    p.update(state='PAUSED', message='服务已重启，请核对买单和止损后重新启用跟进')
                    db.execute('UPDATE protection SET data=? WHERE id=?', (json.dumps(p), row['id']))

    def save_protection(self, p, db=None):
        if db is not None:
            db.execute('INSERT OR REPLACE INTO protection VALUES (?,?)', (p['id'], json.dumps(p)))
        else:
            with self.db() as conn:
                self.save_protection(p, conn)

    def protections(self, acc=None, env=None):
        with self.db() as db:
            rows = db.execute('SELECT data FROM protection ORDER BY rowid DESC').fetchall()
        return [p for row in rows if (p := json.loads(row[0])) and
                (acc is None or (p['acc_id'] == str(acc) and p['env'] == env))]

    def create_protection(self, op_id, owner, order, db):
        if 'protection' not in order:
            return
        self.save_protection(dict(id=op_id, owner=owner, acc_id=order['acc_id'], env=order['env'],
            code=order['code'], config=order['protection'], state='WAITING', covered=0,
            covered_value=0, pending=None, children=[], message='等待买入成交；尚未建立止损', created=time.time()), db)

    def pause_protections(self, message):
        for p in self.protections():
            if p['state'] == 'WAITING':
                p.update(state='PAUSED', message=message)
                self.save_protection(p)

    def resume_protection(self, owner, plan_id):
        from .trading import TradeError
        p = next((x for x in self.protections() if x['id'] == plan_id), None)
        if not p or p['state'] != 'PAUSED':
            raise TradeError('方案不存在或不需要恢复')
        self.authorize(owner, p['acc_id'], p['env'])
        # Original owner may have logged out. The new, unlocked operator explicitly adopts it.
        p.update(owner=owner, state='WAITING', message='已恢复，正在核对券商成交与止损记录')
        self.save_protection(p)
        return {'ok': True}

    def protection_tick(self):
        from .trading import TradeError, ACTIVE
        for p in self.protections():
            if p['state'] != 'WAITING':
                continue
            try:
                self.authorize(p['owner'], p['acc_id'], p['env'])
                parent_op = self.operation(p['id'])
                if parent_op['state'] not in {'ACCEPTED', 'RECONCILED'}:
                    raise TradeError('买单结果未确认，请先核对操作流水')
                rows = self.broker.orders(p['acc_id'], p['env'])
                parent = next((r for r in rows if r.get('remark') == 'NMT:' + p['id']), None)
                if not parent:
                    raise TradeError('未查到买单，请在 moomoo 核对')
                for child_id in p['children']:
                    prior = next((r for r in rows if r.get('remark') == 'NMT:' + child_id), None)
                    if not prior or prior.get('order_status') not in {'SUBMITTED', 'FILLED_PART', 'FILLED_ALL'}:
                        raise TradeError('先前止损已失效或无法确认，后续跟进暂停；请人工核对')
                # A persisted child intent is resolved before considering another fill.
                pending = p['pending']
                if pending:
                    op = self.operation(pending['id'])
                    if op is None:
                        # Intent saved but no mutation journal: safe to construct it again.
                        preview = self.preview(p['owner'], pending['order'])
                        op = self.commit(p['owner'], preview['preview_id'], pending['id'])
                    child = next((r for r in rows if r.get('remark') == 'NMT:' + pending['id']), None)
                    if op['state'] not in {'ACCEPTED', 'RECONCILED'}:
                        raise TradeError('止损提交结果未确认，请核对流水；不会自动重发')
                    if child is None or child.get('order_status') in {'UNSUBMITTED', 'WAITING_SUBMIT', 'SUBMITTING'}:
                        p['message'] = '止损请求已受理，等待券商订单确认'
                        self.save_protection(p)
                        continue
                    if child.get('order_status') not in {'SUBMITTED', 'FILLED_PART', 'FILLED_ALL'}:
                        raise TradeError('止损未处于有效状态，请在 moomoo 核对处理')
                    if float(child.get('qty') or 0) != pending['qty'] or child.get('trd_side') != 'SELL' or child.get('code') != p['code'] or child.get('order_type') != p['config']['mode']:
                        raise TradeError('止损订单内容已变化，请人工核对保护数量')
                    if float(child.get('aux_price') or 0) != pending['order']['aux_price'] or (p['config']['mode'] == 'STOP_LIMIT' and float(child.get('price') or 0) != pending['order']['price']):
                        raise TradeError('止损价格已变化，请人工核对')
                    p['covered'] += pending['qty']
                    p['covered_value'] += pending['value']
                    p['children'].append(pending['id'])
                    p['pending'] = None
                    self.save_protection(p)
                filled = float(parent.get('dealt_qty') or 0)
                if filled < p['covered'] or filled != int(filled):
                    raise TradeError('成交数量出现校正或碎股，请人工核对保护数量')
                delta = int(filled) - p['covered']
                if delta:
                    value = filled * float(parent.get('dealt_avg_price') or 0) - p['covered_value']
                    if value <= 0:
                        raise TradeError('无法确定新增成交均价，请人工核对')
                    trigger, limit = stop_prices(value / delta, p['config'])
                    child_order = dict(acc_id=p['acc_id'], env=p['env'], code=p['code'], side='SELL',
                        order_type=p['config']['mode'], qty=delta, aux_price=trigger, price=limit,
                        session='RTH', time_in_force='DAY' if p['config'].get('option') else 'GTC')
                    # Persist before any possible child submission. Never recreate this ID.
                    p['pending'] = dict(id=str(uuid.uuid4()), qty=delta, value=value, order=child_order)
                    p['message'] = f'已成交 {int(filled)} 股，正在提交新增 {delta} 股的止损'
                    self.save_protection(p)
                    preview = self.preview(p['owner'], child_order)
                    op = self.commit(p['owner'], preview['preview_id'], p['pending']['id'])
                    if op['state'] not in {'ACCEPTED', 'RECONCILED'}:
                        raise TradeError('止损提交结果未确认，请核对流水；不会自动重发')
                elif parent.get('order_status') in {'FILLED_ALL', 'CANCELLED_ALL', 'CANCELLED_PART', 'FAILED', 'DELETED'}:
                    p.update(state='COMPLETE', message=f'买单已结束，累计确认止损委托 {p["covered"]} 股；当前有效性请查看券商订单')
                    self.save_protection(p)
                elif parent.get('order_status') in ACTIVE:
                    p['message'] = f'等待后续成交；累计确认止损委托 {p["covered"]} 股'
                    self.save_protection(p)
                else:
                    raise TradeError('买单状态无法识别，请人工核对')
            except Exception as exc:
                p.update(state='PAUSED', message=str(exc)[:300] if isinstance(exc, TradeError) else '连接异常，跟进已暂停，请核对买单与止损')
                self.save_protection(p)

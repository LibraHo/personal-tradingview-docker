"""Broker contracts and trusted deployment-time selection."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from importlib import import_module
from typing import Callable, Protocol


class TradeError(Exception):
    pass


class BrokerRejected(TradeError):
    pass


class BrokerUncertain(Exception):
    pass


STOCK_SYMBOL = re.compile(r'^US\.[A-Z][A-Z0-9.]{0,11}$')
OPTION_SYMBOL = re.compile(r'^US\.[A-Z][A-Z0-9.]{0,11}\d{6}[CP]\d{1,10}$')
SYMBOL = re.compile(r'^US\.(?:[A-Z][A-Z0-9.]{0,11}|[A-Z][A-Z0-9.]{0,11}\d{6}[CP]\d{1,10})$')


class ArchiveError(Exception):
    """An archive diagnostic suitable for the user."""


class ArchiveBroker(Protocol):
    def accounts(self) -> list[dict]: ...
    def archive_positions(self, account: str) -> list[dict]: ...
    def archive_fills(self, account: str, start: date, end: date, as_of: datetime) -> list[dict]: ...
    def close(self) -> None: ...


class TradingBroker(Protocol):
    generation: int

    def accounts(self) -> list[dict]: ...
    def positions(self, acc: str, env: str) -> list[dict]: ...
    def funds(self, acc: str, env: str) -> list[dict]: ...
    def orders(self, acc: str, env: str, refresh: bool = True) -> list[dict]: ...
    def capacity(self, order: dict, order_id: str | None = None) -> dict: ...
    def unlock(self, password: str | None = None, lock: bool = False) -> None: ...
    def quote(self, symbol: str) -> dict: ...
    def option_chain(self, symbol: str, expiry: str = '') -> dict: ...
    def place(self, order: dict, remark: str) -> list[dict]: ...
    def modify(self, order: dict, cancel: bool = False) -> list[dict]: ...
    def close(self) -> None: ...


CAPABILITIES = frozenset({'trading', 'archive'})


class InactiveBroker:
    generation = 0

    def accounts(self):
        return []

    def close(self):
        pass

    def __getattr__(self, name):
        raise TradeError('当前未启用券商交易接口')


@dataclass(frozen=True)
class BrokerConfig:
    source_id: str
    capabilities: frozenset[str]
    factory: Callable

    def trading_directory(self, base):
        return base if self.source_id == 'opend' else base / 'brokers' / ('source-' + self.source_id)

    def trading_broker(self):
        return self.factory() if 'trading' in self.capabilities else InactiveBroker()


def broker_config(injected=None):
    """Resolve provider identity before accessing its databases or opening a session."""
    if injected is not None:
        source = getattr(injected, 'source_id', 'opend')
        caps = getattr(injected, 'capabilities', CAPABILITIES)
        factory = lambda: injected
    else:
        market = (os.getenv('MARKET_DATA_PROVIDER') or 'opend').strip()
        routes = os.getenv('MARKET_DATA_ROUTES', '').strip()
        default = 'opend' if market == 'opend' and not routes else 'disabled'
        setting = (os.getenv('BROKER_PROVIDER') or default).strip()
        if setting == 'disabled':
            return BrokerConfig('disabled', frozenset(), InactiveBroker)
        if setting == 'opend':
            from .opend_broker import OpenDBroker
            return BrokerConfig('opend', CAPABILITIES, OpenDBroker)
        module, sep, name = setting.partition(':')
        if not sep or not module or not name:
            raise ValueError('BROKER_PROVIDER 须为 opend、disabled 或 module:factory')
        factory = getattr(import_module(module), name)
        source = getattr(factory, 'source_id', None)
        caps = getattr(factory, 'capabilities', ())
        if source in ('opend','disabled'):
            raise ValueError('外部券商需要独立的 source_id')
    if not isinstance(source,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,47}', source):
        raise ValueError('券商工厂需要稳定的小写 source_id')
    caps = frozenset(caps)
    if not caps or not caps <= CAPABILITIES or not callable(factory):
        raise ValueError('券商工厂须声明 trading 或 archive 能力')
    return BrokerConfig(source, caps, factory)

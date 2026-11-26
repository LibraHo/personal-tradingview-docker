"""Immutable scope and effective condition snapshots for scan history."""
import copy
import hashlib
import json
import time
from .advanced_indicators import DEFAULTS as ADVANCED_DEFAULTS
from .tdx_indicators import SPEC as TDX_SPEC


DEFAULT_PARAMS = {
    **{name: {'period': period} for name, period in
       [('SMA', 20), ('EMA', 20), ('RSI', 14), ('VOLUME', 20), ('DMI', 14), ('ATR', 14)]},
    'MACD': {'fast': 12, 'slow': 26, 'signal': 9},
    'BOLL': {'period': 20, 'stddev': 2},
    **ADVANCED_DEFAULTS,
}
FORMULA_REVISION = hashlib.sha256(json.dumps(TDX_SPEC, sort_keys=True).encode()).hexdigest()


def execution_plan(plan):
    result = copy.deepcopy(plan)
    for key, default in [('join', 'all'), ('lookback', 1), ('live', True)]:
        result.setdefault(key, default)
    for rule in result['rules']:
        for key, default in [('offset', 0), ('temporal', 'current'), ('window', 1),
                             ('min_count', 1), ('max_count', None), ('period', None)]:
            rule.setdefault(key, default)
        for side in ('left', 'right'):
            operand = rule[side]
            operand.setdefault('offset', 0)
            operand.setdefault('scale', 1)
            operand['params'] = {**DEFAULT_PARAMS.get(operand['name'], {}), **operand.get('params', {})}
            if operand['name'] in TDX_SPEC['indicators']:
                operand['formula_revision'] = FORMULA_REVISION
    return result


def scope_snapshot(scope, workspace, frozen_monitor=None):
    if frozen_monitor and frozen_monitor.get('targets') is not None:
        if frozen_monitor.get('scope_snapshot'):
            return copy.deepcopy(frozen_monitor['scope_snapshot'])
        return {'captured_at': time.time(), 'basis': 'legacy_fixed_targets',
                'kind': scope.get('kind', 'all'), 'market': scope.get('market'),
                'selected_groups': [], 'excluded_groups': [], 'missing_groups': [], 'empty_groups': [],
                'target_groups': sorted({name for row in frozen_monitor['targets'] for name in row.get('groups', [])})}
    market, kind = scope.get('market'), scope.get('kind', 'all')
    all_groups = []
    for area, value in workspace.get('markets', {'US': workspace}).items():
        if market and market != area:
            continue
        for group in value.get('groups', []):
            symbols = [code for code in group.get('symbols', []) if not market or
                       (code.startswith('US.') if market == 'US' else code.startswith(('SH.', 'SZ.')))]
            all_groups.append({'id': area + ':' + group['id'], 'name': group['name'],
                               'market': area, 'symbols': symbols, 'symbol_count': len(set(symbols))})
    selected, excluded = [], []
    wanted = scope.get('groups', [])
    for group in all_groups:
        include = (kind == 'all' or kind == 'groups' and group['id'] in wanted or
                   kind == 'favorites' and group['id'].endswith(':radar-favorites') or
                   kind in ('symbols', 'members') and bool(set(group['symbols']) & set(scope.get('symbols', []))))
        (selected if include else excluded).append(group)
    return {'captured_at': time.time(), 'basis': 'submission_watchlists', 'kind': kind, 'market': market,
            'selected_groups': selected,
            'excluded_groups': [{key: group[key] for key in ('id', 'name', 'market', 'symbol_count')} for group in excluded],
            'missing_groups': [ident for ident in wanted if ident not in {group['id'] for group in all_groups}] if kind == 'groups' else [],
            'empty_groups': [group['id'] for group in selected if not group['symbol_count']],
            'requested_symbols': copy.deepcopy(scope.get('symbols', []))}


def scope_summary(snapshot):
    if not snapshot:
        return None
    return {'kind': snapshot['kind'], 'basis': snapshot['basis'],
            'selected_groups': [group['name'] for group in snapshot['selected_groups']],
            'excluded_groups': [group['name'] for group in snapshot['excluded_groups']],
            'missing_groups': snapshot['missing_groups'], 'empty_groups': snapshot['empty_groups']}


def job_summary(job):
    value = {key: item for key, item in job.items() if key not in
             ('plan', 'execution_plan', 'scope_snapshot', 'results', 'targets', 'monitor_snapshot', 'failures')}
    plan = job.get('plan', {})
    value.update(plan_name=plan.get('name'), plan_version=plan.get('version'),
                 market=plan.get('scope', {}).get('market'), live=plan.get('live'),
                 condition_count=len(plan.get('rules', [])), failure_count=len(job.get('failures', [])))
    return value

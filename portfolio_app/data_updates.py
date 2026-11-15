"""Plan immutable daily requests from explicit instrument and calendar versions."""
from dataclasses import asdict

from .providers.base import ProviderBatch
from .snapshot_contracts import identity_hash
from .instrument_master import _date
from .update_jobs import run_update


def plan_daily_update(store, *, master, calendars, start, end, symbols, mode='incremental',
                      suspension_batches=None):
    _date(start)
    _date(end)
    if start > end:
        raise ValueError('更新起始日期晚于结束日期')
    symbols = sorted(set(symbols))
    if not symbols:
        raise ValueError('请选择明确的更新证券范围')
    by_symbol = {r.symbol: r for r in master.records.values()}
    if set(symbols) - set(by_symbol):
        raise ValueError('所选证券不在已登记主表，请先补齐主表')
    records = [by_symbol[symbol] for symbol in symbols]
    if any(r.asset_type != 'cn_stock' or r.provider != 'tushare' or r.provider_code != r.symbol for r in records):
        raise ValueError('当前下载链只支持已核对Tushare代码的A股')
    markets = sorted({r.market for r in records})
    sessions = {}
    for market in markets:
        calendar = calendars.get(market)
        if calendar is None or calendar.market != market:
            raise ValueError('缺少所选市场的明确交易日历')
        sessions[market] = set(calendar.sessions(start, end))
    fingerprints = {m: calendars[m].fingerprint for m in markets}
    master_id = identity_hash(master.to_dict())
    scope = identity_hash(dict(instruments=[asdict(r) for r in records], master=master_id,
                               calendars=fingerprints))
    parts = []
    for session in sorted(set().union(*sessions.values())):
        expected = sorted(r.symbol for r in records if session in sessions[r.market] and r.listed_on <= session
                          and (r.delisted_on is None or session < r.delisted_on))
        if not expected:
            continue
        suspended, evidence_id = [], None
        evidence = (suspension_batches or {}).get(session)
        if evidence is not None:
            if (evidence.metadata.get('session') != session
                    or evidence.metadata.get('status_coverage') != 'verified'):
                raise ValueError('停牌覆盖尚未核验，不能用于豁免缺失日线')
            suspended = sorted(set(evidence.metadata.get('suspended_symbols', ())) & set(expected))
            evidence_id = evidence.metadata.get('batch_id')
            if not evidence_id:
                raise ValueError('停牌证据缺少批次身份')
        parts.append(dict(session=session, expected_symbols=expected, suspended_symbols=suspended,
            suspension_batch=evidence_id, calendar_fingerprints=fingerprints,
            instrument_master_id=master_id))
    if not parts:
        return None
    return store.create(provider='tushare', dataset='a_daily_raw', scope_hash=scope,
        adapter_version='tushare-daily-1.0', mode=mode, shards=parts)


def run_tushare_update(store, job, provider, **options):
    request = store.request(job)
    if request['provider'] != 'tushare' or request['dataset'] != 'a_daily_raw':
        raise ValueError('任务类型与Tushare日线执行器不一致')
    def fetch(part):
        batch = provider.daily(part['session'], expected_symbols=part['expected_symbols'],
            suspended_symbols=part['suspended_symbols'], universe_scope='selection')
        metadata = {**batch.metadata, 'calendar_fingerprints': part['calendar_fingerprints'],
            'instrument_master_id': part['instrument_master_id'], 'suspension_batch': part['suspension_batch'],
            'research_ready': False, 'validation_scope': 'daily_rows_and_units_only'}
        return ProviderBatch(batch.frame, batch.raw, metadata, batch.completeness)
    return run_update(store, job, fetch, **options)

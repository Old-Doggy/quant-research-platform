import json
import pytest


def test_missing_token_and_provider_errors_have_safe_distinct_codes():
    from portfolio_app.providers.tushare import TushareProvider
    from portfolio_app.providers.base import ProviderError
    with pytest.raises(ProviderError) as missing:
        TushareProvider(token='').query('daily', {})
    assert missing.value.code == 'credentials_missing'
    for code, message, expected in [(40203, '权限不足 token=secret', 'permission_denied'),
                                     (40203, '每分钟最多访问50次 secret', 'rate_limited'),
                                     (40001, 'token无效 secret', 'credentials_invalid')]:
        provider = TushareProvider(token='secret', transport=lambda *a, **k: dict(code=code, msg=message))
        with pytest.raises(ProviderError) as failure:
            provider.query('daily', {})
        assert failure.value.code == expected
        assert 'secret' not in str(failure.value)
        assert 'secret' not in repr(provider)


def test_bad_shape_duplicate_fields_and_network_failures_are_not_empty_success():
    from portfolio_app.providers.tushare import TushareProvider
    from portfolio_app.providers.base import ProviderError
    for payload in [{'code': 0}, dict(code=0, data=dict(fields=['x', 'x'], items=[[1, 2]]))]:
        with pytest.raises(ProviderError, match='响应'):
            TushareProvider(token='secret', transport=lambda *a, **k: payload).query('daily', {})
    def offline(*a, **k):
        raise OSError('network URL contains secret')
    with pytest.raises(ProviderError) as failure:
        TushareProvider(token='secret', transport=offline).query('daily', {})
    assert failure.value.code == 'network_error'
    assert 'secret' not in str(failure.value)


def test_daily_cap_switches_to_security_shards_and_deduplicates_complete_day():
    from portfolio_app.providers.tushare import TushareProvider
    calls = []
    fields = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount']
    def transport(endpoint, params, **kwargs):
        calls.append((endpoint, params))
        codes = [params['ts_code']] if 'ts_code' in params else ['600000.SH', '000001.SZ']
        return dict(code=0, data=dict(fields=fields, items=[[code, '20250102', 10., 10., 10., 10., 1., 1.] for code in codes]))
    provider = TushareProvider(token='secret', transport=transport, row_limit=2, min_interval=0)
    result = provider.daily('2025-01-02', expected_symbols=['600000.SH', '000001.SZ'])
    assert len(result.frame) == 2
    assert result.frame.volume.tolist() == [100., 100.]
    assert result.completeness == 'complete'
    assert len(calls) == 3
    assert 'secret' not in json.dumps(result.metadata)


def test_missing_daily_rows_require_suspension_evidence_before_complete():
    from portfolio_app.providers.tushare import TushareProvider
    fields = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount']
    provider = TushareProvider(token='secret', min_interval=0, transport=lambda *a, **k: dict(code=0,
        data=dict(fields=fields, items=[['600000.SH', '20250102', 10., 10., 10., 10., 1., 1.]])))
    result = provider.daily('2025-01-02', expected_symbols=['600000.SH', '000001.SZ'])
    assert result.completeness == 'partial'
    assert result.metadata['missing_symbols'] == ['000001.SZ']
    assert provider.daily('2025-01-02', expected_symbols=['600000.SH', '000001.SZ'],
        suspended_symbols=['000001.SZ']).completeness == 'complete'


def test_master_fetches_live_delisted_and_suspended_statuses_and_parses_calendar():
    from portfolio_app.providers.tushare import TushareProvider
    calls = []
    def transport(endpoint, params, **kwargs):
        calls.append((endpoint, params))
        if endpoint == 'stock_basic':
            code = {'L': '600000.SH', 'D': '600001.SH', 'P': '600002.SH'}[params['list_status']]
            return dict(code=0, data=dict(fields=['ts_code','name','exchange','market','list_date','delist_date'],
                items=[[code, '示例', 'SSE', '主板', '19991110', '20200101' if params['list_status']=='D' else None]]))
        return dict(code=0, data=dict(fields=['exchange','cal_date','is_open'], items=[['SSE','20250101',0], ['SSE','20250102',1]]))
    provider = TushareProvider(token='secret', transport=transport, min_interval=0)
    batch = provider.instrument_master(observed_on='2025-01-02')
    assert batch.completeness == 'complete'
    assert set(batch.frame.symbol) == {'600000.SH', '600001.SH', '600002.SH'}
    assert batch.frame.loc[batch.frame.symbol.eq('600001.SH'), 'delisted_on'].iloc[0] == '2020-01-01'
    calendar = provider.calendar('SSE', '2025-01-01', '2025-01-02', generation=1)
    assert calendar.sessions('2025-01-01','2025-01-02') == ('2025-01-02',)
    assert set(p['list_status'] for e,p in calls if e=='stock_basic') == {'L','D','P'}


def test_selected_daily_universe_keeps_unfiltered_raw_and_detects_contradictory_suspension():
    from portfolio_app.providers.tushare import TushareProvider
    from portfolio_app.providers.base import ProviderError
    fields = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount']
    provider = TushareProvider(token='secret', min_interval=0, transport=lambda *a, **k: dict(code=0,
        data=dict(fields=fields, items=[[code, '20250102', 10., 10., 10., 10., 1., 1.]
                                     for code in ['600000.SH', '000001.SZ']])))
    batch = provider.daily('2025-01-02', expected_symbols=['600000.SH'])
    assert batch.frame.ts_code.tolist() == ['600000.SH']
    assert len(batch.raw) == 2
    with pytest.raises(ProviderError) as failure:
        provider.daily('2025-01-02', expected_symbols=['600000.SH'], universe_scope='master')
    assert failure.value.code == 'universe_mismatch'
    with pytest.raises(ProviderError) as failure:
        provider.daily('2025-01-02', expected_symbols=['600000.SH'], suspended_symbols=['600000.SH'])
    assert failure.value.code == 'status_conflict'


def test_master_handles_empty_optional_dates_and_shards_capped_status_by_exchange():
    from portfolio_app.providers.tushare import TushareProvider
    calls = []
    def transport(endpoint, params, **kwargs):
        calls.append(params)
        fields = ['ts_code','name','exchange','market','list_date','delist_date']
        if params['list_status'] != 'L':
            rows = []
        elif 'exchange' not in params:
            rows = [['600000.SH', '浦发', 'SSE', '主板', '19991110', ''],
                    ['000001.SZ', '平安', 'SZSE', '主板', '19910403', '']]
        else:
            rows = {'SSE': [['600000.SH', '浦发', 'SSE', '主板', '19991110', '']],
                    'SZSE': [['000001.SZ', '平安', 'SZSE', '主板', '19910403', '']], 'BSE': []}[params['exchange']]
        return dict(code=0, data=dict(fields=fields, items=rows))
    provider = TushareProvider(token='secret', transport=transport, min_interval=0, row_limit=2)
    batch = provider.instrument_master(observed_on='2025-01-02')
    assert len(batch.frame) == 2
    assert batch.frame.delisted_on.isna().all()
    assert {p['exchange'] for p in calls if 'exchange' in p} == {'SSE', 'SZSE', 'BSE'}


def test_provider_rejects_nonstring_field_names_without_leaking_internal_exception():
    from portfolio_app.providers.tushare import TushareProvider
    from portfolio_app.providers.base import ProviderError
    provider = TushareProvider(token='secret', transport=lambda *a, **k:
        dict(code=0, data=dict(fields=[['bad']], items=[])))
    with pytest.raises(ProviderError) as failure:
        provider.query('daily', {})
    assert failure.value.code == 'invalid_response'


def test_capabilities_do_not_imply_live_verification_and_probes_are_independent(monkeypatch):
    from portfolio_app.provider_registry import provider_capabilities, probe_tushare_permission
    from portfolio_app.providers.tushare import TushareProvider
    monkeypatch.delenv('TUSHARE_TOKEN', raising=False)
    assert all(row['access_status'] == 'credentials_missing' for row in provider_capabilities() if row['provider']=='tushare')
    monkeypatch.setenv('TUSHARE_TOKEN', 'secret')
    rows = provider_capabilities()
    assert all(row['access_status'] == 'not_probed' and not row['live_verified'] for row in rows if row['provider']=='tushare')
    def transport(endpoint, params, **kwargs):
        if endpoint == 'daily':
            return dict(code=40203, msg='权限不足 secret')
        return dict(code=0, data=dict(fields=['ts_code'], items=[['600000.SH']]))
    provider = TushareProvider(transport=transport, min_interval=0)
    assert probe_tushare_permission(provider, 'a_daily_raw')['status'] == 'permission_denied'
    assert probe_tushare_permission(provider, 'instrument_master')['status'] == 'available'


def test_security_shard_still_at_cap_and_wrong_date_never_become_complete():
    from portfolio_app.providers.tushare import TushareProvider
    from portfolio_app.providers.base import ProviderError
    fields = ['ts_code', 'trade_date']
    for rows, limit, expected in [([['600000.SH', '20250102']], 1, 'truncated_response'),
                                   ([['600000.SH', '20250103']], 6000, 'invalid_response')]:
        provider = TushareProvider(token='secret', min_interval=0, row_limit=limit,
            transport=lambda *a, **k: dict(code=0, data=dict(fields=fields, items=rows)))
        with pytest.raises(ProviderError) as failure:
            provider.daily('2025-01-02', expected_symbols=['600000.SH'])
        assert failure.value.code == expected

from datetime import date
import pandas as pd
import pytest


def test_free_refresh_retains_reference_batches_and_publishes_only_cross_checked_daily(tmp_path):
    from portfolio_app.daily_refresh import refresh_free_daily
    from portfolio_app.providers.base import ProviderBatch
    from portfolio_app.providers.baostock_reference import BaoStockReference
    from portfolio_app.providers.free_sdk import FreeDailyProvider
    from test_free_sdk_providers import sample
    def reference_transport(**params):
        if params['start']==params['end']=='2026-11-15':
            return pd.DataFrame(dict(code=['sh.600000'],code_name=['浦发银行'],ipoDate=['1999-11-10'],
                outDate=[''],type=['1'],status=['1']))
        return pd.DataFrame(dict(calendar_date=['2025-01-01','2025-01-02'],is_trading_day=['0','1']))
    reference=BaoStockReference(transport=reference_transport)
    providers={name:FreeDailyProvider(name,transport=lambda name=name,**k:sample(name)) for name in ['sina','baostock']}
    report=refresh_free_daily(tmp_path,symbols=['600000.SH'],start='2025-01-01',end='2025-01-02',
        observed_on='2026-11-15',reference=reference,providers=providers)
    assert report['status']=='published'
    assert report['snapshot']['research_capabilities']['corporate_action_backtest'] is False
    assert len(report['snapshot']['reference_batch_ids'])==2
    assert report['snapshot']['range']['start']=='2025-01-02'


def test_free_refresh_invalid_request_rejects_before_network(tmp_path):
    from portfolio_app.daily_refresh import refresh_free_daily
    with pytest.raises(ValueError):
        refresh_free_daily(tmp_path,symbols=['600000.SH'],start='2025-01-03',end='2025-01-01',observed_on='2026-11-15')
    with pytest.raises(ValueError):
        refresh_free_daily(tmp_path,symbols=['920599.BJ'],start='2025-01-01',end='2025-01-02',observed_on='2026-11-15')


def test_failed_provider_cannot_publish_success(tmp_path):
    from portfolio_app.daily_refresh import refresh_free_daily
    from portfolio_app.providers.baostock_reference import BaoStockReference
    from portfolio_app.providers.free_sdk import FreeDailyProvider
    from portfolio_app.snapshot_store import SnapshotStore
    from test_free_sdk_providers import sample
    def references(**params):
        if params['start']==params['end']=='2026-11-15':
            return pd.DataFrame(dict(code=['sh.600000'],code_name=['浦发银行'],ipoDate=['1999-11-10'],outDate=[''],type=['1'],status=['1']))
        return pd.DataFrame(dict(calendar_date=['2025-01-02'],is_trading_day=['1']))
    providers={name:FreeDailyProvider(name,transport=lambda name=name,**k:
        sample(name).iloc[:0] if name=='sina' else sample(name)) for name in ['sina','baostock']}
    result=refresh_free_daily(tmp_path,symbols=['600000.SH'],start='2025-01-02',end='2025-01-02',
        observed_on='2026-11-15',reference=BaoStockReference(transport=references),providers=providers)
    assert result['status']=='incomplete'
    assert SnapshotStore(tmp_path).current('free-a-daily') is None


def test_selected_security_queries_form_one_master_observation(tmp_path):
    from portfolio_app.daily_refresh import refresh_free_daily
    from portfolio_app.providers.baostock_reference import BaoStockReference
    from portfolio_app.providers.free_sdk import FreeDailyProvider
    from test_free_sdk_providers import sample
    def references(**params):
        if params['start']==params['end']=='2026-11-15':
            code=params['symbol'][:6]
            return pd.DataFrame(dict(code=['sh.'+code],code_name=['测试'+code],ipoDate=['1999-11-10'],
                outDate=[''],type=['1'],status=['1']))
        return pd.DataFrame(dict(calendar_date=['2025-01-02'],is_trading_day=['1']))
    def daily(name,**params):
        frame=sample(name)
        if name=='baostock':
            frame['code']='sh.'+params['symbol'][:6]
        return frame
    providers={name:FreeDailyProvider(name,transport=lambda name=name,**kw:daily(name,**kw))
        for name in ('sina','baostock')}
    result=refresh_free_daily(tmp_path,symbols=['600000.SH','688001.SH'],start='2025-01-02',end='2025-01-02',
        observed_on='2026-11-15',reference=BaoStockReference(transport=references),providers=providers)
    assert result['status']=='published'
    master=result['snapshot']['instrument_master']
    assert len(master['records'])==2
    assert all(not change['missing'] for change in master['changes'])
    assert len(result['snapshot']['reference_batch_ids'])==3

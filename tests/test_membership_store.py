import pytest
from portfolio_app.membership_store import MembershipStore
from portfolio_app.industry_query import industry_at


def master():
    from portfolio_app.instrument_master import InstrumentMaster
    m=InstrumentMaster()
    rows=[]
    for symbol,out in [('600000.SH',None),('600001.SH','2025-02-01')]:
        rows.append(dict(instrument_id='CN:SSE:'+symbol[:6],symbol=symbol,name='测试证券',market='SSE',asset_type='cn_stock',
            subtype='main_a',listed_on='2000-01-01',delisted_on=out,provider='test',provider_code=symbol))
    m.update(rows,observed_on='2026-11-15',source='synthetic-test',batch_id='synthetic-1')
    return m


def record(symbol='600000.SH',group='bank',start='2025-01-01',end=None,announcement='2024-12-20'):
    return dict(symbol=symbol,group=group,valid_from=start,valid_until=end,announced_on=announcement,evidence_ref='synthetic-notice-1')


def test_interval_inclusion_exclusion_and_delisted_master_are_time_correct(tmp_path):
    store=MembershipStore(tmp_path)
    identifier=store.save(dataset_id='test-index',classification_version='v1',source='synthetic-test',observed_on='2026-11-15',
        rows=[record(end='2025-02-01'),record('600001.SH')],coverage=dict(start='2025-01-01',end='2025-03-31',groups=['bank']),
        evidence_scope='verified_historical_intervals')
    opts=dict(group='bank',master=master())
    assert store.members(identifier,session='2025-01-31',**opts)['symbols']==['600000.SH','600001.SH']
    assert store.members(identifier,session='2025-02-01',**opts)['symbols']==[]
    with pytest.raises(ValueError,match='覆盖不足'):store.members(identifier,session='2024-12-31',**opts)


def test_current_or_monthly_observation_never_becomes_precise_daily_history(tmp_path):
    store=MembershipStore(tmp_path)
    identifier=store.save(dataset_id='test-index',classification_version='v1',source='synthetic-monthly',observed_on='2025-01-02',
        rows=[record(start='2025-01-02')],coverage=dict(start='2025-01-02',end='2025-01-02',groups=['bank']))
    assert store.members(identifier,group='bank',session='2025-01-02',master=master())['symbols']==['600000.SH']
    with pytest.raises(ValueError,match='覆盖不足'):store.members(identifier,group='bank',session='2025-01-03',master=master())


def test_industry_changes_use_valid_version_and_missing_is_explicit(tmp_path):
    store=MembershipStore(tmp_path)
    identifier=store.save(dataset_id='industry',classification_version='sw-2021',source='synthetic-test',observed_on='2026-11-15',
        rows=[record(end='2025-02-01'),record(group='insurance',start='2025-02-01',announcement='2025-01-20')],
        coverage=dict(start='2025-01-01',end='2025-03-31',groups=['bank','insurance']),evidence_scope='verified_historical_intervals')
    opts=dict(symbols=['600000.SH'],master=master())
    assert industry_at(store,identifier,session='2025-01-31',**opts)['assignments']=={'600000.SH':'bank'}
    assert industry_at(store,identifier,session='2025-02-03',**opts)['assignments']=={'600000.SH':'insurance'}
    result=industry_at(store,identifier,session='2025-02-03',symbols=['600001.SH'],master=master())
    assert result['status']=='partial' and result['missing_symbols']==['600001.SH']
    path=store.directory/(identifier+'.json');path.write_text('{}')
    with pytest.raises(ValueError,match='校验'):store.open(identifier)

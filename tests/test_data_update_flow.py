import pandas as pd
import pytest


def inputs():
    from portfolio_app.instrument_master import InstrumentMaster
    from portfolio_app.calendar_service import MarketCalendar
    from test_instrument_master import record
    master = InstrumentMaster()
    master.update([record(), record(instrument_id='CN:SSE:600001', symbol='600001.SH',
        provider_code='600001.SH', listed_on='2025-01-03')],
        observed_on='2025-01-06', source='synthetic', batch_id='truth')
    calendar = MarketCalendar('SSE','Asia/Shanghai','synthetic',1,
        (('2025-01-01', False),('2025-01-02', True),('2025-01-03', True),
         ('2025-01-04', False),('2025-01-05', False),('2025-01-06', True)))
    return master, calendar


def test_update_plan_uses_real_calendar_and_dated_listing_scope_and_is_immutable(tmp_path):
    from portfolio_app.data_updates import plan_daily_update, run_tushare_update
    from portfolio_app.providers.tushare import TushareProvider
    from portfolio_app.update_store import UpdateStore
    from test_instrument_master import record
    master, calendar = inputs()
    store = UpdateStore(tmp_path)
    job = plan_daily_update(store, master=master, calendars={'SSE':calendar},
        start='2025-01-01', end='2025-01-05', symbols=['600000.SH','600001.SH'])
    parts = store.shards(job)
    assert [p['payload']['session'] for p in parts] == ['2025-01-02','2025-01-03']
    assert parts[0]['payload']['expected_symbols'] == ['600000.SH']
    assert parts[1]['payload']['expected_symbols'] == ['600000.SH','600001.SH']
    master.update([record(name='新名')], observed_on='2025-01-07',source='synthetic',batch_id='new')
    assert store.shards(job) == parts
    calls = []
    def transport(endpoint, params, *, fields):
        calls.append(params)
        codes = ['600000.SH'] if params['trade_date']=='20250102' else ['600000.SH','600001.SH']
        rows = [[code,params['trade_date'],10.,11.,9.,10.,10.,1.,1.] for code in codes]
        return dict(code=0, data=dict(fields=fields.split(','),items=rows))
    provider = TushareProvider(token='test',transport=transport,min_interval=0)
    assert run_tushare_update(store,job,provider)['status']=='succeeded'
    assert run_tushare_update(store,job,provider)['status']=='succeeded'
    assert len(calls)==2
    artifact=store.read_artifact(store.shards(job)[0]['artifact_id'])
    assert artifact.frame.volume.iloc[0]==100
    assert artifact.metadata['calendar_fingerprints']=={'SSE':calendar.fingerprint}
    assert artifact.metadata['research_ready'] is False


def test_calendar_gap_missing_master_symbols_and_holiday_window_do_not_issue_downloads(tmp_path):
    from portfolio_app.data_updates import plan_daily_update
    from portfolio_app.update_store import UpdateStore
    master,calendar=inputs()
    store=UpdateStore(tmp_path)
    for options in [dict(start='2024-12-01',end='2025-01-02',symbols=['600000.SH']),
                    dict(start='2025-01-01',end='2025-01-02',symbols=['000001.SZ'])]:
        with pytest.raises(ValueError):
            plan_daily_update(store,master=master,calendars={'SSE':calendar},**options)
    assert plan_daily_update(store,master=master,calendars={'SSE':calendar},
        start='2025-01-04',end='2025-01-05',symbols=['600000.SH']) is None


def test_unverified_suspension_batch_cannot_exempt_missing_rows(tmp_path):
    from portfolio_app.data_updates import plan_daily_update
    from portfolio_app.providers.base import ProviderBatch
    from portfolio_app.update_store import UpdateStore
    master,calendar=inputs()
    evidence=ProviderBatch(pd.DataFrame(),pd.DataFrame(),dict(session='2025-01-02',
        status_coverage='unverified',suspended_symbols=['600000.SH'],batch_id='test'),'unverified')
    with pytest.raises(ValueError,match='停牌'):
        plan_daily_update(UpdateStore(tmp_path),master=master,calendars={'SSE':calendar},
            start='2025-01-02',end='2025-01-02',symbols=['600000.SH'],
            suspension_batches={'2025-01-02':evidence})


def test_calendar_batch_retains_raw_closed_days_and_is_persistable(tmp_path):
    from portfolio_app.providers.tushare import TushareProvider
    from portfolio_app.update_store import UpdateStore
    def transport(endpoint, params, *, fields):
        return dict(code=0,data=dict(fields=fields.split(','),items=[
            ['SSE','20250101',0,'20241231'],['SSE','20250102',1,'20241231']]))
    provider=TushareProvider(token='test',transport=transport,min_interval=0)
    batch=provider.calendar_batch('SSE','2025-01-01','2025-01-02',generation=1)
    store=UpdateStore(tmp_path)
    restored=store.read_artifact(store.save_artifact(batch))
    assert restored.raw.is_open.tolist()==[0,1]
    assert restored.metadata['calendar']['days']==[['2025-01-01',False],['2025-01-02',True]]

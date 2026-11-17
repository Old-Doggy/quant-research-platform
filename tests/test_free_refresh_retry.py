import pandas as pd
import pytest


def test_retry_reads_pinned_reference_and_only_fetches_failed_source(tmp_path):
    from portfolio_app.daily_refresh import refresh_free_daily
    from portfolio_app.free_refresh_plan import run_plan
    from portfolio_app.providers.baostock_reference import BaoStockReference
    from portfolio_app.providers.free_sdk import FreeDailyProvider
    from portfolio_app.snapshot_store import SnapshotStore
    from test_free_sdk_providers import sample
    def references(**params):
        if params['start']==params['end']=='2026-11-15':
            return pd.DataFrame(dict(code=['sh.600000'],code_name=['浦发银行'],ipoDate=['1999-11-10'],outDate=[''],type=['1'],status=['1']))
        return pd.DataFrame(dict(calendar_date=['2025-01-02'],is_trading_day=['1']))
    calls={'sina':0,'baostock':0}
    failed=True
    def transport(name,**kw):
        calls[name]+=1
        data=sample(name)
        return data.iloc[:0] if name=='sina' and failed else data
    providers={name:FreeDailyProvider(name,transport=lambda name=name,**kw:transport(name,**kw)) for name in calls}
    first=refresh_free_daily(tmp_path,symbols=['600000.SH'],start='2025-01-02',end='2025-01-02',
        observed_on='2026-11-15',reference=BaoStockReference(transport=references),providers=providers)
    assert first['status']=='incomplete'
    store=SnapshotStore(tmp_path)
    success=next(p for p in store.updates.shards(first['jobs'][0]['job_id']) if p['status']=='succeeded')['artifact_id']
    failed=False
    resumed=run_plan(tmp_path,first['plan_id'],retry=True,providers=providers)
    assert resumed['status']=='published'
    assert calls=={'baostock':1,'sina':2}
    assert success in resumed['snapshot']['batch_ids']
    assert len(store.updates.history(first['jobs'][1]['job_id']))==2
    again=run_plan(tmp_path,first['plan_id'],providers=providers)
    assert again['snapshot']['generation']==resumed['snapshot']['generation']
    assert calls=={'baostock':1,'sina':2}
    # Identical market bytes do not make revised reference contracts equivalent.
    import copy
    revised=copy.deepcopy(resumed['snapshot']['instrument_master'])
    revised['records'][0]['name']='旧版证券名称'
    revised['changes'][0]['observations'][0]['name']='旧版证券名称'
    from portfolio_app.instrument_master import InstrumentMaster
    from portfolio_app.calendar_service import MarketCalendar
    calendar_payload=resumed['snapshot']['calendars']['SSE'].copy()
    calendar_payload.pop('schema_version')
    calendar_payload['days']=tuple((d,o) for d,o in calendar_payload['days'])
    stale=store.publish_daily(dataset_id='free-a-daily',batch_ids=resumed['snapshot']['batch_ids'],
        comparison_ids=resumed['snapshot']['comparison_ids'],master=InstrumentMaster.from_dict(revised),
        calendars={'SSE':MarketCalendar(**calendar_payload)},start='2025-01-02',end='2025-01-02',
        symbols=['600000.SH'],reference_batch_ids=resumed['snapshot']['reference_batch_ids'])
    corrected=run_plan(tmp_path,first['plan_id'],providers=providers)
    assert corrected['snapshot']['generation']>stale['generation']
    assert corrected['snapshot']['instrument_master']==resumed['snapshot']['instrument_master']
    path=tmp_path/'refresh-plans'/(first['plan_id']+'.json')
    path.write_text(path.read_text(encoding='utf8').replace('2025-01-02','2025-01-03'),encoding='utf8')
    with pytest.raises(ValueError,match='校验'):
        run_plan(tmp_path,first['plan_id'],retry=True,providers=providers)

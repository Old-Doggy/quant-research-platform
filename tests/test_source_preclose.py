import numpy as np
import pandas as pd
import pytest


def test_tushare_previous_close_is_source_only_aligned_after_sorting():
    from portfolio_app.provider_normalize import normalize_daily
    raw = pd.DataFrame(dict(ts_code=['600000.SH']*3,trade_date=['20250106','20250102','20250103'],
        open=[10.]*3,high=[11.]*3,low=[9.]*3,close=[10.]*3,vol=[100.]*3,amount=[100.]*3,
        pre_close=[None,9.,9.5]))
    result = normalize_daily(raw,profile='tushare_a_daily',batch_id='source-previous-close')
    assert result.source_pre_close.tolist()[:2] == [9.,9.5]
    assert pd.isna(result.source_pre_close.iloc[-1])
    assert pd.isna(result.pre_close.iloc[-1])
    assert result.attrs['previous_close_policy'] == 'explicit_source_only.v1'
    assert raw.trade_date.tolist()[0] == '20250106'


@pytest.mark.parametrize('bad',[True,False,'wrong',np.inf,-1.,0.])
def test_invalid_source_previous_close_rejected_before_legacy_coercion(bad):
    from portfolio_app.provider_normalize import normalize_daily
    raw = pd.DataFrame(dict(ts_code=['600000.SH'],trade_date=['20250102'],open=[10.],high=[10.],
        low=[10.],close=[10.],vol=[100.],amount=[100.],pre_close=[bad]))
    with pytest.raises(ValueError,match='昨收'):
        normalize_daily(raw,profile='tushare_a_daily',batch_id='bad')


@pytest.mark.parametrize('provider',['sina','baostock'])
def test_free_source_previous_close_is_explicit_or_unknown(provider):
    from portfolio_app.providers.free_sdk import FreeDailyProvider
    from test_free_sdk_providers import sample
    raw = pd.concat([sample(provider),sample(provider,day='2025-01-06')],ignore_index=True)
    if provider == 'baostock':
        raw['preclose'] = [9.,None]
    batch = FreeDailyProvider(provider,transport=lambda **kw:raw).daily('600000.SH',sessions=['2025-01-02','2025-01-06'])
    assert pd.isna(batch.frame.pre_close.iloc[-1])
    if provider == 'baostock':
        assert batch.frame.source_pre_close.iloc[0] == 9.
    else:
        assert batch.frame.source_pre_close.isna().all()
    assert batch.raw.equals(raw)


def test_tencent_does_not_promote_previous_observation_to_source_quote():
    from portfolio_app.providers.tencent import TencentProvider
    from test_tencent_provider import response
    payload = response()
    payload['data']['sh600000']['day'].append(['2025-01-06','10','10','10','10','100',{},'1','10'])
    batch = TencentProvider(transport=lambda *a:payload,min_interval=0).daily('600000.SH',sessions=['2025-01-02','2025-01-06'])
    assert batch.frame.pre_close.isna().all()
    assert batch.frame.source_pre_close.isna().all()


def test_legacy_query_and_full_read_never_promote_inferred_previous_close(tmp_path):
    from test_snapshot_store import setup_store,publish
    from portfolio_app.providers.base import ProviderBatch
    from portfolio_app.market_query import query_daily
    store,updates,ids,master,calendar = setup_store(tmp_path)
    for explicit in (False,True):
        changed = []
        for artifact in ids:
            batch = updates.read_artifact(artifact)
            batch.frame['pre_close'] = 9.
            if explicit:
                batch.frame['source_pre_close'] = 8.
            changed.append(updates.save_artifact(ProviderBatch(batch.frame,batch.raw,batch.metadata,batch.completeness)))
        manifest = publish(store,changed,master,calendar)
        result = query_daily(store,manifest['snapshot_id'],symbols=['600000.SH'],start='2025-01-02',
            end='2025-01-02',columns=['close','pre_close'])
        assert result.columns.tolist() == ['close','pre_close']
        full = store.read_frame(manifest['snapshot_id'])
        for frame in (result,full):
            if explicit:
                assert frame.pre_close.iloc[0] == 8.
            else:
                assert frame.pre_close.isna().all()
            assert frame.attrs['previous_close_policy'] == 'explicit_source_only.v1'
        # Immutable source files and earlier inferred values remain untouched.
        assert updates.read_artifact(changed[0]).frame.pre_close.iloc[0] == 9.
        only = query_daily(store,manifest['snapshot_id'],symbols=['600000.SH'],start='2025-01-02',
            end='2025-01-02',columns=['pre_close'])
        assert len(only)==1 and only.columns.tolist()==['pre_close']
        with pytest.raises(ValueError,match='预算'):
            query_daily(store,manifest['snapshot_id'],symbols=['600000.SH'],start='2025-01-02',
                end='2025-01-02',columns=['pre_close'],max_bytes=1)


def test_canonical_reread_does_not_refill_explicitly_missing_source_previous_close():
    from portfolio_app.data import normalise_market_frame
    from portfolio_app.provider_normalize import normalize_daily
    raw = pd.DataFrame(dict(ts_code=['600000.SH']*2,trade_date=['20250102','20250106'],
        open=[10.]*2,high=[11.]*2,low=[9.]*2,close=[10.]*2,vol=[100.]*2,amount=[100.]*2))
    frame = normalize_daily(raw,profile='tushare_a_daily',batch_id='missing')
    assert normalise_market_frame(frame).pre_close.isna().all()

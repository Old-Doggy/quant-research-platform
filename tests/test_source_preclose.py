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

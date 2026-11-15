import pandas as pd
import pytest

from portfolio_app.providers.base import ProviderError


def sample(provider, *, day='2025-01-02'):
    data=dict(date=[day],open=[10.],high=[10.],low=[10.],close=[10.],volume=[10000.],amount=[100000.])
    if provider=='baostock':
        data.update(code=['sh.600000'],adjustflag=['3'],tradestatus=['1'])
    return pd.DataFrame(data)


@pytest.mark.parametrize('name',['sina','baostock'])
def test_sdk_units_keep_exact_shares_and_yuan_and_source_frame(name):
    from portfolio_app.providers.free_sdk import FreeDailyProvider
    original=sample(name)
    batch=FreeDailyProvider(name,transport=lambda **k:original).daily('600000.SH',sessions=['2025-01-02'])
    assert batch.frame.volume.iloc[0]==10000
    assert batch.frame.amount.iloc[0]==100000
    assert batch.raw.equals(original)
    assert batch.completeness=='complete'
    assert batch.metadata['automatic_fallback'] is False


def test_eastmoney_declares_lots_and_keeps_missing_days():
    from portfolio_app.providers.free_sdk import FreeDailyProvider
    original=pd.DataFrame({'日期':['2025-01-02'],'股票代码':['600000'],'开盘':[10.],
        '最高':[10.],'最低':[10.],'收盘':[10.],'成交量':[100.],'成交额':[100000.]})
    result=FreeDailyProvider('eastmoney',transport=lambda **k:original).daily('600000.SH',sessions=['2025-01-02','2025-01-03'])
    assert result.frame.volume.iloc[0]==10000
    assert result.completeness=='partial'
    assert result.metadata['missing_sessions']==['2025-01-03']


def test_baostock_refuses_adjusted_or_wrong_security_and_empty_returns_partial():
    from portfolio_app.providers.free_sdk import FreeDailyProvider
    for changes in [dict(adjustflag=['1']),dict(code=['sz.000001'])]:
        with pytest.raises(ProviderError):
            FreeDailyProvider('baostock',transport=lambda **k:sample('baostock').assign(**changes)).daily('600000.SH',sessions=['2025-01-02'])
    result=FreeDailyProvider('sina',transport=lambda **k:sample('sina').iloc[:0]).daily('600000.SH',sessions=['2025-01-02'])
    assert result.frame.empty and result.completeness=='partial'


def test_sdk_failures_and_duplicate_keys_never_become_empty_success():
    from portfolio_app.providers.free_sdk import FreeDailyProvider
    def offline(**kwargs):
        raise OSError('private URL')
    with pytest.raises(ProviderError) as failure:
        FreeDailyProvider('sina',transport=offline).daily('600000.SH',sessions=['2025-01-02'])
    assert failure.value.code=='network_error'
    assert 'private' not in str(failure.value)
    with pytest.raises(ProviderError):
        FreeDailyProvider('sina',transport=lambda **k:pd.concat([sample('sina')]*2)).daily('600000.SH',sessions=['2025-01-02'])

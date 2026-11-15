import pandas as pd
import pytest

from portfolio_app.providers.base import ProviderError


def response(symbol='sh600000', *, adjusted=False, volume='100', amount='10'):
    return dict(code=0,data={symbol:{'qfqday' if adjusted else 'day':[
        ['2025-01-02','10','10','10','10',volume,{},'1',amount,'0','0']]}})


def test_tencent_lots_and_star_shares_use_separate_explicit_profiles():
    from portfolio_app.providers.tencent import TencentProvider
    for symbol, upstream, vol in [('600000.SH','sh600000','100'), ('688001.SH','sh688001','10000')]:
        provider=TencentProvider(transport=lambda *a,**k: response(upstream,volume=vol),min_interval=0)
        result=provider.daily(symbol,sessions=['2025-01-02'])
        assert result.frame.volume.iloc[0]==10000
        assert result.frame.amount.iloc[0]==100000
        assert result.frame.attrs['research_dataset']['price_basis']=='raw'
        assert result.metadata['upstream']=='Tencent Finance'
        assert result.raw.source_vol.iloc[0]==vol
        assert result.completeness=='complete'


def test_tencent_rejects_adjusted_response_and_unit_mismatch():
    from portfolio_app.providers.tencent import TencentProvider
    for payload in [response(adjusted=True),response(volume='10000')]:
        provider=TencentProvider(transport=lambda *a,**k:payload,min_interval=0)
        with pytest.raises(ProviderError):
            provider.daily('600000.SH',sessions=['2025-01-02'])


def test_tencent_missing_sessions_and_long_history_chunks_are_explicit():
    from portfolio_app.providers.tencent import TencentProvider
    calls=[]
    def transport(symbol,start,end):
        calls.append((start,end))
        return response()
    provider=TencentProvider(transport=transport,min_interval=0)
    result=provider.daily('600000.SH',sessions=['2025-01-02','2027-01-04'])
    assert result.completeness=='partial'
    assert result.metadata['missing_sessions']==['2027-01-04']
    assert len(calls)==3


def test_tencent_network_and_empty_or_wrong_symbol_payload_are_not_success():
    from portfolio_app.providers.tencent import TencentProvider
    for payload in [dict(code=1),response(symbol='sz000001'),dict(code=0,data={'sh600000':{'day':[]}})]:
        provider=TencentProvider(transport=lambda *a,**k:payload,min_interval=0)
        with pytest.raises(ProviderError):
            provider.daily('600000.SH',sessions=['2025-01-02'])
    def offline(*a):
        raise OSError('private request')
    with pytest.raises(ProviderError) as failure:
        TencentProvider(transport=offline,min_interval=0).daily('600000.SH',sessions=['2025-01-02'])
    assert failure.value.code=='network_error'
    assert 'private' not in str(failure.value)

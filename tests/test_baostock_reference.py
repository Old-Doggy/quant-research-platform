import pandas as pd
import pytest


def test_baostock_selected_master_retains_delisted_identity():
    from portfolio_app.providers.baostock_reference import BaoStockReference
    raw=pd.DataFrame(dict(code=['sh.600000'],code_name=['浦发银行'],ipoDate=['1999-11-10'],
        outDate=['2025-01-06'],type=['1'],status=['0']))
    result=BaoStockReference(transport=lambda **k:raw).instrument('600000.SH',observed_on='2025-01-07')
    assert result.frame.delisted_on.iloc[0]=='2025-01-06'
    assert result.frame.instrument_id.iloc[0]=='CN:SSE:600000'
    assert result.raw.equals(raw)


def test_baostock_calendar_requires_every_calendar_date_and_states():
    from portfolio_app.providers.baostock_reference import BaoStockReference
    raw=pd.DataFrame(dict(calendar_date=['2025-01-01','2025-01-02'],is_trading_day=['0','1']))
    reference=BaoStockReference(transport=lambda **k:raw)
    result=reference.calendar('SSE','2025-01-01','2025-01-02',generation=1)
    assert result.metadata['calendar']['days']==[['2025-01-01',False],['2025-01-02',True]]
    with pytest.raises(ValueError):
        reference.calendar('BSE','2025-01-01','2025-01-02',generation=1)
    with pytest.raises(ValueError):
        reference.calendar('SSE','2025-01-01','2025-01-03',generation=1)

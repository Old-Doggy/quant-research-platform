import pandas as pd
import pytest


def bars():
    return pd.DataFrame(dict(ts_code=['600000.SH'], trade_date=['20250102'], open=[10.],
        high=[10.], low=[10.], close=[10.], vol=[100.], amount=[100.]))


def test_tushare_daily_converts_lots_and_thousand_yuan_once_retaining_raw_values():
    from portfolio_app.provider_normalize import normalize_daily
    raw = bars()
    frame = normalize_daily(raw, profile='tushare_a_daily', batch_id='test')
    assert frame.volume.iloc[0] == 10000
    assert frame.vol.iloc[0] == 10000
    assert frame.amount.iloc[0] == 100000
    assert frame.source_vol.iloc[0] == 100.
    assert frame.source_amount.iloc[0] == 100.
    assert frame.attrs['field_units']['volume'] == 'shares'
    assert raw.vol.iloc[0] == 100.
    with pytest.raises(ValueError, match='重复|归一'):
        normalize_daily(frame, profile='tushare_a_daily', batch_id='again')


def test_missing_activity_stays_missing_and_invalid_values_do_not_become_zero():
    from portfolio_app.provider_normalize import normalize_daily
    raw = bars()
    raw['vol'] = float('nan')
    assert pd.isna(normalize_daily(raw, profile='tushare_a_daily', batch_id='test').volume.iloc[0])
    raw['vol'] = -1.
    with pytest.raises(ValueError, match='成交量'):
        normalize_daily(raw, profile='tushare_a_daily', batch_id='bad')
    raw['vol'] = 'bad'
    with pytest.raises(ValueError, match='成交量'):
        normalize_daily(raw, profile='tushare_a_daily', batch_id='bad')


def test_field_profiles_do_not_guess_units_for_unknown_sources_or_assets():
    from portfolio_app.provider_normalize import normalize_daily
    with pytest.raises(ValueError, match='来源|profile'):
        normalize_daily(bars(), profile='unknown', batch_id='bad')
    with pytest.raises(ValueError, match='证券|股票'):
        normalize_daily(bars().assign(ts_code='113001.SH'), profile='tushare_a_daily', batch_id='cb')


def test_unit_alignment_consistency_of_turnover_and_price():
    from portfolio_app.provider_normalize import normalize_daily
    frame = normalize_daily(bars(), profile='tushare_a_daily', batch_id='test')
    assert frame.amount.iloc[0] / frame.volume.iloc[0] == frame.close.iloc[0]
    assert frame.attrs['research_dataset']['price_basis'] == 'raw'
    assert frame.attrs['normalization']['profile'] == 'tushare_a_daily'


def test_a_share_adapter_rejects_b_shares_and_fractional_share_volume():
    from portfolio_app.provider_normalize import normalize_daily
    with pytest.raises(ValueError, match='证券|股票'):
        normalize_daily(bars().assign(ts_code='900901.SH'), profile='tushare_a_daily', batch_id='bshare')
    with pytest.raises(ValueError, match='成交量|整数'):
        normalize_daily(bars().assign(vol=.005), profile='tushare_a_daily', batch_id='fraction')

import pandas as pd
import pytest

from portfolio_app.providers.tushare import TushareProvider
from portfolio_app.providers.base import ProviderError


def adapter(rows, fields, *, row_limit=6000):
    from portfolio_app.providers.tushare_reference import TushareReference
    calls = []
    def transport(endpoint, params, **kwargs):
        calls.append((endpoint, params))
        selected = [r for r in rows if 'ts_code' not in params or r[0] == params['ts_code']]
        return dict(code=0, data=dict(fields=fields, items=selected))
    return TushareReference(TushareProvider(token='test', transport=transport,
        min_interval=0, row_limit=row_limit)), calls


def test_daily_basic_units_missing_and_originals_are_separate():
    ref, _ = adapter([['600000.SH', '20250102', 10., 2., 3., 1.5, None, 8., .8, 2., 2.1, 1., 2., 100., 80., 70., 1000., 800.]],
        ['ts_code', 'trade_date', 'close', 'turnover_rate', 'turnover_rate_f', 'volume_ratio',
         'pe', 'pe_ttm', 'pb', 'ps', 'ps_ttm', 'dv_ratio', 'dv_ttm', 'total_share', 'float_share', 'free_share', 'total_mv', 'circ_mv'])
    result = ref.daily_basic('2025-01-02', expected_symbols=['600000.SH'])
    row = result.frame.iloc[0]
    assert row.turnover_rate == .02
    assert row.total_share == 1_000_000
    assert row.total_mv == 10_000_000
    assert row.dv_ttm == .02
    assert pd.isna(row.pe)
    assert row.pe_missing_reason == 'source_missing'
    assert row.source_turnover_rate == 2.
    assert result.raw.turnover_rate.iloc[0] == 2.
    assert result.metadata['pit_coverage'] == 'unverified'
    assert result.frame.attrs['field_units']['turnover_rate'] == 'fraction'
    assert result.completeness == 'complete'


def test_reference_caps_shard_and_missing_or_invalid_factor_is_not_complete():
    ref, calls = adapter([['600000.SH', '20250102', 2.], ['000001.SZ', '20250102', 3.]],
        ['ts_code', 'trade_date', 'adj_factor'], row_limit=2)
    result = ref.adjustment_factors('2025-01-02', expected_symbols=['600000.SH', '000001.SZ'])
    assert result.completeness == 'complete'
    assert len(calls) == 3
    partial = ref.adjustment_factors('2025-01-02', expected_symbols=['600000.SH', '300001.SZ'])
    assert partial.completeness == 'partial'
    assert partial.metadata['missing_symbols'] == ['300001.SZ']
    for value in [0., -1., float('nan'), float('inf'), 'bad']:
        bad, _ = adapter([['600000.SH', '20250102', value]], ['ts_code', 'trade_date', 'adj_factor'])
        with pytest.raises(ProviderError):
            bad.adjustment_factors('2025-01-02', expected_symbols=['600000.SH'])


def test_reference_wrong_date_duplicate_rows_and_missing_fields_fail():
    for rows, fields in [([['600000.SH', '20250103', 2.]], ['ts_code','trade_date','adj_factor']),
                         ([['600000.SH', '20250102', 2.]] * 2, ['ts_code','trade_date','adj_factor']),
                         ([['600000.SH', '20250102']], ['ts_code','trade_date'])]:
        ref, _ = adapter(rows, fields)
        with pytest.raises(ProviderError):
            ref.adjustment_factors('2025-01-02', expected_symbols=['600000.SH'])


def test_empty_reference_day_is_partial_and_original_input_is_not_modified():
    ref, _ = adapter([], ['ts_code', 'trade_date', 'adj_factor'])
    result = ref.adjustment_factors('2025-01-02', expected_symbols=['600000.SH'])
    assert result.frame.empty and result.completeness == 'partial'
    assert result.metadata['missing_symbols'] == ['600000.SH']
    ref, _ = adapter([['600000.SH', '20250102', 2.]], ['ts_code','trade_date','adj_factor'])
    result = ref.adjustment_factors('2025-01-02', expected_symbols=['600000.SH'])
    assert result.raw.trade_date.tolist() == ['20250102']
    assert result.frame.trade_date.tolist() == [pd.Timestamp('2025-01-02')]


def test_a_share_reference_does_not_guess_fund_or_bond_units():
    ref, _ = adapter([], ['ts_code', 'trade_date', 'adj_factor'])
    for code in ['510300.SH', '113001.SH', '900901.SH']:
        with pytest.raises(ValueError):
            ref.adjustment_factors('2025-01-02', expected_symbols=[code])


def test_limit_prices_filter_funds_and_keep_unknown_limits_explicit():
    ref, _ = adapter([['600000.SH', '20250102', 10., 11., 9.],
                      ['510300.SH', '20250102', 4., 4.4, 3.6],
                      ['000001.SZ', '20250102', 10., None, None]],
                     ['ts_code','trade_date','pre_close','up_limit','down_limit'])
    batch = ref.price_limits('2025-01-02', expected_symbols=['600000.SH','000001.SZ'])
    assert set(batch.frame.ts_code) == {'600000.SH','000001.SZ'}
    assert batch.completeness == 'partial'
    assert batch.metadata['unresolved_symbols'] == ['000001.SZ']
    assert len(batch.raw) == 3
    bad, _ = adapter([['600000.SH','20250102',10.,9.,11.]],
                     ['ts_code','trade_date','pre_close','up_limit','down_limit'])
    with pytest.raises(ProviderError):
        bad.price_limits('2025-01-02', expected_symbols=['600000.SH'])


def test_index_points_are_not_share_prices_and_missing_sessions_remain_missing():
    from portfolio_app.providers.tushare_reference import TushareReference
    calls = []
    def transport(endpoint, params, *, fields):
        calls.append(params)
        rows = [['000300.SH',params['trade_date'],100.,101.,99.,100.,100.,1.,10.]] if params['trade_date']=='20250102' else []
        return dict(code=0, data=dict(fields=fields.split(','), items=rows))
    ref = TushareReference(TushareProvider(token='test', transport=transport, min_interval=0))
    batch = ref.index_daily('000300.SH', sessions=['2025-01-02','2025-01-03'])
    assert len(batch.frame) == 1 and len(calls) == 2
    assert batch.completeness == 'partial'
    assert batch.metadata['missing_sessions'] == ['2025-01-03']
    assert batch.metadata['return_basis'] == 'unclassified_index'
    assert batch.frame.attrs['field_units']['close'] == 'index_points'
    assert batch.frame.amount.iloc[0] == 10000.
    assert 'volume' not in batch.frame


def test_index_missing_required_prices_does_not_fabricate_return_or_zero_volume():
    from portfolio_app.providers.tushare_reference import TushareReference
    def transport(endpoint, params, *, fields):
        row = ['000300.SH','20250102',100.,101.,99.,None,100.,None,10.]
        return dict(code=0, data=dict(fields=fields.split(','), items=[row]))
    ref = TushareReference(TushareProvider(token='test', transport=transport, min_interval=0))
    with pytest.raises(ProviderError):
        ref.index_daily('000300.SH', sessions=['2025-01-02'])

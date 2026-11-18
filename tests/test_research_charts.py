"""The shared interactive charts must preserve result semantics."""
import numpy as np
import pandas as pd
import pytest

from portfolio_app.research_charts import build_performance_chart, build_time_series_chart, build_coverage_chart


def test_ic_rolling_requires_full_window_and_preserves_original_gaps():
    from portfolio_app.research_charts import build_ic_chart
    frame = pd.DataFrame({'trade_date': pd.date_range('2025-01-01', periods=7),
                          'ic':[.1,.2,.3,np.nan,.5,.6,.7]})
    before = frame.copy(deep=True)
    fig = build_ic_chart(frame, window=3)
    pd.testing.assert_frame_equal(frame, before)
    assert pd.isna(fig.data[0].y[3])
    assert pd.isna(fig.data[1].y[1])
    assert fig.data[1].y[2] == pytest.approx(.2)
    assert pd.isna(fig.data[1].y[5])
    assert fig.data[1].y[6] == pytest.approx(.6)
    assert fig.data[0].connectgaps is False
    assert fig.layout.yaxis.rangemode == 'tozero'


def test_metric_bars_keep_order_signed_units_and_omit_unknown_values():
    from portfolio_app.research_charts import build_metric_bars
    frame = pd.DataFrame({'name':['baseline','cost','failed'], 'value':[.12,-.03,np.nan]})
    before = frame.copy(deep=True)
    fig = build_metric_bars(frame, category='name', value='value', title='场景收益', unit='percent')
    pd.testing.assert_frame_equal(frame, before)
    assert list(fig.data[0].y) == ['baseline','cost']
    assert list(fig.data[0].x) == [.12,-.03]
    assert '.2%' in fig.data[0].hovertemplate
    assert fig.layout.yaxis.autorange == 'reversed'
    amounts = build_metric_bars(frame, category='name', value='value', unit='number')
    assert ',.2f' in amounts.data[0].hovertemplate


def test_contribution_waterfall_keeps_signed_components_and_total():
    from portfolio_app.research_charts import build_contribution_waterfall
    frame = pd.DataFrame({'label': ['价格变化', '现金分红', '交易费用'],
                          'contribution': [.05, 0, -.012]})
    trace = build_contribution_waterfall(frame, revision='test').data[0]
    assert list(trace.x) == ['价格变化', '交易费用', '组合收益']
    assert list(trace.y) == [.05, -.012, 0]
    assert list(trace.measure) == ['relative', 'relative', 'total']
    assert trace.text[-1] == '+3.80%'


def test_performance_has_matched_time_axes_and_keeps_missing_values():
    frame = pd.DataFrame({'date': pd.date_range('2025-01-01', periods=4),
                          'nav': [1., 1.1, np.nan, 1.05],
                          'benchmark_nav': [1., 1.02, 1.03, 1.01],
                          'drawdown': [0., 0., np.nan, -.0454545]})
    before = frame.copy(deep=True)
    fig = build_performance_chart(frame, date='date', nav='nav', benchmark='benchmark_nav')
    pd.testing.assert_frame_equal(frame, before)
    assert list(fig.data[0].y[:2]) == [1., 1.1]
    assert pd.isna(fig.data[0].y[2])
    assert fig.data[0].connectgaps is False
    assert fig.layout.xaxis2.matches == 'x'
    assert all(trace.xaxis == 'x' for trace in fig.data)
    assert fig.layout.xaxis.anchor == 'y2'
    assert fig.layout.xaxis.showticklabels
    assert fig.layout.hovermode == 'x unified'
    assert fig.layout.font.size >= 14
    assert fig.layout.yaxis2.tickformat == '.1%'
    assert len(fig.data) == 3


def test_account_nav_has_no_invented_benchmark_or_return_recalculation():
    frame = pd.DataFrame({'trade_date': ['2025-01-01','2025-01-02'],
                          'unit_nav': [1., .98], 'drawdown': [0., -.02]})
    fig = build_performance_chart(frame, nav='unit_nav', label='账户净值')
    assert len(fig.data) == 2
    assert list(fig.data[0].y) == [1., .98]
    assert list(fig.data[-1].y) == [0., -.02]
    assert fig.data[0].name == '账户净值'


def test_missing_drawdown_is_not_silently_repaired():
    with pytest.raises(ValueError, match='drawdown'):
        build_performance_chart(pd.DataFrame({'trade_date':['2025-01-01'],'nav':[1.]}))


def test_turnover_displays_optional_daily_points_and_full_window_trend_without_filling_gaps():
    from portfolio_app.research_charts import build_turnover_chart
    frame = pd.DataFrame({'trade_date':pd.date_range('2025-01-01', periods=7),
                          'turnover':[None, 0., .5, 1., None, .5, 0.]})
    original = frame.copy(deep=True)
    fig = build_turnover_chart(frame, window=3)
    pd.testing.assert_frame_equal(frame, original)
    assert fig.data[0].type == 'scatter'
    assert fig.data[0].mode == 'markers'
    assert fig.data[0].visible == 'legendonly'
    assert list(fig.data[0].y[1:4]) == [0., .5, 1.]
    assert pd.isna(fig.data[0].y[4])
    assert fig.data[1].y[3] == .5
    assert pd.isna(fig.data[1].y[5])
    assert fig.data[1].connectgaps is False
    assert len(fig.data[0].x) == len(frame)
    assert fig.layout.yaxis.range == (0, 1.05)


def test_performance_uses_readable_terminal_axes_and_top_legend():
    frame = pd.DataFrame({'trade_date':pd.date_range('2025-01-01', periods=3),
                          'nav':[1., 1.02, 1.01], 'drawdown':[0., 0., -.0098]})
    fig = build_performance_chart(frame)
    assert fig.layout.legend.y > 1
    assert fig.layout.xaxis.tickformat == '%Y-%m'
    assert fig.layout.xaxis.hoverformat == '%Y-%m-%d'
    assert fig.layout.yaxis.side == 'right'


def test_allocation_includes_cash_and_uses_actual_market_values_without_normalizing():
    from portfolio_app.research_charts import build_allocation_chart
    frame = pd.DataFrame({'symbol':['AAA','BBB'], 'market_value':[60000., 30000.]})
    before = frame.copy(deep=True)
    fig = build_allocation_chart(frame, cash=10000., nav=100000.)
    pd.testing.assert_frame_equal(before, frame)
    assert list(fig.data[0].y) == ['AAA','BBB','现金']
    assert list(fig.data[0].x) == [.6,.3,.1]
    assert sum(fig.data[0].customdata) == 100000.
    assert list(build_allocation_chart(frame.iloc[:0], cash=100., nav=100.).data[0].x) == [1.]


def test_time_series_uses_units_and_never_fills_a_gap():
    frame = pd.DataFrame({'trade_date':['2025-01-01','2025-01-02','2025-01-03'],
                          'ic':[.2,np.nan,-.3]})
    fig = build_time_series_chart(frame, {'ic':'Rank IC'}, title='IC 稳定性', unit='number')
    assert fig.data[0].connectgaps is False
    assert pd.isna(fig.data[0].y[1])
    assert '.3f' in fig.data[0].hovertemplate
    assert fig.layout.xaxis.showspikes
    assert fig.layout.font.size >= 14


def test_allocation_includes_dividend_receivables_in_the_nav_denominator():
    from portfolio_app.research_charts import build_allocation_chart
    frame = pd.DataFrame({'symbol': ['AAA'], 'market_value': [950.]})
    fig = build_allocation_chart(frame, cash=100., nav=1100., receivables=50.)
    assert list(fig.data[0].y) == ['AAA', '现金', '应收股息']
    assert sum(fig.data[0].x) == pytest.approx(1.)
    assert sum(fig.data[0].customdata) == 1100.


def test_coverage_counts_unique_sessions_and_exposes_empty_months():
    frame = pd.DataFrame({'symbol':['A','A','A','B','B', 'B'],
        'trade_date':['2025-01-02','2025-01-02','2025-03-04','2025-01-03','2025-03-05',None]})
    before = frame.copy(deep=True)
    fig = build_coverage_chart(frame)
    pd.testing.assert_frame_equal(frame, before)
    assert list(fig.data[0].x) == ['2025-01','2025-02','2025-03']
    assert list(fig.data[0].y) == ['A','B']
    assert list(fig.data[0].z[0]) == [1,0,1]
    assert list(fig.data[0].z[1]) == [1,0,1]
    assert '日期数' in fig.data[0].hovertemplate


def test_coverage_limits_only_displayed_symbols_and_handles_invalid_dates():
    frame = pd.DataFrame({'symbol':['B','A','C'],
                          'trade_date':['2025-01-01','2025-01-02','2025-01-03']})
    assert list(build_coverage_chart(frame, max_symbols=2).data[0].y) == ['A','B']
    empty = pd.DataFrame({'symbol':['A'], 'trade_date':['bad']})
    assert len(build_coverage_chart(empty).data) == 0


def test_sparse_comparisons_retain_negative_values_and_skip_unknowns():
    from portfolio_app.research_charts import build_comparison_chart
    fig = build_comparison_chart(['2024','2025','2026'], [('年化收益',[.12,-.0641,None])])
    assert list(fig.data[0].y) == ['2024','2025']
    assert list(fig.data[0].x) == [.12,-.0641]
    assert list(fig.data[0].text) == ['12.00%','-6.41%']
    assert fig.layout.xaxis.rangemode == 'tozero'


def test_short_diagnostics_show_daily_points_when_rolling_window_is_unavailable():
    from portfolio_app.research_charts import build_ic_chart, build_turnover_chart
    frame = pd.DataFrame({'trade_date':pd.date_range('2025-01-01', periods=2),
                          'ic':[.2,-.1], 'turnover':[.5,1.]})
    for fig in [build_ic_chart(frame), build_turnover_chart(frame)]:
        assert fig.data[0].visible is True
        assert fig.data[0].mode == 'markers'
        assert all(pd.isna(y) for y in fig.data[1].y)

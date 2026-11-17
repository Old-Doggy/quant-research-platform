import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest


def performance():
    return dict(curve=[dict(date=d,daily_cost=c,daily_return=r,nav=n) for d,c,r,n in [
        ('2025-01-02',0.,0.,1.),('2025-01-03',.001,-.011,.989),
        ('2025-01-06',0.,-.02,.96922),('2025-01-07',.001,.009,.97794298)]],
        metrics=dict(total_cost=.002),cost_assumption=dict(transaction_cost=.001))


def test_cost_series_keeps_zero_days_and_cumulative_turnover_cost():
    from portfolio_app.strategy_cost_view import cost_series,cost_chart,cost_table
    data=cost_series(performance())
    assert data.daily_cost.tolist()==[0.,.001,0.,.001]
    assert data.cumulative_cost.tolist()==pytest.approx([0.,.001,.001,.002])
    fig=cost_chart(data,revision='same-run')
    assert list(fig.data[0].y)==data.daily_cost.tolist()
    assert list(fig.data[1].y)==data.cumulative_cost.tolist()
    assert fig.data[1].xaxis=='x'
    assert fig.layout.yaxis.tickformat=='.2%'
    assert fig.layout.yaxis2.tickformat=='.2%'
    assert cost_table(data)['日收益'].tolist()==[0.,-.011,-.02,.009]


@pytest.mark.parametrize('bad',[None,-.1,float('inf'),True])
def test_cost_chart_refuses_invalid_values_without_fake_zeros(bad):
    from portfolio_app.strategy_cost_view import cost_series
    result=performance();result['curve'][1]['daily_cost']=bad
    with pytest.raises(ValueError):cost_series(result)


def test_cost_series_rejects_duplicate_days_and_wrong_aggregate():
    from portfolio_app.strategy_cost_view import cost_series
    result=performance();result['metrics']['total_cost']=.003
    with pytest.raises(ValueError,match='合计'):cost_series(result)
    result=performance();result['curve'][1]['date']=result['curve'][0]['date']
    with pytest.raises(ValueError,match='日期'):cost_series(result)


def test_cost_view_switch_keeps_four_original_rows_and_negative_return():
    app=AppTest.from_string('''
from test_strategy_cost_view import performance
from portfolio_app.strategy_cost_view import render_strategy_costs
render_strategy_costs(performance(),revision='fixture')
''').run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    app.segmented_control(key='strategy_cost_display').set_value('表格').run()
    assert not app.exception and len(app.get('plotly_chart'))==0
    table=app.dataframe[0].value
    assert len(table)==4 and table['日收益'].iloc[2]==-.02


def test_no_cost_and_empty_curve_are_distinct():
    from portfolio_app.strategy_cost_view import cost_series,cost_chart
    result=performance()
    for row in result['curve']:row['daily_cost']=0.
    result['metrics']['total_cost']=0.
    assert cost_series(result).cumulative_cost.eq(0).all()
    assert len(cost_chart(cost_series(result),revision='zero').data)==2
    assert cost_series({'curve':[]}).empty


def test_long_cost_chart_aggregates_all_days_without_dropping_cost():
    from portfolio_app.strategy_cost_view import cost_series,cost_chart
    dates=pd.bdate_range('2020-01-01',periods=1000)
    result=dict(curve=[dict(date=d,daily_cost=.001,daily_return=0.,nav=1.) for d in dates],
        metrics=dict(total_cost=1.))
    fig=cost_chart(cost_series(result),revision='long')
    assert fig.data[0].name=='月度换手成本'
    assert sum(fig.data[0].y)==pytest.approx(1.)
    assert len(fig.data[1].x)<=600
    assert fig.data[1].y[-1]==pytest.approx(1.)

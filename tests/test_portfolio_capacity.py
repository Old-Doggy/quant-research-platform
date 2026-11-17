import pandas as pd
import pytest


def inputs():
    sessions=pd.bdate_range('2025-01-01',periods=24).strftime('%Y-%m-%d').tolist()
    frame=pd.DataFrame({'trade_date':sessions,'amount':[100000.]*24})
    frame.attrs['field_units']={'price':'CNY_per_share','amount':'CNY'}
    positions=pd.DataFrame({'symbol':['AAA'],'market_value':[25000.]})
    return sessions,{'AAA':frame},positions


def test_capacity_uses_twenty_prior_sessions_and_independent_arithmetic():
    from portfolio_app.portfolio_capacity import capacity_report
    sessions,frames,positions=inputs()
    frames['AAA'].loc[20:,'amount']=1e12
    row=capacity_report(positions,frames,sessions=sessions,date=sessions[20]).iloc[0]
    assert row.status=='available' and row.observed_sessions==20
    assert row.average_amount==100000.
    assert row.daily_budget==5000.
    assert row.estimated_sessions==5.
    assert row.holding_to_daily_amount==.25
    assert row.window_end==sessions[19]


@pytest.mark.parametrize('case,status',[('units','unknown_units'),('missing','incomplete_window'),
    ('short','short_window'),('zero','zero_liquidity'),('absent','missing_amount')])
def test_capacity_unknowns_are_not_zero_or_estimated_from_price_times_volume(case,status):
    from portfolio_app.portfolio_capacity import capacity_report
    sessions,frames,positions=inputs();date=sessions[20]
    if case=='units':frames['AAA'].attrs={}
    if case=='missing':frames['AAA'].loc[4,'amount']=float('nan')
    if case=='short':date=sessions[5]
    if case=='zero':frames['AAA']['amount']=0.
    if case=='absent':frames['AAA']=frames['AAA'].drop(columns='amount')
    row=capacity_report(positions,frames,sessions=sessions,date=date).iloc[0]
    assert row.status==status and pd.isna(row.estimated_sessions)


def test_capacity_future_changes_do_not_change_selected_date_and_input_not_mutated():
    from portfolio_app.portfolio_capacity import capacity_report
    sessions,frames,positions=inputs();before=frames['AAA'].copy(deep=True)
    first=capacity_report(positions,frames,sessions=sessions,date=sessions[20])
    pd.testing.assert_frame_equal(frames['AAA'],before)
    frames['AAA'].loc[21:,'amount']=1e30
    pd.testing.assert_frame_equal(first,capacity_report(positions,frames,sessions=sessions,date=sessions[20]))


def test_capacity_rejects_invalid_amounts_or_participation_and_preserves_all_holdings():
    from portfolio_app.portfolio_capacity import capacity_report
    sessions,frames,positions=inputs()
    with pytest.raises(ValueError):capacity_report(positions,frames,sessions=sessions,date=sessions[20],participation_rate=0)
    frames['AAA'].loc[3,'amount']=-1
    with pytest.raises(ValueError):capacity_report(positions,frames,sessions=sessions,date=sessions[20])
    frames['AAA'].loc[3,'amount']=100000.
    positions.loc[1]=['BBB',5000.]
    result=capacity_report(positions,frames,sessions=sessions,date=sessions[20])
    assert result.symbol.tolist()==['AAA','BBB']
    assert result.iloc[1].status=='missing_input'


def test_capacity_view_arrays_table_and_rate_change_share_source():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string('''
from types import SimpleNamespace
from test_portfolio_capacity import inputs
from portfolio_app.portfolio_capacity_view import render_capacity
sessions,frames,positions=inputs()
positions['trade_date']=sessions[20]
result=SimpleNamespace(positions=positions,inputs={'sessions':sessions})
render_capacity(result,frames,date=sessions[20],revision='fixture')
''').run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    app.selectbox(key='portfolio_capacity_rate').set_value(.1).run()
    app.segmented_control(key='portfolio_capacity_display').set_value('表格').run()
    assert not app.exception
    assert app.dataframe[0].value['参考消化天数'].tolist()==[2.5]
    assert app.dataframe[0].value['每日参考额度（元）'].tolist()==[10000.]


def test_capacity_inputs_snapshot_preserves_units_and_does_not_follow_current_input():
    from portfolio_app.portfolio_capacity import capacity_inputs
    _,frames,_=inputs();saved=capacity_inputs(frames)
    frames['AAA'].loc[0,'amount']=999.
    assert saved['AAA'].amount.iloc[0]==100000.
    assert saved['AAA'].attrs['field_units']['amount']=='CNY'


def test_capacity_chart_keeps_only_computable_rows_and_actual_numbers():
    from portfolio_app.portfolio_capacity import capacity_report
    from portfolio_app.portfolio_capacity_view import capacity_chart
    sessions,frames,positions=inputs();positions.loc[1]=['BBB',5000.]
    report=capacity_report(positions,frames,sessions=sessions,date=sessions[20])
    fig=capacity_chart(report,revision='fixture')
    assert list(fig.data[0].x)==[5.]
    assert list(fig.data[0].y)==['AAA']
    assert fig.layout.xaxis.range[1]>5.
    assert list(fig.data[0].customdata[0])==[25000.,100000.,5000.,sessions[0],sessions[19]]


def test_capacity_snapshot_survives_result_store_and_original_source_changes(tmp_path):
    from portfolio_app.portfolio_capacity import capacity_inputs,capacity_report
    from portfolio_app.result_store import ResultStore
    from test_result_store import key
    sessions,frames,positions=inputs()
    store=ResultStore(tmp_path)
    store.save('capacity',key(),{'capacity_inputs':capacity_inputs(frames)})
    frames['AAA']['amount']=1.
    saved=ResultStore(tmp_path).load('capacity')['capacity_inputs']
    assert saved['AAA'].attrs['field_units']=={'price':'CNY_per_share','amount':'CNY'}
    assert capacity_report(positions,saved,sessions=sessions,date=sessions[20]).iloc[0].estimated_sessions==5.


def test_tiny_capacity_is_visible_without_false_zero_label():
    from portfolio_app.portfolio_capacity import capacity_report
    from portfolio_app.portfolio_capacity_view import capacity_chart
    sessions,frames,positions=inputs()
    frames['AAA']['amount']=1e12
    fig=capacity_chart(capacity_report(positions,frames,sessions=sessions,date=sessions[20]),revision='tiny')
    assert fig.data[0].text[0]=='<0.01'
    assert fig.layout.xaxis.range[1]<.001

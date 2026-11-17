import numpy as np
import pandas as pd
import pytest


def bars():
    dates=pd.bdate_range('2024-01-02',periods=180)
    price=10+np.arange(180)*.02+np.sin(np.arange(180)/5)
    return pd.DataFrame(dict(trade_date=dates,open=price,high=price,low=price,close=price,
        volume=100000,symbol='SYNTH',return_=0.)).rename(columns={'return_':'return'})


def report():
    from portfolio_app.validation import locked_validation_report
    return locked_validation_report(bars(),'trend',params={'fast_window':5,'slow_window':30})


def test_validation_timeline_uses_each_actual_session_once_and_keeps_gap_types():
    from portfolio_app.validation_view import validation_segments,timeline_chart
    from portfolio_app.research_integrity import temporal_split
    sessions=pd.bdate_range('2024-01-02',periods=100).strftime('%Y-%m-%d').tolist()
    split=temporal_split(sessions,horizon=5)
    segments=validation_segments(sessions,split)
    assert segments['kind'].tolist()==['train','purge','embargo','validation','purge','embargo','test','tail']
    assert segments.sessions.sum()==100
    assert segments.sessions.tolist()==[55,5,5,10,5,5,10,5]
    assert segments.iloc[3].start==sessions[65]
    figure=timeline_chart(segments)
    assert sum(sum(t.x) for t in figure.data)==100
    bad={**split,'test':[66]}
    with pytest.raises(ValueError): validation_segments(sessions,bad)


def test_validation_report_retains_dates_and_test_changes_do_not_tune_validation():
    from portfolio_app.validation import locked_validation_report
    before=report()
    assert before['sessions']==bars().trade_date.dt.strftime('%Y-%m-%d').tolist()
    changed=bars();test=before['split']['test']
    changed.loc[test,['open','high','low','close']]*=1.4
    after=locked_validation_report(changed,'trend',params={'fast_window':5,'slow_window':30})
    pd.testing.assert_frame_equal(before['validation_sensitivity'],after['validation_sensitivity'])
    assert before['selected_parameters'] is None and after['test_used_for_selection'] is False


def test_validation_page_only_draws_active_results_and_selection_reads_real_row(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import portfolio_app.result_presentations as presentations
    value=report();calls=[];original=presentations.build_validation_chart
    def draw(frame,kind):
        calls.append(kind);return original(frame,kind)
    monkeypatch.setattr(presentations,'build_validation_chart',draw)
    view=AppTest.from_string('''
from test_validation_view_v2 import report
from portfolio_app.result_presentations import render_validation_results
render_validation_results(report())
''').run()
    assert not view.exception and calls==['oos']
    assert len(view.get('plotly_chart'))==2
    view.session_state['locked_validation_tab']='参数与成本'
    view.run()
    assert not view.exception and calls==['oos','sensitivity']
    view.selectbox(key='validation_parameter').set_value(value['validation_sensitivity']['参数'].iloc[-1]).run()
    chosen=value['validation_sensitivity'].iloc[-1]
    view.selectbox(key='validation_extra_bps').set_value(int(chosen['额外滑点bp'])).run()
    assert not view.exception
    assert any(m.value==f"{chosen['区间收益']:.2%}" for m in view.metric)


def test_validation_saved_report_replays_split_parameters_and_each_result(tmp_path):
    import copy
    from portfolio_app.result_replay import validation_replay_inputs,replay_saved
    from portfolio_app.result_store import ResultStore
    from portfolio_app.research_result_cache import build_research_cache_key
    from portfolio_app.result_archive_v2 import export_result,import_result
    from portfolio_app.result_history import result_projection
    value=report()
    value['replay']=validation_replay_inputs(bars(),strategy_key='trend',params={'fast_window':5,'slow_window':30},transaction_cost=.001)
    assert 'return' in value['replay']['frame']
    store=ResultStore(tmp_path/'original')
    key=build_research_cache_key(dataset_id='strategy-validation',data_version='fixture',processing={},engine_id='test')
    store.save('validation',key,value)
    restored=ResultStore(tmp_path/'restored')
    import_result(restored,export_result(store,'validation'))
    checked=replay_saved(restored,'validation')
    assert checked['kind']=='validation' and checked['sessions']==180
    assert len(result_projection(value)['tables']['验证区间'])==8
    for field in ('rolling_oos','validation_sensitivity','split'):
        changed=copy.deepcopy(value)
        if field=='split': changed[field]['test'][0]+=1
        else: changed[field].iloc[0,changed[field].columns.get_loc('total_return' if field=='rolling_oos' else '区间收益')]+=.01
        store.save('wrong-'+field,key,changed)
        with pytest.raises(ValueError,match='不一致'): replay_saved(store,'wrong-'+field)


def test_history_can_reopen_validation_as_charts_and_replay(monkeypatch,tmp_path):
    from streamlit.testing.v1 import AppTest
    from portfolio_app.result_store import ResultStore
    from portfolio_app.research_result_cache import build_research_cache_key
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    store=ResultStore(tmp_path/'research_results')
    key=build_research_cache_key(dataset_id='strategy-validation',data_version='fixture',processing={},engine_id='test')
    store.save('saved-validation',key,report())
    app=AppTest.from_string('from portfolio_app.result_history_view import render_result_history\nrender_result_history(public_mode=False)').run()
    assert not app.exception and len(app.get('plotly_chart'))==2

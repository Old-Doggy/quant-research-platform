import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest


def fixture():
    curve=[dict(date=d,nav=v) for d,v in [('2025-01-02',1.),('2025-01-03',1.1),('2025-01-06',.99)]]
    trades=pd.DataFrame([
        {'信号日期':'2025-01-02','执行日期':'2025-01-03','标的':'DEMO','方向':'买入','状态':'已成交','原因':'突破','数量':1,'价格':11.,'订单ID':'a'},
        {'信号日期':'2025-01-03','执行日期':'2025-01-06','标的':'DEMO','方向':'卖出','状态':'已成交','原因':'离场','数量':1,'价格':9.9,'订单ID':'b'},
        {'信号日期':'2025-01-02','执行日期':'2025-01-03','标的':'DEMO','方向':'买入','状态':'已拒单','原因':'停牌','数量':1,'价格':None,'订单ID':'c'},
        {'信号日期':'2025-01-06','执行日期':'2025-01-07','标的':'DEMO','方向':'买入','状态':'已成交','原因':'开仓','数量':1,'价格':10.,'订单ID':'d'},
    ])
    return dict(curve=curve),trades


def test_event_markers_use_exact_nav_dates_and_keep_unplottable_rows():
    from portfolio_app.strategy_event_view import event_chart
    performance,trades=fixture()
    fig=event_chart(performance,trades,revision='test')
    assert list(fig.data[0].y)==[1.,1.1,.99]
    by_name={t.name:t for t in fig.data}
    assert list(by_name['买入成交'].y)==[1.1]
    assert list(by_name['卖出成交'].y)==[.99]
    assert list(by_name['未成交'].y)==[1.1]
    assert by_name['未成交'].customdata[0][3]=='—'
    assert by_name['卖出成交'].customdata[0][0]==1
    assert by_name['卖出成交'].customdata[0][4]=='离场'
    assert len(trades)==4
    assert '股' not in ''.join(t.hovertemplate or '' for t in fig.data)


def test_event_chart_preserves_gaps_and_rejects_duplicate_curve_dates():
    from portfolio_app.strategy_event_view import event_chart
    performance,trades=fixture();performance['curve'][1]['nav']=None
    fig=event_chart(performance,trades,revision='test')
    assert pd.isna(fig.data[0].y[1])
    assert len(fig.data)==2 and list(fig.data[1].y)==[.99]
    assert not fig.data[0].connectgaps
    performance['curve'].append(performance['curve'][0])
    with pytest.raises(ValueError,match='日期'):
        event_chart(performance,trades,revision='test')


def test_event_view_table_switch_and_detail_selection_keep_same_rows():
    view=AppTest.from_string('''
from test_strategy_event_view import fixture
from portfolio_app.strategy_event_view import render_strategy_events
performance,trades=fixture()
render_strategy_events(performance,trades,revision='run1')
''').run()
    assert not view.exception and len(view.get('plotly_chart'))==1
    view.selectbox(key='strategy_event_pick').set_value(2).run()
    assert not view.exception
    details = next(block.value for block in view.get('html') if '事件详情' in block.value)
    assert '已拒单' in details and '<dt>价格</dt><dd>—</dd>' in details
    view.segmented_control(key='strategy_event_display').set_value('表格').run()
    assert not view.exception and len(view.get('plotly_chart'))==0
    assert len(view.dataframe[0].value)==4
    assert view.selectbox(key='strategy_event_pick').value==2


def test_all_single_templates_lazy_views_keep_saved_run(monkeypatch,tmp_path):
    import time
    from portfolio_app.strategies import STRATEGIES
    monkeypatch.setenv('PORTFOLIO_MODE','local')
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    from pathlib import Path
    view=AppTest.from_file(str(Path('streamlit_app.py').resolve()),default_timeout=60).run()
    view.radio(key='workspace_route_selector').set_value('strategy').run()
    for strategy in STRATEGIES:
        view.selectbox(key='explicit_strategy_strategy').set_value(strategy.key).run()
        if strategy.key=='quality_momentum':
            assert view.button(key='run_explicit_strategy').disabled
            assert any('时点' in item.value for item in view.caption)
            continue
        view.button(key='run_explicit_strategy').click().run()
        deadline=time.monotonic()+10
        while view.session_state['research_run_state_strategy'].status.value!='result' and time.monotonic()<deadline:
            time.sleep(.05);view.run()
        assert not view.exception and not view.error
        state=view.session_state['research_run_state_strategy']
        assert state.status.value=='result'
        count=state.run_count
        assert len(view.get('plotly_chart'))==1
        view.segmented_control(key='strategy_nav_display').set_value('表格').run()
        assert not view.exception and len(view.get('plotly_chart'))==0
        view.segmented_control(key='strategy_nav_display').set_value('图表').run()
        view.session_state['strategy_main_view']='买卖事件';view.run()
        assert not view.exception and not view.error
        if state.result['result_payload']['details']['trades']:
            assert view.selectbox(key='strategy_event_pick').value==0
            view.segmented_control(key='strategy_event_display').set_value('表格').run()
            assert len(view.get('plotly_chart'))==0
        view.session_state['strategy_main_view']='成本与参数';view.run()
        assert not view.exception
        view.segmented_control(key='strategy_analysis_detail').set_value('参数敏感性').run()
        assert not view.exception and len(view.get('plotly_chart'))==1
        view.session_state['strategy_main_view']='研究记录';view.run()
        assert not view.exception and len(view.get('plotly_chart'))==0
        view.session_state['strategy_main_view']='净值表现';view.run()
        assert view.session_state['research_run_state_strategy'].run_count==count

import pandas as pd
from streamlit.testing.v1 import AppTest

from portfolio_app.result_presentations import build_quote_chart, build_validation_chart, validation_table


def test_quote_chart_retains_prices_in_hover_and_source_activity():
    frame=pd.DataFrame({'trade_date':pd.date_range('2024-01-01',periods=3),
        'open':[10,11,10],'high':[12,12,12],'low':[9,9,9],
        'close':[10,11,10],'pre_close':[10,10,11],'vol':[100,200,300]})
    fig=build_quote_chart(frame)
    assert abs(fig.data[0].y[1]-.1)<1e-12
    assert fig.data[0].y[2] == 10/11-1
    assert list(fig.data[1].y)==[100,200,300]
    assert list(fig.data[0].customdata[1])==[11,12,9,11]
    assert fig.layout.yaxis.tickformat=='+.1%'


def test_validation_heatmap_and_chinese_table_preserve_negative_results():
    frame=pd.DataFrame({'参数':['fast=10,slow=30']*2,'额外滑点bp':[0,10],
        '区间收益':[-.05,-.06],'最大回撤':[-.1,-.11],'scope':['validation_only']*2})
    fig=build_validation_chart(frame,'sensitivity')
    assert list(fig.data[0].z[0])==[-.05,-.06]
    assert list(fig.data[0].text[0])==['-5.00%','-6.00%']
    assert fig.data[1].hoverinfo!='skip'
    assert list(fig.data[1].customdata[1][:2])==['fast=10,slow=30',10]
    table=validation_table(frame)
    assert table['评分区间'].tolist()==['验证段']*2
    assert table['参数'].iloc[0]=='快线 10 / 慢线 30'


def test_recent_quotes_keep_missing_returns_and_do_not_invent_activity():
    frame=pd.DataFrame({'trade_date':pd.date_range('2024-01-01',periods=3),
        'open':[10,11,10],'high':[12,12,12],'low':[9,9,9],'close':[10,11,10]})
    fig=build_quote_chart(frame)
    assert pd.isna(fig.data[0].y[0])
    assert len(fig.data)==1
    assert fig.layout.yaxis.range[0] == -fig.layout.yaxis.range[1]
    assert len(fig.layout.shapes)==2


def test_chart_table_switch_keeps_raw_quote_records():
    view=AppTest.from_string('''
import pandas as pd
from portfolio_app.result_presentations import render_recent_quotes
frame=pd.DataFrame({'trade_date':pd.date_range('2024-01-01',periods=3),
 'open':[10,11,10],'high':[12,12,12],'low':[9,9,9],'close':[10,11,10],'vol':[100,200,300]})
render_recent_quotes(frame,key='quotes')
''').run()
    assert not view.exception and len(view.get('plotly_chart'))==1 and not view.dataframe
    view.segmented_control(key='quotes').set_value('table').run()
    assert not view.exception and not view.get('plotly_chart')
    assert len(view.dataframe[0].value)==3 and '最高' in view.dataframe[0].value


def test_local_showcase_displays_selected_real_curve_and_changes_cost():
    view=AppTest.from_string('''
from portfolio_app.showcase_workspace import render_showcase_workspace
render_showcase_workspace('.',mode='local')
''',default_timeout=30).run()
    view.selectbox(key='dossier_project_zh').set_value('model6').run()
    assert not view.exception and len(view.get('plotly_chart'))==1
    assert view.segmented_control(key='evidence_page_model6_zh').value=='curve'
    base=view.metric[0].value
    view.selectbox(key='evidence_layer_model6_zh').set_value('cost_x2').run()
    assert not view.exception and view.metric[0].value!=base
    view.segmented_control(key='project_curve_display_model6_zh').set_value('table').run()
    assert not view.exception and len(view.dataframe[0].value)==557
    assert not view.get('plotly_chart')
    view.selectbox(key='dossier_project_zh').set_value('model2').run()
    assert view.selectbox(key='evidence_layer_model2_zh').value=='local_native_wfo'
    assert len(view.get('plotly_chart'))==1

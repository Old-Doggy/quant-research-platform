import pandas as pd
import pytest


def orders():
    return [dict(symbol='AAA',side='BUY',effective_date='2025-01-03',requested_quantity=200,filled_quantity=100,
        remaining_quantity=100,status='PARTIAL',reason='现金限制导致部分成交',reason_code='partial_cash',
        price=10.,cash_before=1000.,cash_after=0.),
        dict(symbol='BBB',side='SELL',effective_date='2025-01-03',requested_quantity=100,filled_quantity=0,
        remaining_quantity=100,status='REJECTED',reason='标的处于停牌状态',reason_code='suspended',
        price=None,cash_before=0.,cash_after=0.)]


def test_order_chart_keeps_each_actual_order_and_rejected_zero_fill():
    from portfolio_app.portfolio_order_view import order_chart,order_table
    frame=pd.DataFrame(orders())
    fig=order_chart(frame)
    assert list(fig.data[0].x)==[200,100]
    assert list(fig.data[1].x)==[100,0]
    assert list(fig.data[1].customdata[1])==[1,'BBB','SELL','REJECTED','标的处于停牌状态']
    table=order_table(frame)
    assert table['方向'].tolist()==['买入','卖出']
    assert table['执行参考价'].iloc[0]==10. and pd.isna(table['执行参考价'].iloc[1])
    assert table['原因'].iloc[1]=='标的处于停牌状态'
    assert table['状态'].iloc[0]=='部分成交'


def test_order_display_graph_and_table_share_rows_and_selection():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string('''
import pandas as pd
from test_portfolio_order_view import orders
from portfolio_app.portfolio_order_view import render_orders
render_orders(pd.DataFrame(orders()),revision='fixture')
''').run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    app.selectbox(key='portfolio_order_pick').set_value(1).run()
    assert any('标的处于停牌状态' in c.value for c in app.caption)
    app.segmented_control(key='portfolio_order_display').set_value('表格').run()
    assert not app.exception and len(app.get('plotly_chart'))==0
    assert app.dataframe[0].value['成交股数'].tolist()==[100,0]


def test_order_chart_page_preserves_global_row_ids_and_missing_reasons():
    from portfolio_app.portfolio_order_view import order_chart
    frame=pd.DataFrame(orders()*6)
    frame.loc[9,'reason']=None
    fig=order_chart(frame.iloc[8:])
    assert len(fig.data[0].x)==4
    assert list(fig.data[0].customdata[1])==[9,'BBB','SELL','REJECTED','—']
    assert fig.data[0].y[0].startswith('9 · ')


def test_order_paging_does_not_hide_rows_from_table_or_details():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string('''
import pandas as pd
from test_portfolio_order_view import orders
from portfolio_app.portfolio_order_view import render_orders
render_orders(pd.DataFrame(orders()*6),revision='many')
''').run()
    app.selectbox(key='portfolio_order_page').set_value(1).run()
    assert not app.exception
    app.selectbox(key='portfolio_order_pick').set_value(11).run()
    assert any('标的处于停牌状态' in c.value for c in app.caption)
    app.segmented_control(key='portfolio_order_display').set_value('表格').run()
    assert len(app.dataframe[0].value)==12

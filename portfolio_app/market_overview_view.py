"""Snapshot scope charts and tables built from one verified daily report."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .design_tokens import COLOR_TOKENS
from .market_overview import market_overview, overview_sessions
from .market_query import query_daily
from .research_charts import CHART_CONFIG, style_chart


def overview_table(report):
    data = report['details'].copy()
    data['status'] = '已记录'
    data.loc[data.price_change.isna(), 'status'] = '涨跌未知'
    data.loc[~data.observed.eq(True), 'status'] = '行情缺失'
    fields = dict(symbol='证券', name='名称', trade_date='日期', close='原始收盘（元）',
        pre_close='来源昨收（元）', price_change='价格涨跌幅', amount='成交额（元）',
        volume='成交量（股）', status='状态')
    return data[list(fields)].rename(columns=fields)


def breadth_chart(report):
    labels, counts = list(report['breadth']), list(report['breadth'].values())
    colors = [COLOR_TOKENS[k] for k in ('up','benchmark','down','warning','divider')]
    figure = go.Figure(go.Bar(x=counts, y=labels, orientation='h',
        marker_color=colors, width=.52, text=counts, textposition='outside', cliponaxis=False,
        hovertemplate='%{y} %{x:,} 只<extra></extra>'))
    style_chart(figure, height=330, revision=report['snapshot_id']+report['session']+'breadth')
    figure.update_layout(showlegend=False, hovermode='closest', margin=dict(l=10,r=40,t=25,b=40))
    figure.update_yaxes(type='category', autorange='reversed', showgrid=False)
    figure.update_xaxes(title_text='证券数量', rangemode='tozero', dtick=1 if report['expected'] < 8 else None,
        range=[0,max(1,max(counts,default=0)*1.18)])
    return figure


def ranking_chart(report, *, metric='price_change', limit=20):
    if metric not in ('price_change','amount'):
        raise ValueError('未知行情排序指标')
    # Every table row is retained; the chart shows both tails when the pool is large.
    data = report['details'].dropna(subset=[metric]).sort_values([metric,'symbol'])
    if len(data) > limit:
        data = (pd.concat([data.head(limit//2),data.tail(limit-limit//2)])
            if metric == 'price_change' else data.tail(limit))
    changes = metric == 'price_change'
    colors = [COLOR_TOKENS['up'] if v > 0 else COLOR_TOKENS['down'] if v < 0
        else COLOR_TOKENS['benchmark'] for v in data.price_change] if changes else COLOR_TOKENS['primary']
    figure = go.Figure(go.Bar(x=data[metric].tolist(),
        y=(data['name']+' · '+data.symbol).tolist(), orientation='h',
        customdata=data[['symbol','name']].values.tolist(), marker_color=colors,
        width=min(.52,.16*max(1,len(data))),
        hovertemplate='%{customdata[1]} · %{customdata[0]}<br>'+
            ('价格涨跌 %{x:+.2%}' if changes else '成交额 %{x:,.2f} 元')+'<extra></extra>'))
    style_chart(figure, height=max(330,110+len(data)*30),
        revision=report['snapshot_id']+report['session']+metric)
    figure.update_layout(showlegend=False, hovermode='closest', clickmode='event+select',
        margin=dict(l=10,r=30,t=25,b=45))
    figure.update_yaxes(type='category', showgrid=False, dtick=1)
    figure.update_xaxes(title_text='价格涨跌幅' if changes else '成交额（元）',
        tickformat='.1%' if changes else '~s', zeroline=True, rangemode='tozero')
    return figure


def selected_symbol(points, allowed):
    if not points:
        return None
    custom = points[-1].get('customdata', [])
    return custom[0] if isinstance(custom, (list,tuple)) and custom and custom[0] in allowed else None


def render_market_overview(store, manifest):
    """Return an explicitly opened security; viewing never submits research."""
    try:
        sessions = overview_sessions(manifest)
    except (ValueError,KeyError):
        st.error('所选版本的交易日历不完整，无法生成概览。')
        return None
    if not sessions:
        st.info('所选版本没有交易日。')
        return None
    snapshot_id = manifest['snapshot_id']
    heading, date_control = st.columns([2,1], vertical_alignment='bottom')
    heading.subheader('所选范围概览')
    session = date_control.selectbox('概览交易日', sessions, index=len(sessions)-1, filter_mode=None,
        key='market_overview_day_'+snapshot_id)
    try:
        frame = query_daily(store, snapshot_id, symbols=manifest['range']['symbols'],
            start=session, end=session,
            columns=['symbol','trade_date','close','pre_close','amount','volume'])
        report = market_overview(frame, manifest=manifest, session=session)
    except (ValueError,OSError,KeyError):
        st.error('该版行情或单位校验失败，概览已停止读取。请在数据中心检查版本。')
        return None
    st.session_state['_actual_context_watch'] = dict(dataset_id=manifest['dataset_id'],
        version=f"v{manifest['generation']}", source_kind='provider_snapshot', price_basis='raw',
        period='1d', snapshot_id=snapshot_id, dataset_generation=manifest['generation'],
        as_of=session, symbol=None)
    st.caption(f"{session} · {report['expected']} 只当日已上市证券 · v{report['generation']}")
    average, amount, coverage = st.columns(3)
    change = report['equal_weight_price_change']
    average.metric('等权价格涨跌', '—' if change is None else f'{change:+.2%}')
    total = report['amount_cny']
    amount.metric('已记录成交额', '—' if total is None else f'{total/1e8:,.2f} 亿')
    coverage.metric('涨跌覆盖', f"{report['valid_return']} / {report['expected']}")
    display = st.segmented_control('概览展示', ['图形','表格'], default='图形',
        key='market_overview_display')
    table = overview_table(report)
    symbol = None
    if display == '表格':
        st.dataframe(table, hide_index=True, width='stretch', column_config={
            '价格涨跌幅': st.column_config.NumberColumn(format='percent',help='原始收盘 / 来源昨收 − 1'),
            '成交额（元）': st.column_config.NumberColumn(format='localized')})
    else:
        left, right = st.columns([2,1])
        with left:
            ranking = st.selectbox('证券排序', ['价格涨跌','成交额'], filter_mode=None,
                key='market_overview_ranking')
            chart = ranking_chart(report, metric='price_change' if ranking == '价格涨跌' else 'amount')
            if not len(chart.data[0].x):
                st.info('当日缺少可用于排序的记录。')
            else:
                event = st.plotly_chart(chart, width='stretch', config=CHART_CONFIG,
                    key='market_overview_rank_'+snapshot_id+session+ranking,
                    on_select='rerun', selection_mode='points')
                symbol = selected_symbol(event.selection.points, table['证券'].tolist())
            if len(table) > 20:
                st.caption('涨跌展示两端各10只，成交额展示前20只；完整范围见表格或下载。')
        with right:
            st.markdown('**涨跌分布**')
            st.plotly_chart(breadth_chart(report), width='stretch', config=CHART_CONFIG,
                key='market_overview_breadth')
        if symbol:
            chosen = table.loc[table['证券'].eq(symbol)]
            st.dataframe(chosen, hide_index=True, width='stretch', column_config={
                '价格涨跌幅': st.column_config.NumberColumn(format='percent'),
                '成交额（元）': st.column_config.NumberColumn(format='localized')})
            if st.button('打开 '+symbol+' 行情', key='market_overview_open'):
                return symbol
    st.caption('原始收盘 ÷ 来源昨收 − 1；等权仅含有效记录。上市前及退市后排除，未知值不计零。')
    amount_coverage = report['amount_coverage']
    if amount_coverage is not None and amount_coverage < 1:
        st.caption(f'成交额覆盖 {amount_coverage:.1%}，合计仅包含已记录金额。')
    st.download_button('下载当日明细', table.to_csv(index=False).encode('utf-8-sig'),
        file_name=f'market-scope-{session}-v{report["generation"]}.csv', mime='text/csv',
        key='market_overview_csv')
    return None

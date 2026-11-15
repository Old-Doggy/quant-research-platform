"""Coverage cells, inspection and explicit version rollback use one manifest."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .market_query import query_daily
from .research_charts import style_chart, CHART_CONFIG

STATUS = {
    'observed': ('已核对日线', '#2864D7'),
    'not_listed': ('未上市/已退市', '#D8E0EC'),
    'suspended': ('有证据停牌', '#68788D'),
    'unknown_gap': ('未知缺口', '#A46B16'),
    'conflict': ('冲突', '#C4424B'),
}


def coverage_chart(rows, snapshot_id):
    fig = go.Figure()
    for status, (label, color) in STATUS.items():
        part = rows.loc[rows.status.eq(status)]
        if part.empty:
            continue
        fig.add_trace(go.Scatter(x=part.session, y=part.symbol, mode='markers', name=label,
            marker=dict(symbol='square', size=20, color=color),
            customdata=part[['symbol', 'session']].values.tolist(),
            hovertemplate='%{y}<br>%{x}<br>'+label+'<extra></extra>',
            selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=.65))))
    style_chart(fig, height=max(180, min(650, 120+rows.symbol.nunique()*30)), revision=snapshot_id)
    fig.update_layout(hovermode='closest', clickmode='event+select', dragmode='pan',
        margin=dict(l=100, r=24, t=55, b=55))
    fig.update_xaxes(type='category', categoryorder='array', categoryarray=sorted(rows.session.unique()))
    if rows.session.nunique() > 45:
        fig.update_xaxes(range=[rows.session.nunique()-40.5, rows.session.nunique()-.5])
    fig.update_yaxes(type='category')
    return fig


def render_coverage(store):
    manifests = []
    invalid = 0
    for path in store.directory.glob('snapshot-*.json'):
        try:
            manifests.append(store.open(path.stem))
        except (ValueError, OSError, KeyError):
            invalid += 1
    if invalid:
        st.warning(f'{invalid}份版本清单校验失败，已停止读取这些版本。')
    if not manifests:
        st.info('尚无可读取的行情快照。完成更新和核对后，这里显示覆盖与版本。')
        return
    manifests.sort(key=lambda m:(m['dataset_id'], m['generation']), reverse=True)
    by_id = {m['snapshot_id']:m for m in manifests}
    chosen = st.selectbox('行情版本', list(by_id), format_func=lambda key:
        f"{by_id[key]['dataset_id']} · v{by_id[key]['generation']} · {by_id[key]['range']['start']}—{by_id[key]['range']['end']}",
        filter_mode=None, key='coverage_snapshot')
    manifest = by_id[chosen]
    from .data_service_view import record_service_context
    record_service_context(manifest)
    rows = pd.DataFrame(manifest['checks']['coverage']['rows'])
    st.caption(f"{len(manifest['range']['symbols'])}只证券 · {rows.session.nunique()}个交易日 · {len(rows)}个覆盖单元")
    mode = st.segmented_control('覆盖展示', ['图形','表格'], default='图形', key='coverage_view_mode')
    selected = []
    if mode=='表格':
        display = rows.copy()
        display['status'] = display.status.map(lambda s:STATUS.get(s, (s,))[0])
        st.dataframe(display.rename(columns={'symbol':'证券','session':'日期','status':'状态'}), hide_index=True, width='stretch')
    else:
        st.caption('点击覆盖单元查看当日数据；蓝色为已核对日线。')
        event = st.plotly_chart(coverage_chart(rows, chosen), width='stretch', config=CHART_CONFIG,
            key='coverage_matrix_'+chosen, on_select='rerun', selection_mode='points')
        selected = event.selection.points
    symbol_key = 'snapshot_inspect_symbol_'+chosen
    selected_day = None
    selection_key='coverage_selected_'+chosen
    if selected:
        custom = selected[-1].get('customdata', [])
        if len(custom)==2 and custom[0] in manifest['range']['symbols']:
            if st.session_state.get(selection_key)!=custom:
                st.session_state[symbol_key] = custom[0]
                st.session_state[selection_key] = custom
            if st.session_state.get(symbol_key)==custom[0]:
                selected_day = custom[1]
    symbol = st.selectbox('查看证券', manifest['range']['symbols'], filter_mode=None, key=symbol_key)
    try:
        price = query_daily(store, chosen, symbols=[symbol], start=manifest['range']['start'], end=manifest['range']['end'],
            columns=['ts_code','trade_date','open','high','low','close','volume','amount'])
    except (ValueError, OSError, KeyError):
        st.error('该版底层批次缺失或校验失败。行情图已停止读取，请恢复批次或选择其他版本。')
        return
    if price.empty:
        st.info('该证券在此版没有日线记录。')
    else:
        fig = go.Figure(go.Scatter(x=price.trade_date, y=price.close, mode='lines+markers', name='原始收盘',
            line=dict(color='#2864D7', width=2.2), marker=dict(size=5),
            hovertemplate='%{x|%Y-%m-%d}<br>收盘 %{y:.2f} 元<extra></extra>'))
        style_chart(fig, height=320, revision=chosen+symbol)
        fig.update_xaxes(type='date', tickformat='%m-%d', dtick=86400000,
            rangebreaks=[dict(bounds=['sat','mon'])])
        fig.update_yaxes(title_text='元 / 股', side='right')
        st.plotly_chart(fig, width='stretch', config=CHART_CONFIG)
        if selected_day:
            detail = price.loc[price.trade_date.eq(pd.Timestamp(selected_day))]
            st.caption(f'{symbol} · {selected_day}')
            if detail.empty:
                status = rows.loc[rows.symbol.eq(symbol)&rows.session.eq(selected_day), 'status']
                st.write(STATUS.get(status.iloc[0], ('无行情记录',))[0] if len(status) else '无行情记录')
            else:
                st.dataframe(detail.rename(columns={'ts_code':'证券','trade_date':'日期','open':'开盘','high':'最高',
                    'low':'最低','close':'收盘','volume':'成交量（股）','amount':'成交额（元）'}), hide_index=True, width='stretch')
    st.caption('日线价量与覆盖已核对；研究事件包尚未验收。')
    try:
        current = store.current(manifest['dataset_id'])
    except (ValueError, OSError, KeyError):
        current = None
        st.warning('当前版本索引异常，可将已校验的保留版重新设为当前行情版本。')
    if current is None or current['snapshot_id']!=chosen:
        if st.button('设为当前行情版本', type='secondary', key='snapshot_rollback'):
            try:
                store.rollback(manifest['dataset_id'], chosen)
            except (ValueError, OSError, KeyError):
                st.error('切换失败，版本索引未更新。请检查批次与目录权限。')
            else:
                st.rerun()

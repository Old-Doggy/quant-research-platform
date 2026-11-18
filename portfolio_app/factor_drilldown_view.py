"""IC date selection, ranked cross-section and quarterly descriptive stability."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .factor_drilldown import factor_cross_section, factor_periods
from .research_charts import build_ic_chart, style_chart, CHART_CONFIG


def render_ic_drilldown(result):
    ic = pd.DataFrame(result['analysis']['ic_series'])
    if ic.empty:
        st.caption('没有可展示的IC日期。')
        return
    identity = result['run_id']
    sessions = sorted(pd.to_datetime(ic.trade_date).dt.strftime('%Y-%m-%d').unique())
    date_key = 'factor_ic_date_' + identity
    chart_key = 'factor_ic_select_' + identity
    def select_date():
        from .chart_events import plotly_date_event
        event = plotly_date_event(st.session_state.get(chart_key, {}),
            chart_id=identity, symbol='factor', sequence=1)
        if event and event['date'] in sessions:
            st.session_state[date_key] = event['date']
    fig = build_ic_chart(ic, revision=identity)
    fig.data[1].update(mode='lines+markers', marker=dict(size=9, opacity=0))
    fig.update_layout(clickmode='event+select')
    st.plotly_chart(fig, width='stretch', config=CHART_CONFIG, key=chart_key,
        on_select=select_date, selection_mode='points')
    left, right = st.columns([1.1, 2.9], gap='large')
    with left:
        session = st.selectbox('查看IC截面', sessions, index=len(sessions)-1,
            filter_mode=None, key=date_key)
        section = factor_cross_section(result, session)
        st.metric('当日 Rank IC', f"{section['ic']:.4f}" if section['ic'] is not None else '—')
        st.caption(f"有效证券 {section['samples']:,} · 未来 {result['config']['label_horizon_sessions']} 个交易日收益")
        if section['samples'] < 20:
            st.caption('小样本截面，仅作描述。')
        if section['status'] != 'ok':
            st.caption({'constant_factor': '因子值相同', 'constant_label': '未来收益相同',
                'insufficient_observations': '有效证券不足'}.get(section['status'], '相关性不可计算'))
    with right:
        detail = section['frame']
        scatter = go.Figure(go.Scatter(x=detail.factor_rank.tolist(), y=detail.label_rank.tolist(),
            mode='markers', customdata=detail[['symbol','factor','forward_label']].values.tolist(),
            marker=dict(size=10, color='#2864D7', opacity=.75, line=dict(width=1, color='white')),
            hovertemplate='%{customdata[0]}<br>因子 %{customdata[1]:.4f}<br>未来收益 %{customdata[2]:.2%}<br>排名 %{x:.1f} / %{y:.1f}<extra></extra>'))
        style_chart(scatter, title=session + ' · 因子与未来收益排名', height=300, revision=identity+session)
        scatter.update_xaxes(title_text='因子排名（由低到高）', dtick=1 if len(detail)<12 else None)
        scatter.update_yaxes(title_text='未来收益排名（由低到高）', dtick=1 if len(detail)<12 else None)
        st.plotly_chart(scatter, width='stretch', config=CHART_CONFIG, key='factor_ic_scatter')
    with st.expander('当日截面数据'):
        st.dataframe(detail, hide_index=True, width='stretch')
        st.download_button('下载当日截面', detail.to_csv(index=False).encode('utf-8-sig'),
            'factor-cross-section.csv', 'text/csv', key='factor_ic_section_csv')
    periods = factor_periods(result)
    st.subheader('季度稳定性')
    display = st.segmented_control('稳定性展示', ['图表','表格'], default='图表', key='factor_period_display')
    if display == '表格':
        st.dataframe(periods, hide_index=True, width='stretch')
    else:
        period_fig = go.Figure(go.Bar(x=periods.period.tolist(), y=periods.ic_mean.tolist(),
            marker_color=['#2864D7' if v>=0 else '#8D77AF' for v in periods.ic_mean],
            customdata=periods[['valid_sessions','sessions','positive_ratio']].values.tolist(),
            hovertemplate='%{x}<br>平均IC %{y:.4f}<br>有效日期 %{customdata[0]:.0f} / %{customdata[1]:.0f}<br>正IC占比 %{customdata[2]:.1%}<extra></extra>'))
        style_chart(period_fig, title='季度平均 Rank IC', height=260, revision=identity+'-quarters')
        period_fig.update_xaxes(type='category')
        period_fig.add_hline(y=0, line_color='#AAB7CA', line_width=1)
        st.plotly_chart(period_fig, width='stretch', config=CHART_CONFIG, key='factor_ic_periods')
    st.caption('按实际样本日期分期；重叠标签保留，季度均值用于描述。')
    st.download_button('下载季度统计', periods.to_csv(index=False).encode('utf-8-sig'),
        'factor-quarterly-ic.csv', 'text/csv', key='factor_period_csv')

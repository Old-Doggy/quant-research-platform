"""Compact, bilingual navigation for reviewed aggregate evidence."""
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from .design_tokens import COLOR_TOKENS
from .research_charts import build_comparison_chart, build_performance_chart, style_chart, CHART_CONFIG
from .research_help import help_link


def _remembered_select(label, options, *, name, language, labels, segmented=False):
    """Keep canonical selection outside Streamlit's language-specific widgets."""
    key = f"{name}_{language}"
    saved = st.session_state.get(f"{name}_saved", options[0])
    if st.session_state.get(f"{name}_language") != language or st.session_state.get(key) not in options:
        st.session_state[key] = saved if saved in options else options[0]
    st.session_state[f"{name}_language"] = language
    widget = st.segmented_control if segmented else st.selectbox
    kwargs = {"selection_mode": "single", "required": True} if segmented else {"filter_mode": None}
    value = widget(label, options, format_func=labels.__getitem__, key=key, **kwargs)
    st.session_state[f"{name}_saved"] = value
    return value


def _comparison_table(rows, *, annual, zh):
    """Keep numbers numeric in tables and exports; format only when displayed."""
    records=[]
    for row in rows:
        item={'year' if annual else 'scenario':row['year'] if annual else row['label'],
              'period':f"{row['start']} → {row['end']}" if annual else row['period'],
              **{key:row['metrics'].get(key) for key in ('annual_return','sharpe','max_drawdown')}}
        if annual:
            item.update(days=row['days'],coverage=('不完整' if zh else 'Incomplete') if row['incomplete'] else ('全年' if zh else 'Full year'))
        item.update(cost_assumption=row['cost_assumption'],source=row['source'],limitations=row['limitations'])
        records.append(item)
    frame=pd.DataFrame(records)
    if zh:
        frame=frame.rename(columns=dict(year='年度',scenario='情景',period='期间',annual_return='年化收益',
            sharpe='夏普',max_drawdown='最大回撤',days='交易日',coverage='覆盖',cost_assumption='成本口径',source='来源',limitations='限制'))
    return frame


def _annual_chart(rows, *, zh, revision):
    """Separate annual observations; partial-year values remain annualized."""
    fig=go.Figure(go.Bar(
        x=[r['year'] for r in rows], y=[r['metrics'].get('annual_return') for r in rows],
        name='年化收益' if zh else 'Annual return',width=.48,
        marker=dict(color=[COLOR_TOKENS['up'] if r['metrics'].get('annual_return',0)>=0 else COLOR_TOKENS['down'] for r in rows],
                    pattern=dict(shape=['/' if r['incomplete'] else '' for r in rows],solidity=.18)),
        text=[('—' if r['metrics'].get('annual_return') is None else format(r['metrics']['annual_return'],'.2%')) for r in rows],
        textposition='outside',cliponaxis=False,
        customdata=[[f"{r['start']} → {r['end']}",r['days'],
                     ('不完整年度 · 年化值' if zh else 'Partial year · annualized') if r['incomplete'] else ('完整年度' if zh else 'Full year')] for r in rows],
        hovertemplate='%{x}<br>%{customdata[0]}<br>'+('年化收益' if zh else 'Annual return')+
            ' %{y:.2%}<br>%{customdata[1]} '+('个交易日' if zh else 'sessions')+'<br>%{customdata[2]}<extra></extra>'))
    style_chart(fig,height=350,revision=revision)
    fig.update_layout(showlegend=False,hovermode='closest',margin=dict(l=18,r=40,t=45,b=42))
    fig.update_xaxes(type='category',showspikes=False)
    fig.update_yaxes(title_text='年化收益' if zh else 'Annual return',tickformat='.0%',rangemode='tozero',zeroline=True)
    values=[r['metrics']['annual_return'] for r in rows if r['metrics'].get('annual_return') is not None]
    if values:
        lo,hi=min(0.,min(values)),max(0.,max(values));pad=max((hi-lo)*.22,.01)
        fig.update_yaxes(range=[lo-pad,hi+pad])
    return fig


def _render_comparison(rows, *, annual, model_id, language):
    zh=language=='zh';kind='annual' if annual else 'cost'
    table=_comparison_table(rows,annual=annual,zh=zh)
    display=_remembered_select('展示方式' if zh else 'Display',['chart','table'],
        name=f'evidence_display_{model_id}_{kind}',language=language,
        labels={'chart':'图形' if zh else 'Chart','table':'表格' if zh else 'Table'},segmented=True)
    if display=='chart':
        revision=f'{model_id}-{kind}-'+','.join(r['year'] if annual else r['key'] for r in rows)
        if annual:
            figure=_annual_chart(rows,zh=zh,revision=revision)
        else:
            figure=build_comparison_chart([r['label'] for r in rows],
                [('年化收益' if zh else 'Annual return',[r['metrics'].get('annual_return') for r in rows])])
            figure.update_layout(uirevision=revision)
            figure.update_xaxes(title_text='年化收益' if zh else 'Annual return')
        st.plotly_chart(figure,width='stretch',config=CHART_CONFIG,key=f'evidence_chart_{model_id}_{kind}')
    else:
        st.dataframe(table,hide_index=True,width='stretch',column_config={
            '年化收益' if zh else 'annual_return':st.column_config.NumberColumn(format='percent'),
            '最大回撤' if zh else 'max_drawdown':st.column_config.NumberColumn(format='percent'),
            '夏普' if zh else 'sharpe':st.column_config.NumberColumn(format='%.2f')})
    if annual and any(r['incomplete'] for r in rows):
        st.caption('斜纹柱为不完整年度，显示年化收益；悬停可查看期间和交易日数。' if zh else
                   'Hatched bars mark partial years and show annualized returns. Hover for dates and sessions.')
    st.download_button('下载当前数据' if zh else 'Download current data',table.to_csv(index=False).encode('utf-8-sig'),
        f'{model_id}-{kind}.csv','text/csv',key=f'evidence_download_{model_id}_{kind}')


def render_project_evidence(view, *, model_id, language):
    zh = language == "zh"
    layers = view["layers"]
    if not layers:
        st.markdown("- 暂无经过审查的公开结果。" if zh else "- No reviewed result is available in this copy.")
        return
    pages = dict(zip(["summary", "curve", "cost", "annual", "audit"],
        ["证据摘要", "净值曲线", "成本情景", "年度样本外", "审计与限制"] if zh else
        ["Evidence summary", "NAV curve", "Cost scenarios", "Annual OOS", "Audit and limits"]))
    if any(layer.get('curve', {}).get('points') for layer in layers):
        pages = {key: pages[key] for key in ['curve', 'summary', 'cost', 'annual', 'audit']}
    page = _remembered_select("证据导航" if zh else "Evidence navigation", list(pages),
        name=f"evidence_page_{model_id}", language=language, labels=pages, segmented=True)
    by_key = {row["key"]: row for row in layers}
    if any(r.get('curve', {}).get('points') for r in layers):
        by_key = dict(sorted(by_key.items(), key=lambda item: not bool(item[1].get('curve', {}).get('points'))))
    selected = _remembered_select("证据层 / 情景" if zh else "Evidence layer / scenario", list(by_key),
        name=f"evidence_layer_{model_id}", language=language,
        labels={key: row["label"] for key, row in by_key.items()})
    row = by_key[selected]
    st.markdown(f"**{row['status_label']}** · {row['label']}")
    st.caption(f"{row['period']} · {row['cost_assumption']}")
    if selected == 'local_native_wfo':
        st.caption('2026-05-04 原生引擎研究 · 与股票池验证摘要为不同批次' if zh else
                   'Native-engine research dated 2026-05-04 · Separate from the pool-validation summary')
    def explain():
        st.write(('来源：' if zh else 'Source: ') + row['source'])
        st.write(row['limitations'])
        if model_id == 'model2' and selected == 'local_native_wfo':
            st.write('夏普：年化日均收益减 2% 无风险收益，再除以年化样本标准差。' if zh else
                     'Sharpe uses annualized arithmetic daily returns, a 2% risk-free rate and sample standard deviation.')
        elif model_id == 'model4':
            st.write('夏普沿用源回测：无风险收益为 0，波动率使用样本标准差；源日收益首日记 0，净值仍包含首日资金变化。' if zh else
                     'Source Sharpe uses a zero risk-free rate and sample standard deviation. Its first daily return is zero; NAV retains the opening-session capital change.')
        elif model_id in {'model1', 'model3', 'model5', 'model6', 'model7'}:
            st.write('夏普：年化日均收益减 3% 无风险收益，再除以年化样本标准差。' if zh else
                     'Sharpe uses annualized arithmetic daily returns, a 3% risk-free rate and sample standard deviation.')
        curve = row.get('curve', {})
        if curve.get('points'):
            st.write(('逐日来源：' if zh else 'Daily source: ') + curve['source'])
            st.code('SHA256 ' + curve['sha256'], language=None)
            st.write('净值以期初资金为 1，包含首日收益；交易成本沿用源回测。' if zh else
                     'Initial capital is 1, including first-session returns. Costs follow the source backtest.')
        st.write('比较限于相同项目、期间和证据层。' if zh else 'Compare matching projects, periods and evidence layers.')
    help_link('数据说明' if zh else 'About this data', explain, key=f'evidence_help_{model_id}_{language}')
    runtime = row["status"] == "runtime_only"
    if runtime:
        st.info("仅历史运行状态：无历史收益证据，不代表当前可执行状态。" if zh else "Historical runtime metadata only: no performance evidence or claim of current executability.")
    if page == "summary":
        if not runtime:
            labels = {"annual_return": "年化收益" if zh else "Annual return", "sharpe": "夏普" if zh else "Sharpe", "max_drawdown": "最大回撤" if zh else "Maximum drawdown"}
            columns = st.columns(3)
            for column, (key, label) in zip(columns, labels.items()):
                value = row["metrics"].get(key)
                column.metric(label, "—" if value is None else (f"{value:.2f}" if key == "sharpe" else f"{value:.2%}"))
        if not row.get('curve', {}).get('points'):
            st.write(row["limitations"])
    elif page == "curve":
        curve = row.get('curve', {})
        if curve.get('points') and not runtime:
            frame = pd.DataFrame(curve['points'])
            frame['date'] = pd.to_datetime(frame.date)
            values = st.columns(3)
            values[0].metric('期末净值' if zh else 'Ending NAV', f"{frame.value.iloc[-1]:.3f}")
            values[1].metric('累计收益' if zh else 'Total return', f"{frame.value.iloc[-1]-1:.2%}")
            values[2].metric('最大回撤' if zh else 'Maximum drawdown', f"{frame.drawdown.min():.2%}")
            display = st.segmented_control('展示方式' if zh else 'Display', ['chart', 'table'],
                format_func=lambda x: ({'chart':'图形','table':'表格'} if zh else {'chart':'Chart','table':'Table'})[x],
                default='chart', required=True, key=f'project_curve_display_{model_id}_{language}')
            if display == 'chart':
                figure = build_performance_chart(frame, date='date', nav='value',
                    title='净值与回撤' if zh else 'NAV and drawdown',
                    label=row['label'], revision=f'{model_id}-{selected}')
                figure.update_xaxes(ticklabelstep=1)
                st.plotly_chart(figure, width='stretch', config=CHART_CONFIG)
            else:
                st.dataframe(frame.rename(columns={'date':'日期','value':'净值','drawdown':'回撤'} if zh else {}),
                    hide_index=True, width='stretch', column_config={
                        '回撤' if zh else 'drawdown': st.column_config.NumberColumn(format='percent'),
                        '净值' if zh else 'value': st.column_config.NumberColumn(format='%.4f')})
            export=frame.rename(columns={'date':'日期','value':'净值','drawdown':'回撤'} if zh else {})
            st.download_button('下载净值与回撤' if zh else 'Download NAV and drawdown',
                export.to_csv(index=False,date_format='%Y-%m-%d').encode('utf-8-sig'),
                f'{model_id}-{selected}-curve.csv','text/csv',key=f'project_curve_download_{model_id}_{language}')
            st.caption(f"{frame.date.iloc[0]:%Y-%m-%d} → {frame.date.iloc[-1]:%Y-%m-%d} · {len(frame):,} " + ('个交易日 · 历史回测' if zh else 'sessions · Historical backtest'))
        else:
            st.info("该情景暂无逐日记录。" if zh else "No daily record is available for this scenario.")
    elif page == "cost":
        if not view["cost_comparable"] or runtime:
            st.info("现有证据不能构成同口径成本对照；不同证据层不可拼成成本曲线。" if zh else "Available evidence cannot be compared as a matched cost study. Different evidence layers are not a cost curve.")
            return
        _render_comparison(layers,annual=False,model_id=model_id,language=language)
    elif page == "annual":
        annual = view["annual"]
        if not annual or runtime:
            st.info("该证据未提供公开年度样本外记录，不从总收益推算。" if zh else "No public annual OOS records for this evidence; annual results are not inferred from aggregate returns.")
            return
        years = ["all", *[r["year"] for r in annual]]
        year = _remembered_select("年度" if zh else "Year", years, name=f"evidence_year_{model_id}",
            language=language, labels={key: ("全部年度" if zh else "All years") if key == "all" else key for key in years})
        shown = [r for r in annual if year == "all" or r["year"] == year]
        _render_comparison(shown,annual=True,model_id=model_id,language=language)
    else:
        st.write(row["limitations"])
        st.info("这里是公开审计结论摘要；不代表完整审计材料已公开，也不代表当前实盘可用。" if zh else "This is a public audit conclusion summary, not the complete audit package or evidence of live readiness.")

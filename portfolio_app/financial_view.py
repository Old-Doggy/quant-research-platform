"""Latest observed statement browser; historical availability stays explicit."""
import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from .financial_store import FinancialStore
from .research_charts import style_chart, CHART_CONFIG, PALETTE
from .research_diagnostics import show_safe_error
from .state_paths import state_root


METRICS = [('income','revenue','营业收入'),('income','n_income_attr_p','归母净利润'),
    ('cashflow','n_cashflow_act','经营现金流'),('balancesheet','total_assets','总资产')]


def statement_basis(table, mode):
    """Latest-observed arithmetic for browsing only; no backdated as-of claim."""
    if mode not in {'累计','单季度','TTM'}:
        raise ValueError('未知报表口径')
    result=table.copy(deep=True)
    result['basis']=mode
    result['input_count']=1
    result['input_versions']=[json.dumps([version]) for version in result.report_version]
    for index,row in table.iterrows():
        if row['endpoint']=='balancesheet' or mode=='累计':
            if row['endpoint']=='balancesheet': result.loc[index,'basis']='期末值'
            continue
        period=row['period'];year=int(period[:4]);quarter=period[5:]
        needed=[]
        if mode=='TTM' and quarter!='12-31':
            needed=[(1,f'{year-1}-12-31'),(-1,str(year-1)+period[4:])]
        elif mode=='单季度' and quarter!='03-31':
            needed=[(-1,f"{year}-"+{'06-30':'03-31','09-30':'06-30','12-31':'09-30'}[quarter])]
        value=row['value']
        versions=[row['report_version']]
        for sign,previous in needed:
            source=table.loc[table.endpoint.eq(row['endpoint']) & table.field.eq(row['field']) & table.period.eq(previous)]
            if len(source)!=1 or pd.isna(source.iloc[0]['value']) or pd.isna(value):
                value=float('nan')
                break
            value+=sign*source.iloc[0]['value']
            versions.append(source.iloc[0]['report_version'])
        result.loc[index,'value']=value
        result.loc[index,'input_count']=len(needed)+1
        result.loc[index,'input_versions']=json.dumps(versions)
    return result


def observed_statements(store, *, symbol, provider):
    rows = []
    for endpoint, field, label in METRICS:
        observed = store.observations(endpoint=endpoint, symbol=symbol, provider=provider)
        by_period = {}
        for row in observed:
            if row['report_type']!='1':
                continue
            rank=(max(row['ann_date'],row['f_ann_date'] or row['ann_date']),row['fetched_at'])
            if row['period'] not in by_period or rank>by_period[row['period']][0]:
                by_period[row['period']]=(rank,row)
        for _, row in sorted(by_period.values(),key=lambda item:item[1]['period']):
            # Latest observations are for browsing only, never an as-of backtest input.
            rows.append(dict(endpoint=endpoint,field=field,label=label,period=row['period'],value=row.get(field),
                ann_date=row['ann_date'],fetched_at=row['fetched_at'],artifact_id=row['artifact_id'],
                report_version=row['report_version']))
    return pd.DataFrame(rows,columns=['endpoint','field','label','period','value','ann_date',
        'fetched_at','artifact_id','report_version'])


def statement_chart(table, *, metric='overview', basis='累计', revision='financial'):
    """Plot observed flows as bars and balance-sheet stocks as dated levels."""
    metrics=METRICS if metric=='overview' else [entry for entry in METRICS if entry[1]==metric]
    if not metrics:
        raise ValueError('未知财务指标')
    overview=metric=='overview'
    titles=[label+' · '+('期末值' if endpoint=='balancesheet' else basis) for endpoint,_,label in metrics]
    figure=make_subplots(rows=2 if overview else 1,cols=2 if overview else 1,subplot_titles=titles,
        vertical_spacing=.25,horizontal_spacing=.13)
    periods=sorted(table.period.unique())
    for index,(endpoint,field,label) in enumerate(metrics):
        row,col=(index//2+1,index%2+1) if overview else (1,1)
        data=table.loc[table.field.eq(field)].set_index('period').reindex(periods)
        values=pd.to_numeric(data.value,errors='coerce')/1e8
        common=dict(x=periods,y=values.tolist(),name=titles[index],
            customdata=data[['ann_date','fetched_at']].fillna('—').values.tolist(),
            hovertemplate='%{x}<br>'+titles[index]+' %{y:,.3f} 亿元<br>公告 %{customdata[0]}<br>观察 %{customdata[1]}<extra></extra>')
        if endpoint=='balancesheet':
            trace=go.Scatter(**common,mode='lines+markers',connectgaps=False,
                line=dict(color=PALETTE[0],width=2.4),marker=dict(size=6))
        else:
            trace=go.Bar(**common,width=.55,marker_color=PALETTE[index%len(PALETTE)])
        figure.add_trace(trace,row=row,col=col)
        if not values.notna().any():
            figure.add_annotation(text='暂无数值',showarrow=False,x=.5,y=.5,
                xref='x domain',yref='y domain',row=row,col=col,font=dict(size=15,color='#52637B'))
    style_chart(figure,height=580 if overview else 400,revision=f'{revision}-{metric}-{basis}')
    figure.update_layout(showlegend=False,hovermode='closest',
        margin=dict(l=18,r=38,t=65,b=60))
    figure.update_xaxes(type='category',categoryorder='array',categoryarray=periods,
        tickangle=-25 if len(periods)>4 else 0,nticks=5,showspikes=False)
    figure.update_yaxes(title_text='亿元',tickformat=',.1f',rangemode='tozero',zeroline=True)
    return figure


def render_financial_data():
    st.subheader('证券财务')
    st.caption('观察记录 · 查看已抓取的报表，不按旧公告日回填历史研究。')
    store=FinancialStore(state_root()/'financial_service')
    provider=st.selectbox('财务来源',['sina','tushare'],filter_mode=None,key='financial_provider',
        format_func={'sina':'新浪 · 免费三表','tushare':'Tushare · 本机权限'}.get)
    with st.expander('获取与更新报表',expanded=False):
        with st.form('financial_fetch_form'):
            left,right=st.columns([1,2])
            symbol=left.text_input('证券代码',value='600000.SH',key='financial_symbol').strip().upper()
            periods_text=right.text_input('报告期',value='2024-12-31,2025-03-31,2025-06-30,2025-09-30,2025-12-31',
                help='季度末日期，逗号分隔。最多12个报告期。',key='financial_periods')
            submit=st.form_submit_button('获取并保存报表',type='primary')
    if submit:
        try:
            periods=[p.strip() for p in periods_text.replace('，',',').split(',') if p.strip()]
            if not 1<=len(periods)<=12:
                raise ValueError('报告期数量无效')
            if provider=='sina':
                from .providers.sina_financial import SinaFinancial
                adapter=SinaFinancial()
            else:
                from .providers.tushare import TushareProvider
                from .providers.tushare_financial import TushareFinancial
                adapter=TushareFinancial(TushareProvider())
            with st.status('获取三张报表',expanded=True) as status:
                for endpoint,label in [('income','利润表'),('balancesheet','资产负债表'),('cashflow','现金流量表')]:
                    batch=adapter.reports(endpoint,symbol,periods=periods)
                    store.ingest(batch)
                    st.write(f"{label} · {len(batch.frame)} 期 · 缺 {len(batch.metadata['missing_periods'])} 期")
                status.update(label='三表已保存',state='complete',expanded=False)
        except Exception as exc:
            show_safe_error(exc,operation='import')
    try:
        table=observed_statements(store,symbol=symbol,provider=provider)
    except Exception as exc:
        show_safe_error(exc,operation='archive')
        return
    if table.empty:
        st.info('这只证券还没有保存的财务报表。填写报告期后获取。')
        return
    # Source units must be confirmed per adapter; unknown Tushare values stay tabular.
    if provider=='tushare':
        st.caption('Tushare财务金额单位尚未实测核验，先展示来源值。')
        st.dataframe(table,hide_index=True,width='stretch')
        return
    range_column,basis_column,display_column=st.columns([1.2,1.3,1.])
    with range_column:
        period_mode=st.segmented_control('报告范围',['全部季度末','仅年报'],default='全部季度末',key='financial_report_range')
    with basis_column:
        basis=st.segmented_control('报表口径',['累计','单季度','TTM'],default='累计',key='financial_basis')
    with display_column:
        display=st.segmented_control('财务展示',['图表','表格'],default='图表',key='financial_display')
    table=statement_basis(table,basis)
    shown=table.loc[table.period.str.endswith('12-31')].copy() if period_mode=='仅年报' else table
    if display=='表格':
        st.dataframe(shown.rename(columns=dict(label='指标',period='报告期',value='金额（元）',ann_date='公告日',fetched_at='观察时间')),
            hide_index=True,width='stretch')
    else:
        choices={'overview':'四项概览',**{field:label for _,field,label in METRICS}}
        metric=st.selectbox('财务指标',list(choices),format_func=choices.get,key='financial_metric',filter_mode=None)
        if shown.empty:
            st.caption('当前范围没有对应报告期。可切回全部季度末查看。')
        else:
            from hashlib import sha256
            revision=sha256(shown.to_csv(index=False).encode('utf-8')).hexdigest()[:16]
            st.plotly_chart(statement_chart(shown,metric=metric,basis=basis,revision=revision),
                width='stretch',config=CHART_CONFIG,key='financial_statements_chart')
    st.caption(f'收入、利润及现金流：{basis}；总资产为期末值。缺期或缺数留空，转换按当前观察版本计算。')
    st.download_button('下载当前财务数据',shown.to_csv(index=False).encode('utf-8-sig'),
        'financial-observations.csv','text/csv',key='financial_csv')

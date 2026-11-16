"""Observed CB prices and conversion events; no inferred lifecycle cash flows."""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from .convertible_store import ConvertibleStore
from .research_charts import CHART_CONFIG,PALETTE,style_chart
from .research_diagnostics import show_safe_error
from .state_paths import state_root


def price_chart(batch):
    frame=batch.frame.sort_values('trade_date')
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,row_heights=[.76,.24],vertical_spacing=.08)
    fig.add_trace(go.Scatter(x=frame.trade_date,y=frame.close,name='收盘价',mode='lines',
        line=dict(color=PALETTE[0],width=2.3),connectgaps=False,
        hovertemplate='收盘 %{y:.3f} 元<extra></extra>'),row=1,col=1)
    fig.add_trace(go.Bar(x=frame.trade_date,y=frame.volume,name='成交量',marker_color='#A1B8DB',
        hovertemplate='成交量 %{y:,.0f} 张<extra></extra>'),row=2,col=1)
    style_chart(fig,height=460,revision=batch.metadata['batch_id'])
    fig.update_layout(hoversubplots='axis',margin=dict(l=18,r=64,t=48,b=38))
    fig.data[1].update(xaxis='x')
    fig.update_yaxes(title_text='价格 · 元/张',side='right',row=1,col=1)
    fig.update_yaxes(title_text='成交量 · 张',side='right',row=2,col=1)
    fig.update_xaxes(matches=None,anchor='y2',tickformat='%Y-%m',nticks=6,
        unifiedhovertitle=dict(text='%{x|%Y-%m-%d}'),row=1,col=1)
    fig.update_xaxes(matches='x',showticklabels=False,row=2,col=1)
    return fig


def conversion_chart(events,symbol):
    frame=pd.DataFrame(events).sort_values(['effective_date','ann_date'])
    fig=go.Figure(go.Scatter(x=pd.to_datetime(frame.effective_date),y=frame.price,
        customdata=frame.ann_date,name='转股价',mode='lines+markers',
        line=dict(color=PALETTE[1],width=2.2,shape='hv'),marker=dict(size=7),
        hovertemplate='转股价 %{y:.2f} 元<br>公告 %{customdata}<extra></extra>'))
    style_chart(fig,height=300,revision='conversion-'+symbol)
    fig.update_xaxes(title_text='生效日期',unifiedhovertitle=dict(text='生效 %{x|%Y-%m-%d}'))
    fig.update_yaxes(title_text='元/股',side='right')
    return fig


def render_convertible_data():
    st.subheader('可转债观察')
    st.caption('价格与成交量 · 债券资料 · 转股价调整')
    store=ConvertibleStore(state_root()/'convertible_service')
    with st.form('cb_fetch_form'):
        symbol=st.text_input('可转债代码',value='113052.SH',key='cb_fetch_symbol').strip().upper()
        left,right=st.columns(2)
        start=left.date_input('转债开始日期',value=pd.Timestamp.now(tz='Asia/Shanghai').date()-pd.Timedelta(days=90),key='cb_start')
        end=right.date_input('转债结束日期',value=pd.Timestamp.now(tz='Asia/Shanghai').date()-pd.Timedelta(days=1),key='cb_end')
        submit=st.form_submit_button('获取并保存转债数据',type='primary')
    if submit:
        try:
            from .providers.convertible import SinaConvertible
            with st.status('获取转债数据',expanded=True) as status:
                adapter=SinaConvertible()
                store.ingest(adapter.daily(symbol,start=start.isoformat(),end=end.isoformat()))
                st.write('日线已保存')
                store.ingest(adapter.reference(symbol))
                status.update(label='转债数据已保存',state='complete',expanded=False)
        except Exception as exc:
            show_safe_error(exc,operation='import')
    records=store.records()
    if not records:
        st.info('还没有保存的转债数据。选择代码与日期后获取。')
        return
    symbols=sorted({r['symbol'] for r in records})
    symbol=st.selectbox('选择转债',symbols,key='cb_symbol',filter_mode=None)
    selected=[r for r in records if r['symbol']==symbol]
    daily_records=[r for r in selected if r['endpoint']=='cb_raw_daily']
    refs=[r for r in selected if r['endpoint']=='cb_reference']
    try:
        reference=store.load(refs[0]['artifact_id']) if refs else None
        if reference:
            master=reference.metadata['master']
            st.markdown(f"**{master['name']} · {symbol}**")
            a,b,c=st.columns(3)
            a.metric('面值',f"{master['face_value']:g} 元")
            b.metric('正股',master['stock_symbol'] if master['stock_symbol']!='unknown' else '待补充')
            c.metric('评级 · 最新资料',master.get('rating') or '—')
            st.caption(f"上市 {master.get('list_date') or '—'} · 来源到期日 {master.get('maturity_date') or '—'} · 摘牌 {master.get('delist_date') or '—'}")
        display=st.segmented_control('转债展示',['图表','表格'],default='图表',key='cb_display')
        if daily_records:
            by_id={r['artifact_id']:r for r in daily_records}
            artifact=st.selectbox('日线批次',list(by_id),format_func=lambda k:by_id[k]['fetched_at'][:19],
                key='cb_daily_batch',filter_mode=None)
            batch=store.load(artifact)
            if batch.frame.empty:
                st.caption('所选区间没有观察行情。')
            else:
                dates=pd.to_datetime(batch.frame.trade_date)
                st.caption(f"{dates.min():%Y-%m-%d} 至 {dates.max():%Y-%m-%d} · {len(batch.frame)} 个观察日")
                if display=='图表':
                    st.plotly_chart(price_chart(batch),width='stretch',config=CHART_CONFIG,key='cb_prices')
                else:
                    st.dataframe(batch.frame.rename(columns=dict(trade_date='日期',symbol='代码',open='开盘',high='最高',
                        low='最低',close='收盘',volume='成交量（张）',amount='成交额（元）')),hide_index=True,width='stretch')
                st.download_button('下载转债日线',batch.frame.to_csv(index=False).encode('utf-8-sig'),
                    symbol+'-observed-prices.csv','text/csv',key='cb_prices_csv')
        else:
            st.caption('尚未保存该转债的日线。')
        events=reference.metadata['events'] if reference else []
        if events:
            st.subheader('转股价调整')
            if display=='图表':
                st.plotly_chart(conversion_chart(events,symbol),width='stretch',config=CHART_CONFIG,key='cb_conversion_prices')
            else:
                st.dataframe(pd.DataFrame(events)[['ann_date','effective_date','price','fetched_at']].rename(
                    columns=dict(ann_date='公告日期',effective_date='生效日期',price='转股价（元）',fetched_at='观察时间')),
                    hide_index=True,width='stretch')
            st.caption('按生效日展示来源记录；公告日见悬停信息。此批资料在抓取后可用。')
            st.download_button('下载转股价记录',pd.DataFrame(events).to_csv(index=False).encode('utf-8-sig'),
                symbol+'-conversion-events.csv','text/csv',key='cb_events_csv')
        else:
            st.caption('尚无可核验的转股价记录。')
    except Exception as exc:
        show_safe_error(exc,operation='archive')
        return
    from .research_help import help_link
    def explain():
        st.write('新浪成交量按张保存，成交额未提供，保持空值。日期仅包含来源观察记录；结束交易后的日期不补价。')
        st.write('债券资料为最新观察，其中“到期日”可能反映提前结束，不能代替原始合同期限。转股价保留公告日、生效日和抓取时间。')
        st.write('转股溢价还需要同日正股价格。赎回、回售、退市结算及历史交易规则未齐备，当前用于观察。')
    help_link('数据与口径',explain,key='cb_data_help')

"""Simple price/volume conditions beside dated scatter and table results."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .market_overview import overview_sessions
from .market_overview_view import overview_table,selected_symbol
from .market_query import query_daily
from .research_charts import CHART_CONFIG,style_chart
from .screener import SCREEN_FIELDS,screen_daily,validate_screen
from .screener_store import ScreenerStore
from .state_paths import state_root


def screen_table(result):
    return overview_table(dict(details=result['details']))


def screen_scatter(result,*,x,y):
    if x not in SCREEN_FIELDS or y not in SCREEN_FIELDS:
        raise ValueError('筛选图形字段不可用')
    data=result['details'].dropna(subset=list(dict.fromkeys([x,y])))
    formats={field:('.2%' if field=='price_change' else ',.2f' if field=='close' else ',.0f')
        for field in SCREEN_FIELDS}
    fig=go.Figure(go.Scatter(x=data[x].tolist(),y=data[y].tolist(),mode='markers',
        customdata=data[['symbol','name']].values.tolist(),
        marker=dict(color='#2864D7',size=10,opacity=.8,line=dict(color='white',width=1)),
        hovertemplate='%{customdata[1]} · %{customdata[0]}<br>'+SCREEN_FIELDS[x]+f' %{{x:{formats[x]}}}<br>'+
            SCREEN_FIELDS[y]+f' %{{y:{formats[y]}}}<extra></extra>'))
    style_chart(fig,height=370,revision=result['screen_id']+x+y)
    fig.update_layout(clickmode='event+select',hovermode='closest',showlegend=False,
        margin=dict(l=15,r=30,t=24,b=45))
    ticks=lambda field:'.1%' if field=='price_change' else '.2f' if field=='close' else '~s'
    fig.update_xaxes(title_text=SCREEN_FIELDS[x],tickformat=ticks(x))
    fig.update_yaxes(title_text=SCREEN_FIELDS[y],tickformat=ticks(y))
    return fig


def filter_counts(result):
    labels=['当日范围']+[SCREEN_FIELDS[s['condition']['field']] for s in result['steps']]
    counts=[result['initial']]+[s['after'] for s in result['steps']]
    missing=[0]+[s['missing'] for s in result['steps']]
    fig=go.Figure(go.Bar(x=labels,y=counts,text=counts,textposition='outside',cliponaxis=False,
        marker_color='#2864D7',customdata=missing,
        hovertemplate='%{x}<br>剩余 %{y} 只<br>本步缺值 %{customdata} 只<extra></extra>'))
    style_chart(fig,height=200,revision=result['screen_id']+'counts')
    fig.update_layout(showlegend=False,hovermode='closest',margin=dict(l=10,r=20,t=24,b=35))
    fig.update_yaxes(rangemode='tozero',dtick=1 if result['initial']<8 else None)
    return fig


def _query(store,manifest,session):
    return query_daily(store,manifest['snapshot_id'],symbols=manifest['range']['symbols'],
        start=session,end=session,columns=['symbol','trade_date','close','pre_close','volume','amount'])


def form_conditions(amount,price,rise,missing):
    return [dict(field=field,op='ge',value=value,missing='keep' if missing=='保留并标记' else 'exclude')
        for field,value,active in [('amount',amount*1e8,amount>0),('close',price,price>0),
                                 ('price_change',rise*.01,rise>-100)] if active]


def control_values(saved):
    config=saved['config']
    validate_screen(config)
    defaults=dict(screen_amount_floor=0.,screen_price_floor=0.,screen_rise_floor=-100.,screen_missing='排除')
    for condition in config['conditions']:
        field=condition['field']
        if condition['op']!='ge' or field not in ('amount','close','price_change'):
            raise ValueError('此保存条件需要高级筛选器，不能改写为当前表单')
        control,scale={'amount':('screen_amount_floor',1e8),'close':('screen_price_floor',1.),
            'price_change':('screen_rise_floor',.01)}[field]
        defaults[control]=condition['value']/scale
        defaults['screen_missing']='保留并标记' if condition['missing']=='keep' else '排除'
    if (not -100.<defaults['screen_rise_floor']<=1000. and defaults['screen_rise_floor']!=-100.
            or form_conditions(defaults['screen_amount_floor'],defaults['screen_price_floor'],
                defaults['screen_rise_floor'],defaults['screen_missing'])!=config['conditions']):
        raise ValueError('保存条件不能由当前表单原样表示')
    return defaults


def _restore_controls(saved):
    defaults=control_values(saved)
    config=saved['config']
    for key,value in defaults.items():
        st.session_state[key]=value
    st.session_state['screen_day_'+config['snapshot_id']]=config['session']
    st.session_state['screen_x']=saved['view']['x']
    st.session_state['screen_y']=saved['view']['y']
    st.session_state['_screen_axes']=saved['view'].copy()


def render_screener(store,manifest):
    saved_store=ScreenerStore(state_root()/'screening')
    pending=st.session_state.pop('_screen_restore_pending',None)
    if pending:
        try:
            saved=saved_store.open(pending)
            if saved['config']['snapshot_id']!=manifest['snapshot_id']:
                st.info('请先选择此筛选保存的行情版本，再读取。')
            else:
                raw=_query(store,manifest,saved['config']['session'])
                saved_store.reproduce(pending,raw,manifest=manifest)
                _restore_controls(saved)
                st.success('已核对保存的条件、证券名单与数值。')
        except (ValueError,OSError,KeyError):
            st.error('保存筛选读取或复算失败，未替换当前条件。')
    try:
        records=saved_store.records()
    except (ValueError,OSError,KeyError):
        records=[]
        st.warning('部分保存筛选未通过校验，请检查本地筛选记录。')
    by_id={r['identifier']:r for r in records}
    picked=st.selectbox('已保存筛选',['']+list(by_id),filter_mode=None,key='screen_saved_pick',
        format_func=lambda key:'选择保存记录' if not key else
            f"{by_id[key]['name']} · {by_id[key]['session']} · {by_id[key]['count']}只")
    if picked and st.button('读取并核对',key='screen_restore'):
        st.session_state['_screen_restore_pending']=picked
        st.rerun()
    controls,main=st.columns([1,3])
    sessions=overview_sessions(manifest)
    if not sessions:
        st.info('此版本没有可筛选的交易日。')
        return None
    for key,value in dict(screen_amount_floor=0.,screen_price_floor=0.,screen_rise_floor=-100.).items():
        if key not in st.session_state:
            st.session_state[key]=value
    with controls:
        st.markdown('**筛选条件**')
        session=st.selectbox('筛选日期',sessions,index=len(sessions)-1,filter_mode=None,
            key='screen_day_'+manifest['snapshot_id'])
        amount=st.number_input('成交额至少（亿元）',min_value=0.,step=.1,key='screen_amount_floor')
        price=st.number_input('收盘价至少（元）',min_value=0.,step=1.,key='screen_price_floor')
        rise=st.number_input('价格涨跌至少（%）',min_value=-100.,max_value=1000.,
            step=1.,key='screen_rise_floor')
        missing=st.selectbox('条件字段缺值',['排除','保留并标记'],filter_mode=None,key='screen_missing')
        st.caption('0表示不限制金额/价格；−100%表示不限制涨跌。财务条件待时点数据接通后开放。')
    conditions=form_conditions(amount,price,rise,missing)
    config=dict(schema='daily-screener.v1',snapshot_id=manifest['snapshot_id'],session=session,
        universe_policy='snapshot_listed_on_session',conditions=conditions)
    try:
        result=screen_daily(_query(store,manifest,session),manifest=manifest,config=config)
    except (ValueError,OSError,KeyError):
        main.error('所选行情或筛选口径校验失败，未生成结果。')
        return None
    st.session_state['_actual_context_watch']=dict(dataset_id=manifest['dataset_id'],
        version=f"v{manifest['generation']}",source_kind='provider_snapshot',price_basis='raw',period='1d',
        snapshot_id=manifest['snapshot_id'],dataset_generation=manifest['generation'],as_of=session,symbol=None)
    with main:
        st.metric('符合条件 / 当日范围',f"{len(result['symbols'])} / {result['initial']}")
        st.plotly_chart(filter_counts(result),width='stretch',config=CHART_CONFIG,key='screen_counts')
        display=st.segmented_control('筛选展示',['散点','表格'],default='散点',key='screen_display')
        table=screen_table(result)
        axes=st.session_state.get('_screen_axes',dict(x='amount',y='price_change'))
        x,y=axes['x'],axes['y']
        if display=='表格':
            st.dataframe(table,hide_index=True,width='stretch',column_config={
                '价格涨跌幅':st.column_config.NumberColumn(format='percent')})
        else:
            first,second=st.columns(2)
            for key,value in [('screen_x',x),('screen_y',y)]:
                if key not in st.session_state:
                    st.session_state[key]=value
            x=first.selectbox('横轴',list(SCREEN_FIELDS),filter_mode=None,
                format_func=SCREEN_FIELDS.get,key='screen_x')
            y=second.selectbox('纵轴',list(SCREEN_FIELDS),filter_mode=None,
                format_func=SCREEN_FIELDS.get,key='screen_y')
            st.session_state['_screen_axes']=dict(x=x,y=y)
            chart=screen_scatter(result,x=x,y=y)
            event=st.plotly_chart(chart,width='stretch',config=CHART_CONFIG,
                key='screen_scatter_'+result['screen_id']+x+y,on_select='rerun',selection_mode='points')
            plotted=len(chart.data[0].x)
            st.caption(f'{plotted} 只有完整坐标；{len(table)-plotted} 只缺坐标，仍保留在表格与下载中。')
            symbol=selected_symbol(event.selection.points,result['symbols'])
            if symbol:
                st.dataframe(table.loc[table['证券'].eq(symbol)],hide_index=True,width='stretch')
                if st.button('打开 '+symbol+' 行情',key='screen_open_security'):
                    return symbol
        st.caption(f"{session}的固定证券名单 · v{manifest['generation']}；不表示历史逐日选股。")
        st.download_button('下载筛选结果',table.to_csv(index=False).encode('utf-8-sig'),
            file_name=f'screen-{session}.csv',mime='text/csv',key='screen_csv')
        name=st.text_input('保存名称',value='价量筛选',max_chars=60,key='screen_save_name')
        if st.button('保存本次筛选',key='screen_save'):
            try:
                saved_store.save(name,result,x=x,y=y)
                st.success('已保存条件、行情版本和完整证券名单。')
            except (ValueError,OSError,KeyError):
                st.error('筛选未能保存，请检查名称与本地目录。')
        if not result['research_ready']:
            st.caption('此行情版尚缺公司行为与交易状态核验，当前名单仅供浏览。')
    return None

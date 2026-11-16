"""Interactive heatmap and exact common-security scatter for computed factors."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .factor_comparison import research_factor_comparison,comparison_sample
from .factor_compute import BASIC_FACTOR_SPECS
from .research_charts import style_chart,CHART_CONFIG
from .research_manifest import semantic_hash,computation_revision
from .research_result_cache import build_data_fingerprint
from .research_display import check_research_size
from .research_task_view import background_task

FACTOR_NAMES={'basic.'+key:value for key,value in {
    'return_1d':'1日涨跌幅','return_5d':'5日涨跌幅','return_20d':'20日涨跌幅','return_60d':'60日涨跌幅',
    'reversal_5d':'5日反转','realized_volatility_20d':'20日波动率','atr_ratio_14d':'14日ATR比例',
    'ma_deviation_20d':'20日均线偏离','volume_ratio_20d':'20日量比',
    'price_volume_corr_20d':'20日量价相关','range_position_20d':'20日区间位置','illiquidity':'非流动性'}.items()}


def selected_pair(points,result):
    for point in points:
        values=point.get('customdata')
        if isinstance(values,(tuple,list)) and len(values)>=2:
            left,right=values[:2]
            if left!=right and all(f in result['factors'] for f in (left,right)):
                return left,right
    return None


def comparison_matrix(result,kind,*,names):
    rows=result[kind]
    fields=result['factors']
    cells={(r['left'],r['right']):r for r in rows.to_dict('records')}
    z,custom,text=[],[],[]
    for left in fields:
        zv,cv,tv=[],[],[]
        for right in fields:
            row=cells.get((left,right),cells.get((right,left),{}))
            value=row.get('correlation')
            value=float(value) if value is not None and pd.notna(value) else None
            zv.append(value)
            cv.append([left,right,row.get('common_n',0),row.get('status','same_factor')])
            tv.append(f'{value:.2f}' if value is not None else '—')
        z.append(zv);custom.append(cv);text.append(tv)
    labels=[names.get('basic.'+f,f) for f in fields]
    fig=go.Figure(go.Heatmap(x=labels,y=labels,z=z,customdata=custom,text=text,
        texttemplate='%{text}',zmin=-1,zmax=1,zmid=0,
        colorscale=[[0,'#D45967'],[.5,'#F4F7FC'],[1,'#2864D7']],hoverongaps=False,
        hovertemplate='%{y} × %{x}<br>相关系数 %{z:.3f}<br>共同观测 %{customdata[2]}<extra></extra>',
        colorbar=dict(title='Rank相关',thickness=12)))
    # Heatmap cells do not emit Plotly selection events in Streamlit. A small
    # transparent scatter hit area supplies the same pair identity.
    hits=[(i,j) for i in range(len(fields)) for j in range(len(fields)) if i!=j and z[i][j] is not None]
    fig.add_trace(go.Scatter(x=[labels[j] for i,j in hits],y=[labels[i] for i,j in hits],
        customdata=[custom[i][j] for i,j in hits],mode='markers',showlegend=False,
        marker=dict(symbol='square',size=48,color='rgba(40,100,215,0.01)'),
        hovertemplate='%{y} × %{x}<br>共同观测 %{customdata[2]}<extra></extra>'))
    style_chart(fig,height=380)
    fig.update_layout(clickmode='event+select',hovermode='closest',margin=dict(l=12,r=12,t=15,b=75))
    fig.update_yaxes(autorange='reversed')
    return fig


def render_factor_comparison(frame,*,names,public_mode):
    check_research_size(frame)
    names={**FACTOR_NAMES,**names}
    choices=[s.factor_id for s in BASIC_FACTOR_SPECS]
    ids=st.multiselect('比较因子（最多6个）',choices,
        default=['basic.return_5d','basic.reversal_5d','basic.ma_deviation_20d'],
        max_selections=6,format_func=lambda f:names.get(f,next(s.name for s in BASIC_FACTOR_SPECS if s.factor_id==f)),
        key='factor_compare_ids')
    horizon=st.selectbox('IC标签跨度',[1,5,10,20],index=1,filter_mode=None,key='factor_compare_horizon')
    run=st.button('计算因子比较',type='primary',key='factor_compare_run',disabled=len(ids)<2)
    start,end=frame.trade_date.min().date().isoformat(),frame.trade_date.max().date().isoformat()
    identity=semantic_hash(dict(data=build_data_fingerprint(frame),factors=ids,horizon=horizon,
        start=start,end=end,revision=computation_revision()))
    def compute(token):
        token.checkpoint()
        result=research_factor_comparison(frame,factor_ids=ids,horizon=horizon,start=start,end=end)
        token.checkpoint()
        value=dict(comparison=result,research_parameters=dict(factor_ids=ids,horizon=horizon,start=start,end=end),
            data_mode=frame.attrs.get('research_dataset',{}).get('source_kind'))
        if not public_mode:
            from .result_replay import comparison_replay_inputs
            value['replay']=comparison_replay_inputs(frame,config={**value['research_parameters'],'min_assets':3})
        return value
    task,computed=background_task(workspace='factors',identity=identity,compute=compute,
        start=run,public_mode=public_mode)
    if computed is not None:
        st.session_state['_factor_compare_result']=(identity,computed['comparison'])
    saved=st.session_state.get('_factor_compare_result')
    if task.get('status')=='running':
        st.caption('正在计算所选因子…')
    if task.get('status')=='failed':
        st.error('比较未完成，请检查行情与研究数据说明。')
    if not saved:
        st.caption('选择实际因子后计算相关性。')
        return
    if saved[0]!=identity:
        st.info('条件已改变，请重新计算因子比较。上次结果仍保存在实验记录。')
        return
    result=saved[1]
    mode=st.segmented_control('比较口径',['每日截面均值','IC序列'],default='每日截面均值',key='factor_compare_kind')
    kind='ic_correlation' if mode=='IC序列' else 'cross_section'
    st.caption('每个交易日按共同证券计算Rank相关，再对有效日期等权平均。' if kind=='cross_section'
        else f'因子各自与未来{horizon}日收益计算每日IC，再按共同日期计算Rank相关；至少20个有效日期。')
    event=st.plotly_chart(comparison_matrix(result,kind,names=names),width='stretch',config=CHART_CONFIG,
        key='factor_compare_matrix_'+identity+kind,on_select='rerun',selection_mode='points')
    rows=result[kind].copy()
    st.download_button('下载相关性',rows.to_csv(index=False).encode('utf-8-sig'),
        'factor-correlation.csv','text/csv',key='factor_compare_csv')
    pair=selected_pair(event.selection.points,result)
    pairs=[(r.left,r.right) for r in rows.itertuples()]
    if pair:
        st.session_state['_factor_compare_pair']=pair
    pair=st.session_state.get('_factor_compare_pair')
    if pair and pair[::-1] in pairs:
        pair=pair[::-1]
    if pair not in pairs:
        pair=pairs[0]
    control_key='factor_compare_pair_'+identity
    if pair!=st.session_state.get('_factor_compare_pair_applied'):
        st.session_state[control_key]=pair
        st.session_state['_factor_compare_pair_applied']=pair
    left,right=st.selectbox('查看因子对',pairs,format_func=lambda p:' × '.join(names.get('basic.'+f,f) for f in p),
        filter_mode=None,key=control_key)
    if kind=='cross_section':
        sessions=sorted(result['values'].trade_date.dt.strftime('%Y-%m-%d').unique())
        session=st.selectbox('截面日期',sessions,index=len(sessions)-1,filter_mode=None,key='factor_compare_date_'+identity)
        detail=comparison_sample(result,left=left,right=right,session=session)
        x,y='left_value','right_value'
    else:
        detail=result['ic_series'][['trade_date',left,right]].dropna()
        detail=detail.assign(symbol=detail.trade_date.dt.strftime('%Y-%m-%d'))
        x,y=left,right
    st.caption(f'共同样本 {len(detail):,} '+('只证券' if kind=='cross_section' else '个日期'))
    fig=go.Figure(go.Scatter(x=detail[x].tolist(),y=detail[y].tolist(),mode='markers',
        customdata=detail.symbol.tolist(),marker=dict(color='#2864D7',size=8,opacity=.7),
        hovertemplate='%{customdata}<br>%{x:.4f} / %{y:.4f}<extra></extra>'))
    style_chart(fig,height=320,revision=identity+str((left,right,mode)))
    fig.update_xaxes(title_text=names.get('basic.'+left,left))
    fig.update_yaxes(title_text=names.get('basic.'+right,right))
    st.plotly_chart(fig,width='stretch',config=CHART_CONFIG,key='factor_compare_scatter')
    with st.expander('比较数据'):
        st.dataframe(detail,hide_index=True,width='stretch')

"""ETF observation and comparison, separate from unverified execution capabilities."""
import re

import pandas as pd
import streamlit as st

from .etf_research import ETFStore,compare_etf_prices
from .research_charts import CHART_CONFIG
from .research_diagnostics import show_safe_error
from .result_comparison import comparison_curve
from .state_paths import state_root


def render_etf_data():
    st.subheader('ETF价格比较')
    st.caption('未复权市场价格 · 分红、份额和基金净值单独核验。')
    store=ETFStore(state_root()/'etf_service')
    with st.form('etf_fetch_form'):
        symbols_text=st.text_input('场内基金代码',value='510300.SH,511010.SH,518880.SH',
            help='最多4只；代码范围包括场内基金，类别仍需基金资料确认。',key='etf_symbols')
        left,right=st.columns(2)
        start=left.date_input('ETF开始日期',value=pd.Timestamp.now(tz='Asia/Shanghai').date()-pd.Timedelta(days=90),key='etf_start')
        end=right.date_input('ETF结束日期',value=pd.Timestamp.now(tz='Asia/Shanghai').date()-pd.Timedelta(days=1),key='etf_end')
        submit=st.form_submit_button('获取并保存ETF行情',type='primary')
    if submit:
        try:
            symbols=[s for s in re.split(r'[,，\s]+',symbols_text.strip().upper()) if s]
            if not 1<=len(symbols)<=4 or len(symbols)!=len(set(symbols)):
                raise ValueError('ETF数量或重复代码无效')
            from .providers.etf import SinaETF
            with st.status('获取ETF行情',expanded=True) as status:
                for symbol in symbols:
                    batch=SinaETF().daily(symbol,start=start.isoformat(),end=end.isoformat())
                    store.ingest(batch)
                    st.write(f'{symbol} · {len(batch.frame):,} 条观察行情')
                status.update(label='ETF行情已保存',state='complete',expanded=False)
        except Exception as exc:
            show_safe_error(exc,operation='import')
    records=store.records()
    if not records:
        st.info('还没有保存的ETF行情。选择代码与日期后获取。')
        return
    by_id={r['artifact_id']:r for r in records}
    newest={}
    for row in records:
        newest.setdefault(row['symbol'],row['artifact_id'])
    selected=st.multiselect('选择行情批次（最多4项）',list(by_id),default=list(newest.values())[:4],max_selections=4,
        format_func=lambda key:f"{by_id[key]['symbol']} · {by_id[key]['fetched_at'][:19]}",key='etf_selected_batches')
    if not selected:
        st.caption('选择至少一个行情批次。')
        return
    try:
        batches={key:store.load(key) for key in selected}
        frames={f"{b.metadata['symbol']} · {key[6:14]}":b.frame for key,b in batches.items() if not b.frame.empty}
        result=compare_etf_prices(frames)
    except Exception as exc:
        show_safe_error(exc,operation='archive')
        return
    if not frames:
        st.caption('所选批次没有观察行情。')
        return
    display=st.segmented_control('ETF展示',['图表','表格'],default='图表',key='etf_display')
    if display=='图表':
        curves={name:data.rename(columns={'price_index':'nav','price_drawdown':'drawdown'})
            for name,data in result['curves'].items()}
        figure=comparison_curve(dict(curves=curves))
        figure.update_yaxes(title_text='价格指数 · 首值=1',row=1,col=1)
        figure.update_yaxes(title_text='价格回撤',row=2,col=1)
        st.plotly_chart(figure,width='stretch',config=CHART_CONFIG,key='etf_price_comparison')
    else:
        st.dataframe(pd.concat([data.assign(batch=name) for name,data in result['curves'].items()],ignore_index=True),
            hide_index=True,width='stretch')
    st.caption('曲线只表示价格变化，不包含现金分红；各批次保留自己的日期和首个观察价格。')
    summary=result['summary']
    st.dataframe(summary.rename(columns=dict(symbol='批次',start='开始',end='结束',observed_sessions='观察日数',
        price_return='价格变化',max_price_drawdown='最大价格回撤')),hide_index=True,width='stretch',
        column_config={'价格变化':st.column_config.NumberColumn(format='percent'),
            '最大价格回撤':st.column_config.NumberColumn(format='percent')})
    combined=pd.concat([data.assign(batch=name) for name,data in result['curves'].items()],ignore_index=True)
    st.download_button('下载ETF价格数据',combined.to_csv(index=False).encode('utf-8-sig'),
        'etf-observed-prices.csv','text/csv',key='etf_prices_csv')
    from .research_help import help_link
    def explain():
        st.write('新浪日线成交量按份、成交额按元保存，原始数据一同保留。未提供真实交易日历和停牌证据时，观察行数不等于完整覆盖。')
        st.write('类别、历史分红、可得基金净值和证券交易规则仍待接入；当前入口用于价格观察与比较。')
    help_link('数据与口径',explain,key='etf_data_help')

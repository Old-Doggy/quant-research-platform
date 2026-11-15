"""Quiet provider setup and explicit permission checks in the data workspace."""
import streamlit as st

from .provider_registry import provider_capabilities, probe_tushare_permission
from .providers.tushare import TushareProvider


def render_provider_status():
    with st.expander('数据接口 · 连接状态', expanded=False):
        capabilities = provider_capabilities()
        configured = capabilities[0]['credential_status'] == 'configured'
        st.caption('Tushare · 已读取本机凭据，接口权限待检查' if configured else 'Tushare · 尚未配置本机凭据')
        st.caption('行情、证券资料和公司行为已接入适配器；自动更新尚在接入。')
        if st.button('检查接口权限', key='provider_probe_tushare', disabled=not configured):
            provider = TushareProvider()
            st.session_state['provider_probe_results'] = [probe_tushare_permission(provider, row['capability'])
                for row in capabilities if row['provider'] == 'tushare']
        labels = {'a_daily_raw': 'A股日线', 'instrument_master': '证券主表', 'market_calendar': '交易日历',
                  'adjustment_factors': '复权因子', 'daily_basic': '每日指标',
                  'dividends': '分红送转', 'suspensions': '停复牌',
                  'price_limits': '涨跌停价', 'index_daily': '指数日线'}
        statuses = {'available': '可访问', 'permission_denied': '权限不足', 'rate_limited': '限流，稍后重试',
            'network_error': '连接失败', 'credentials_missing': '未配置凭据', 'credentials_invalid': '凭据无效',
            'empty_response': '返回为空', 'invalid_response': '返回格式异常', 'upstream_rejected': '请求未接受'}
        for row in st.session_state.get('provider_probe_results', []):
            st.caption(f"{labels[row['capability']]} · {statuses.get(row['status'], '待检查')}")
        st.markdown('[数据配置说明](https://tushare.pro/document/1?doc_id=39)')
        st.caption('腾讯原始日线 · 沪深及北交小样本已检查，自动备用待跨源核对。')
        free_labels = {'sina':'新浪','eastmoney':'东方财富','baostock':'BaoStock'}
        free_statuses = {'sample_verified':'小样本已检查','rate_limited':'最近检查限流','dependency_missing':'未安装可选采集组件'}
        for row in capabilities:
            if row['provider'] in free_labels:
                status = row['access_status'] if row['access_status']=='dependency_missing' else row['last_check_status']
                st.caption(f"{free_labels[row['provider']]} · {free_statuses[status]}（2026-11-15）· 自动备用待验证")

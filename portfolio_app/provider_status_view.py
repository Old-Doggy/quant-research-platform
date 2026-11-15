"""Quiet provider setup and explicit permission checks in the data workspace."""
import streamlit as st

from .provider_registry import provider_capabilities, probe_tushare_permission
from .providers.tushare import TushareProvider


def render_provider_status():
    with st.expander('数据接口 · 连接状态', expanded=False):
        capabilities = provider_capabilities()
        configured = capabilities[0]['credential_status'] == 'configured'
        st.caption('Tushare · 已读取本机凭据，接口权限待检查' if configured else 'Tushare · 尚未配置本机凭据')
        st.caption('未复权日线、证券主表、交易日历已接入适配器；尚未开放自动更新。')
        if st.button('检查接口权限', key='provider_probe_tushare', disabled=not configured):
            provider = TushareProvider()
            st.session_state['provider_probe_results'] = [probe_tushare_permission(provider, row['capability']) for row in capabilities]
        labels = {'a_daily_raw': 'A股日线', 'instrument_master': '证券主表', 'market_calendar': '交易日历'}
        statuses = {'available': '可访问', 'permission_denied': '权限不足', 'rate_limited': '限流，稍后重试',
            'network_error': '连接失败', 'credentials_missing': '未配置凭据', 'credentials_invalid': '凭据无效',
            'empty_response': '返回为空', 'invalid_response': '返回格式异常', 'upstream_rejected': '请求未接受'}
        for row in st.session_state.get('provider_probe_results', []):
            st.caption(f"{labels[row['capability']]} · {statuses.get(row['status'], '待检查')}")
        st.markdown('[数据配置说明](https://tushare.pro/document/1?doc_id=39)')

"""Data-service views render only the active tab; importing stays independent."""
from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

import streamlit as st

from .provider_status_view import render_provider_status
from .snapshot_store import SnapshotStore
from .state_paths import state_root
from .update_launcher import launch_free_refresh, launch_retry, recent_refreshes, refresh_report


def market_service_root():
    return state_root()/'market_service'


def _current(store, dataset):
    try:
        return store.current(dataset)
    except (ValueError, OSError, KeyError):
        st.error('当前版本索引校验失败。请到“覆盖与版本”检查保留版本。')
        return None


def record_service_context(manifest=None):
    st.session_state['_data_service_context'] = None if manifest is None else dict(
        dataset_id=manifest['dataset_id'], generation=manifest['generation'],
        as_of=manifest['range']['end'], snapshot_id=manifest['snapshot_id'])


def _render_update(store):
    st.subheader('原始日线更新')
    st.caption('沪深自选范围 · BaoStock主表与日历 · 新浪 / BaoStock独立核对行情')
    records = recent_refreshes(store.root)
    if 'daily_refresh_request' not in st.session_state and records:
        st.session_state['daily_refresh_request'] = records[0]['request_id']
    with st.form('daily_refresh_form'):
        symbols_text = st.text_input('证券代码', value='600000.SH', help='最多20只沪深A股，多个代码用逗号分隔。')
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
        left, right = st.columns(2)
        start = left.date_input('开始日期', value=today-timedelta(days=14))
        end = right.date_input('结束日期', value=today-timedelta(days=1))
        submit = st.form_submit_button('更新数据', type='primary')
    if submit:
        symbols = sorted(set(filter(None, re.split(r'[,，\s]+', symbols_text.strip().upper()))))
        if any(r['report']['status']=='awaiting_result' for r in records):
            st.info('已有更新正在运行，请刷新任务状态。')
        else:
            try:
                record = launch_free_refresh(store.root, symbols=symbols, start=start.isoformat(), end=end.isoformat())
                st.session_state['daily_refresh_request'] = record['request_id']
            except (ValueError, OSError):
                st.error('未启动：请选择1至20只沪深A股，开始日期不晚于结束日期，范围不超过一年。')
    request = st.session_state.get('daily_refresh_request')
    if request:
        report = refresh_report(store.root, request)
        labels = {
            'awaiting_result':'任务已启动 · 离开页面后继续运行',
            'published':'行情核对通过，已发布新版本', 'incomplete':'部分来源未完成，已保留成功分片',
            'needs_review':'覆盖或来源差异待核对', 'no_sessions':'区间内无交易日',
            'interrupted':'任务中断，已保留成功分片', 'failed':'更新失败',
        }
        st.write(labels[report['status']])
        if report.get('error_code'):
            reasons = {'update_busy':'同一数据目录已有更新进程', 'invalid_request':'请求范围或格式不正确',
                'worker_exited_without_result':'更新进程已退出，未写入完成结果',
                'status_unreadable':'任务状态文件无法读取', 'local_or_network_error':'本机采集或网络异常'}
            st.caption('原因：'+reasons.get(report['error_code'], '来源请求未完成（'+report['error_code']+'）'))
        if report.get('jobs'):
            rows=[]
            states={'succeeded':'已下载','pending':'待下载','retry_wait':'等待重试','running':'下载中',
                'failed':'失败','needs_review':'待核对'}
            try:
                for job in report['jobs']:
                    for part in store.updates.shards(job['job_id']):
                        history=[h for h in store.updates.history(job['job_id']) if h['shard']==part['id']]
                        rows.append({'来源':store.updates.request(job['job_id'])['provider'],
                            '证券':part['payload']['symbol'], '状态':states.get(part['status'],part['status']),
                            '尝试次数':part['attempts'], '原因':history[-1]['error_code'] or '—' if history else '—'})
            except (ValueError,OSError,KeyError):
                st.error('分片日志校验失败，请检查本机更新记录。')
            st.dataframe(rows,hide_index=True,width='stretch')
        if report.get('checks'):
            checks=report['checks']
            st.caption('覆盖：'+('通过' if checks['coverage']['status']=='passed' else '待核对')+
                ' · 来源核对：'+('通过' if checks['comparison']['status']=='passed' else '待核对'))
            differences=checks['comparison'].get('differences',[])
            if differences:
                with st.expander('来源差异明细'):
                    st.dataframe(differences,hide_index=True,width='stretch')
        if report.get('plan_id') and report['status']=='incomplete':
            if st.button('只重试未完成分片',key='daily_refresh_retry',disabled=any(r['report']['status']=='awaiting_result' for r in records)):
                try:
                    record=launch_retry(store.root,report['plan_id'])
                    st.session_state['daily_refresh_request']=record['request_id']
                except (ValueError,OSError,KeyError):
                    st.error('原计划或参考批次校验失败，未启动重试。')
                else:
                    st.rerun()
        if st.button('刷新任务状态', key='daily_refresh_poll'):
            st.rerun()
    if records:
        with st.expander('最近更新记录'):
            st.dataframe([{'任务':r['request_id'], '状态':r['report']['status']} for r in records],
                hide_index=True, width='stretch')
    current = _current(store, 'free-a-daily')
    record_service_context(current)
    if current:
        st.caption(f"当前行情版 v{current['generation']} · {current['range']['start']} 至 {current['range']['end']}")
    st.caption('快照供行情浏览；公司行为与历史交易规则仍在核验。')


def render_data_service():
    record_service_context()
    update, coverage, sources, financial, etf, imports = st.tabs(
        ['更新', '覆盖与版本', '来源', '财务', 'ETF', '文件导入'], key='data_service_tab', on_change='rerun')
    if update.open:
        with update:
            _render_update(SnapshotStore(market_service_root()))
    if coverage.open:
        with coverage:
            from .data_coverage_view import render_coverage
            render_coverage(SnapshotStore(market_service_root()))
    if sources.open:
        with sources:
            render_provider_status()
    if financial.open:
        with financial:
            from .financial_view import render_financial_data
            render_financial_data()
    if etf.open:
        with etf:
            from .etf_view import render_etf_data
            render_etf_data()
    return imports if imports.open else None

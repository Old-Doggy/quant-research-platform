"""Capability inventory separates implemented adapters from live-verified access."""
import os


def provider_capabilities():
    configured = bool(os.environ.get('TUSHARE_TOKEN', '').strip())
    return [dict(provider='tushare', upstream='Tushare Pro', capability=capability,
        credential_status='configured' if configured else 'missing',
        access_status='not_probed' if configured else 'credentials_missing',
        implementation='adapter_ready', live_verified=False,
        source_url=url) for capability, url in [
            ('a_daily_raw', 'https://tushare.pro/document/2?doc_id=27'),
            ('instrument_master', 'https://tushare.pro/document/2?doc_id=25'),
            ('market_calendar', 'https://tushare.pro/document/2?doc_id=26'),
            ('adjustment_factors', 'https://tushare.pro/document/2?doc_id=28'),
            ('daily_basic', 'https://tushare.pro/document/2?doc_id=32')]]


def probe_tushare_permission(provider, capability):
    from .providers.base import ProviderError
    requests = {'a_daily_raw': ('daily', dict(ts_code='600000.SH', trade_date='20250102'), 'ts_code,trade_date'),
        'instrument_master': ('stock_basic', dict(ts_code='600000.SH'), 'ts_code'),
        'market_calendar': ('trade_cal', dict(exchange='SSE', start_date='20250102', end_date='20250102'), 'exchange,cal_date,is_open'),
        'adjustment_factors': ('adj_factor', dict(ts_code='600000.SH', trade_date='20250102'), 'ts_code,trade_date,adj_factor'),
        'daily_basic': ('daily_basic', dict(ts_code='600000.SH', trade_date='20250102'), 'ts_code,trade_date,pb')}
    if capability not in requests:
        raise ValueError('unknown provider capability')
    endpoint, params, fields = requests[capability]
    try:
        frame = provider.query(endpoint, params, fields=fields)
        return dict(capability=capability, status='available' if len(frame) else 'empty_response', rows=len(frame))
    except ProviderError as exc:
        return dict(capability=capability, status=exc.code, retryable=exc.retryable)

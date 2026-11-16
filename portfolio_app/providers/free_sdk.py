"""Optional SDK adapters; each upstream retains its own unit and failure contract."""
from importlib.util import find_spec
from importlib.metadata import version, PackageNotFoundError
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from threading import Lock
import time

import numpy as np
import pandas as pd

from .base import ProviderBatch, ProviderError
from ..data import normalise_market_frame, build_data_quality_report
from ..instrument_master import _date
from ..snapshot_contracts import identity_hash
from ..provider_normalize import source_previous_close, PREVIOUS_CLOSE_POLICY


_LOCKS = {name: Lock() for name in ('sina','eastmoney','baostock')}
_LAST = {name: 0. for name in _LOCKS}


def _sdk_frame(name, symbol, start, end):
    code, market = symbol.split('.')
    if name in {'sina','eastmoney'}:
        import akshare as ak
        if name == 'sina':
            return ak.stock_zh_a_hist_sina(symbol=market.lower()+code, start_date=start.replace('-',''),
                end_date=end.replace('-',''), adjust='')
        return ak.stock_zh_a_hist_em(symbol=code, period='daily', start_date=start.replace('-',''),
            end_date=end.replace('-',''), adjust='')
    import baostock as bs
    login = bs.login()
    if login.error_code != '0':
        raise ProviderError('login_failed', 'BaoStock登录失败')
    try:
        if name == 'baostock_master':
            result = bs.query_stock_basic(code=market.lower()+'.'+code)
        elif name == 'baostock_calendar':
            result = bs.query_trade_dates(start_date=start,end_date=end)
        else:
            result = bs.query_history_k_data_plus(market.lower()+'.'+code,
                'date,code,open,high,low,close,preclose,volume,amount,adjustflag,tradestatus',
                start_date=start, end_date=end, frequency='d', adjustflag='3')
        rows = []
        while result.error_code == '0' and result.next():
            rows.append(result.get_row_data())
        if result.error_code != '0':
            raise ProviderError('query_failed', 'BaoStock行情查询失败')
        return pd.DataFrame(rows, columns=result.fields)
    finally:
        bs.logout()


class FreeDailyProvider:
    def __init__(self, name, *, transport=None):
        if name not in _LOCKS:
            raise ValueError('未知免费上游')
        self.name, self._transport = name, transport

    def _fetch(self, symbol, start, end, *, operation=None):
        if operation is not None and (self.name != 'baostock' or operation not in {'baostock_master','baostock_calendar'}):
            raise ValueError('未知参考数据操作')
        if self._transport:
            try:
                return self._transport(symbol=symbol, start=start, end=end)
            except Exception:
                pass
            raise ProviderError('network_error', '免费行情连接失败', retryable=True)
        package = 'baostock' if self.name == 'baostock' else 'akshare'
        if find_spec(package) is None:
            raise ProviderError('dependency_missing', '尚未安装此来源的可选采集组件')
        with _LOCKS[self.name]:
            delay = 2. - (time.monotonic() - _LAST[self.name])
            if delay > 0:
                time.sleep(delay)
            try:
                with tempfile.TemporaryDirectory(prefix='quant-provider-') as directory:
                    output = Path(directory) / 'result.parquet'
                    command = [sys.executable, '-m', 'portfolio_app.providers.free_sdk', '--worker',
                               operation or self.name, symbol, start, end, str(output)]
                    try:
                        result = subprocess.run(command, capture_output=True, timeout=45,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                    except subprocess.TimeoutExpired:
                        raise ProviderError('network_timeout', '免费行情请求超时', retryable=True) from None
                    if result.returncode != 0 or not output.is_file():
                        status_path = output.with_suffix('.json')
                        status = json.loads(status_path.read_text(encoding='utf8')) if status_path.is_file() else {}
                        code = status.get('code', 'upstream_error')
                        raise ProviderError(code, '免费行情请求失败，请查看来源状态',
                            retryable=code in {'rate_limited','network_error','upstream_error'})
                    return pd.read_parquet(output)
            finally:
                _LAST[self.name] = time.monotonic()

    def daily(self, symbol, *, sessions):
        if not isinstance(symbol, str) or not re.fullmatch(r'(?:6\d{5}\.SH|[03]\d{5}\.SZ|[489]\d{5}\.BJ)', symbol):
            raise ValueError('免费日线只支持明确的A股代码')
        if self.name == 'baostock' and symbol.endswith('.BJ'):
            raise ProviderError('unsupported_market', 'BaoStock北交历史尚未验证')
        sessions = tuple(sessions)
        if not sessions or sessions != tuple(sorted(set(sessions))) or len(sessions) > 10000:
            raise ValueError('请提供有序、唯一且在预算内的真实交易日')
        for day in sessions:
            _date(day)
        raw = self._fetch(symbol, sessions[0], sessions[-1])
        if not isinstance(raw, pd.DataFrame):
            raise ProviderError('invalid_response', '免费源未返回表格数据')
        frame = raw.copy(deep=True)
        if self.name == 'eastmoney':
            frame = frame.rename(columns={'日期':'date','开盘':'open','最高':'high','最低':'low','收盘':'close',
                '成交量':'volume','成交额':'amount','股票代码':'code'})
            if 'code' in frame and not frame.code.astype(str).eq(symbol.split('.')[0]).all():
                raise ProviderError('invalid_response', '东方财富返回证券不符')
        if self.name == 'baostock':
            expected = symbol.split('.')[1].lower()+'.'+symbol.split('.')[0]
            if not {'code','adjustflag','tradestatus'} <= set(frame) or not frame.code.eq(expected).all() or not frame.adjustflag.astype(str).eq('3').all():
                raise ProviderError('invalid_response', 'BaoStock证券或原始价格口径不符')
        required = {'date','open','high','low','close','volume','amount'}
        if frame.empty and len(frame.columns) == 0:
            frame = pd.DataFrame(columns=sorted(required))
        if not required <= set(frame) or frame.columns.duplicated().any():
            raise ProviderError('invalid_response', '免费日线缺少必需字段或字段重复')
        labels = frame.date.astype(str)
        dates = pd.to_datetime(labels, format='%Y-%m-%d', errors='coerce')
        if dates.isna().any() or not dates.dt.strftime('%Y-%m-%d').eq(labels).all() or labels.duplicated().any():
            raise ProviderError('invalid_response', '免费日线日期无效或重复')
        frame = frame.loc[labels.isin(sessions)].copy()
        for field in ('open','high','low','close','volume','amount'):
            values = pd.to_numeric(frame[field], errors='coerce')
            if (frame[field].notna() & values.isna()).any() or (values.notna() & ~np.isfinite(values)).any():
                raise ProviderError('invalid_values', '免费日线数值无效')
            frame[field] = values
        frame['source_vol'], frame['source_amount'] = frame.volume.copy(), frame.amount.copy()
        frame['volume'] *= 100. if self.name == 'eastmoney' else 1.
        if not np.allclose(frame.volume.dropna(), frame.volume.dropna().round(), atol=1e-6, rtol=0):
            raise ProviderError('invalid_values', '免费日线数量不是整数股')
        positive = frame.volume.gt(0) & frame.amount.notna()
        average = frame.amount / frame.volume.where(frame.volume.gt(0))
        tolerance = np.maximum(.02, 1. / frame.volume.where(frame.volume.gt(0)))
        if (positive & ((average < frame.low-tolerance) | (average > frame.high+tolerance))).any():
            raise ProviderError('unit_mismatch', '免费日线量额单位与价格范围不符')
        if self.name == 'baostock' and not frame.tradestatus.astype(str).eq('1').all():
            raise ProviderError('nontrading_rows', 'BaoStock包含停牌估值行，须经状态对齐后单独接入')
        frame['trade_date'], frame['ts_code'] = frame.date, symbol
        try:
            frame['source_pre_close'] = source_previous_close(frame,
                'preclose' if self.name == 'baostock' else 'pre_close')
        except ValueError:
            raise ProviderError('invalid_values', '来源昨收无效') from None
        frame = frame.drop(columns='date')
        if not frame.empty:
            frame = normalise_market_frame(frame)
            frame['volume'] = frame.vol
            frame['pre_close'] = frame['source_pre_close']
            if build_data_quality_report(frame)['status'] != '通过':
                raise ProviderError('invalid_values', '免费日线质量检查未通过')
        missing = sorted(set(sessions)-set(frame.trade_date.dt.strftime('%Y-%m-%d') if not frame.empty else ()))
        batch_id = self.name+'-daily-'+identity_hash(dict(symbol=symbol,sessions=sessions,raw=raw.to_json(orient='split',date_format='iso')))
        frame.attrs['field_units'] = dict(price='CNY_per_share', volume='shares',amount='CNY',
            source_vol='lots_100_shares' if self.name=='eastmoney' else 'shares',source_amount='CNY')
        frame.attrs['normalization'] = dict(profile=self.name+'.sdk.raw',version='1.0',batch_id=batch_id)
        frame.attrs['previous_close_policy'] = PREVIOUS_CLOSE_POLICY
        frame.attrs['research_dataset'] = dict(dataset_id=self.name+'.a_daily_raw',version=batch_id,price_basis='raw',source_kind='provider')
        if 'return_contract' in frame.attrs:
            frame.attrs['return_contract']['price_basis']='raw'
        package = 'baostock' if self.name == 'baostock' else 'akshare'
        try:
            sdk_version = version(package)
        except PackageNotFoundError:
            sdk_version = 'not_installed'
        return ProviderBatch(frame,raw,dict(provider=self.name,upstream={'sina':'Sina Finance','eastmoney':'Eastmoney','baostock':'BaoStock'}[self.name],
            endpoint='raw_daily',batch_id=batch_id,symbol=symbol,requested_sessions=list(sessions),missing_sessions=missing,
            sdk_package=package,sdk_version=sdk_version,automatic_fallback=False,research_ready=False,
            live_coverage='unverified'), 'partial' if missing else 'complete')


if __name__ == '__main__' and len(sys.argv) == 7 and sys.argv[1] == '--worker':
    _, _, name, symbol, start, end, target = sys.argv
    try:
        _sdk_frame(name,symbol,start,end).to_parquet(target,index=False)
    except Exception as exc:
        code = 'rate_limited' if 'RateLimit' in type(exc).__name__ else 'upstream_error'
        Path(target).with_suffix('.json').write_text(json.dumps(dict(code=code)),encoding='utf8')
        raise SystemExit(1)

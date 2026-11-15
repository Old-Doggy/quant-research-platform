"""Source event conversion, without claiming verified historical event coverage."""
from dataclasses import asdict
import math
import re

import pandas as pd

from .base import ProviderBatch, ProviderError
from ..corporate_actions import CorporateAction, CorporateActionError, normalize_actions
from ..instrument_master import _date
from ..snapshot_contracts import identity_hash


DIVIDEND_FIELDS = ('ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,'
                   'cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,imp_ann_date')


def _stock(code):
    if not isinstance(code, str) or not re.fullmatch(r'(?:[06]\d{5}\.SH|[03]\d{5}\.SZ|[489]\d{5}\.BJ)', code):
        raise ValueError('事件适配器只支持已识别的A股代码')


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{8}', value):
        raise ProviderError('invalid_event', '公司行为必需日期缺失或格式无效')
    parsed = pd.to_datetime(value, format='%Y%m%d', errors='coerce')
    if pd.isna(parsed):
        raise ProviderError('invalid_event', '公司行为日期无效')
    return parsed.strftime('%Y-%m-%d')


def _amount(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        number = float('nan')
    if isinstance(value, bool) or not math.isfinite(number) or number < 0:
        raise ProviderError('invalid_event', '公司行为金额或比例缺失、无效')
    return number


class TushareEvents:
    def __init__(self, provider):
        self.provider = provider

    def dividends(self, symbol):
        _stock(symbol)
        raw = self.provider.query('dividend', dict(ts_code=symbol), fields=DIVIDEND_FIELDS)
        if len(raw) >= min(2000, self.provider.row_limit):
            raise ProviderError('truncated_response', '分红历史达到单次上限，不能登记事件完整')
        if not set(DIVIDEND_FIELDS.split(',')) <= set(raw) or not raw.ts_code.eq(symbol).all():
            raise ProviderError('invalid_response', '分红响应缺少字段或证券不符')
        if raw.div_proc.isna().any() or not raw.div_proc.astype(str).str.len().gt(0).all():
            raise ProviderError('invalid_event', '分红实施状态缺失')
        implemented = raw.loc[raw.div_proc.eq('实施')].copy()
        if implemented.duplicated(['ts_code', 'ex_date']).any():
            raise ProviderError('conflicting_events', '同一除权日存在多个实施版本，需先核对更正关系')
        actions = []
        for row in implemented.to_dict('records'):
            cash, bonus = _amount(row['cash_div_tax']), _amount(row['stk_div'])
            detail = [row['stk_bo_rate'], row['stk_co_rate']]
            if all(pd.notna(v) for v in detail) and not math.isclose(sum(_amount(v) for v in detail), bonus, abs_tol=1e-8):
                raise ProviderError('invalid_event', '每股送转与送股、转增明细不一致')
            if not (cash or bonus):
                continue
            record, ex, announced = (_day(row[k]) for k in ('record_date', 'ex_date', 'imp_ann_date'))
            if announced > record:
                raise ProviderError('invalid_event', '分红实施公告晚于登记日，需核对版本')
            # Content identity changes on correction; selecting active revisions is a store concern.
            content = {k: None if pd.isna(v) else v for k, v in row.items()}
            identity = 'tushare-dividend-' + identity_hash(content)
            common = dict(symbol=symbol, record_date=record, ex_date=ex,
                          source='https://tushare.pro/document/2?doc_id=103')
            try:
                if cash:
                    actions.append(CorporateAction(**common, action_id=identity + '-cash',
                        action_type='cash_dividend', pay_date=_day(row['pay_date']), cash_per_share=cash, tax_basis='gross'))
                if bonus:
                    actions.append(CorporateAction(**common, action_id=identity + '-shares',
                        action_type='bonus_share', listing_date=_day(row['div_listdate']), share_multiplier=1 + bonus))
            except CorporateActionError as exc:
                raise ProviderError('invalid_event', '公司行为日期或权益关系无效') from exc
        try:
            actions = [asdict(a) for a in normalize_actions(actions)]
        except CorporateActionError as exc:
            raise ProviderError('conflicting_events', '分红包含重复或冲突版本，请核对原始批次') from exc
        batch_id = 'tushare-dividends-' + identity_hash(dict(symbol=symbol, raw=raw.to_json(orient='split')))
        return ProviderBatch(implemented, raw, dict(provider='tushare', endpoint='dividend', batch_id=batch_id,
            symbol=symbol, corporate_actions=actions, event_coverage='unverified',
            source_url='https://tushare.pro/document/2?doc_id=103', update_window='20:00–21:00 Asia/Shanghai',
            revision_resolution='not_automatic', tax_basis='gross'), 'unverified')

    def suspensions(self, session, *, expected_symbols):
        _date(session)
        expected = set(expected_symbols)
        if not expected:
            raise ValueError('停复牌查询需要明确证券范围')
        for symbol in expected:
            _stock(symbol)
        params = dict(trade_date=session.replace('-', ''))
        fields = 'ts_code,trade_date,suspend_type,suspend_timing'
        cap = min(5000, self.provider.row_limit)
        raw = self.provider.query('suspend_d', params, fields=fields)
        if len(raw) >= cap:
            parts = []
            for symbol in sorted(expected):
                part = self.provider.query('suspend_d', {**params, 'ts_code': symbol}, fields=fields)
                if len(part) >= cap or 'ts_code' not in part or not part.ts_code.eq(symbol).all():
                    raise ProviderError('truncated_response', '停复牌证券分片达到上限或证券不符')
                parts.append(part)
            raw = pd.concat(parts, ignore_index=True)
        if (not set(fields.split(',')) <= set(raw)
                or not raw.trade_date.astype(str).eq(params['trade_date']).all()
                or not raw.suspend_type.isin({'S', 'R'}).all()
                or raw.duplicated(fields.split(',')).any()):
            raise ProviderError('invalid_response', '停复牌字段、日期、状态无效或记录重复')
        frame = raw.loc[raw.ts_code.isin(expected)].copy()
        full = frame.suspend_timing.isna() | frame.suspend_timing.astype(str).str.strip().eq('')
        suspended = set(frame.loc[frame.suspend_type.eq('S') & full, 'ts_code'])
        intraday = set(frame.loc[frame.suspend_type.eq('S') & ~full, 'ts_code'])
        resumed = set(frame.loc[frame.suspend_type.eq('R'), 'ts_code'])
        if suspended & (intraday | resumed):
            raise ProviderError('status_conflict', '同一证券全天停牌与日内停牌或复牌冲突')
        batch_id = 'tushare-suspensions-' + identity_hash(dict(session=session, raw=raw.to_json(orient='split')))
        return ProviderBatch(frame, raw, dict(provider='tushare', endpoint='suspend_d', batch_id=batch_id,
            session=session, suspended_symbols=sorted(suspended), intraday_symbols=sorted(intraday),
            resumed_symbols=sorted(resumed), status_coverage='unverified',
            source_url='https://tushare.pro/document/2?doc_id=214', update_window='irregular'), 'unverified')

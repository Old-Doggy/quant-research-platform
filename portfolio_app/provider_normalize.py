"""Normalize declared raw daily units once; retain the supplied original fields."""
import numpy as np
import pandas as pd

from .data import normalise_market_frame, build_data_quality_report
from .field_registry import daily_profile


PREVIOUS_CLOSE_POLICY = 'explicit_source_only.v1'


def source_previous_close(frame, field='pre_close'):
    """Validate upstream quotes before the legacy normalizer can fill/coerce them."""
    if field not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    raw = frame[field]
    numeric = pd.to_numeric(raw, errors='coerce')
    if (raw.map(lambda value: isinstance(value, (bool, np.bool_))).any()
            or (raw.notna() & numeric.isna()).any() or np.isinf(numeric).any()
            or numeric.dropna().le(0).any()):
        raise ValueError('来源昨收必须为正数；缺失不能用上一条收盘替代')
    return numeric.astype(float)


def normalize_daily(raw, *, profile, batch_id):
    contract = daily_profile(profile)
    if raw.attrs.get('normalization'):
        raise ValueError('数据已经归一，不能重复转换单位')
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError('数据批次缺少身份')
    required = {'ts_code', 'trade_date', 'open', 'high', 'low', 'close', contract.volume_field, contract.amount_field}
    if not required <= set(raw) or raw.empty:
        raise ValueError('日线来源缺少必需字段或为空')
    codes = raw.ts_code.astype(str)
    # The adapter accepts the A-share stock endpoint only, never bonds or funds.
    valid_codes = codes.str.match(r'^(?:[06]\d{5}\.SH|[03]\d{5}\.SZ|[489]\d{5}\.BJ)$')
    if not valid_codes.all():
        raise ValueError('A股日线profile不能用于未知证券或非股票')
    dates = pd.to_datetime(raw.trade_date.astype(str), format='%Y%m%d', errors='coerce')
    if dates.isna().any() or pd.DataFrame(dict(code=codes, day=dates)).duplicated().any():
        raise ValueError('日线日期无效或重复')
    frame = raw.copy(deep=True)
    frame['source_pre_close'] = source_previous_close(raw)
    for field, multiplier, label in [(contract.volume_field, contract.volume_multiplier, '成交量'),
                                     (contract.amount_field, contract.amount_multiplier, '成交额')]:
        values = pd.to_numeric(raw[field], errors='coerce')
        if (raw[field].notna() & values.isna()).any() or (values.notna() & (~np.isfinite(values) | values.lt(0))).any():
            raise ValueError(label + '无效；缺失不能转为0')
        frame[field] = values * multiplier
        if field == contract.volume_field and not np.allclose(frame[field].dropna(), frame[field].dropna().round(), atol=1e-6, rtol=0):
            raise ValueError('成交量归一后必须为整数股')
    frame = normalise_market_frame(frame)
    frame['pre_close'] = frame['source_pre_close']
    frame.attrs['previous_close_policy'] = PREVIOUS_CLOSE_POLICY
    # Match originals by key after the canonical sort, never by incoming row order.
    indexed = raw.assign(_date=dates).set_index(['ts_code', '_date'])
    keys = pd.MultiIndex.from_arrays([frame.ts_code, frame.trade_date])
    frame['source_vol'] = pd.to_numeric(indexed[contract.volume_field], errors='coerce').reindex(keys).to_numpy()
    frame['source_amount'] = pd.to_numeric(indexed[contract.amount_field], errors='coerce').reindex(keys).to_numpy()
    frame['volume'] = frame['vol']
    if build_data_quality_report(frame)['status'] != '通过':
        raise ValueError('归一日线质量检查未通过')
    frame.attrs['field_units'] = dict(price='CNY_per_share', volume='shares', amount='CNY',
        source_vol=contract.volume_unit, source_amount=contract.amount_unit)
    frame.attrs['normalization'] = dict(profile=profile, version='1.0', batch_id=batch_id,
        source_url=contract.source_url, missing_policy='preserve_missing')
    frame.attrs['research_dataset'] = dict(dataset_id=contract.provider + '.' + contract.endpoint,
        version=batch_id, source_kind='provider', price_basis='raw')
    frame.attrs['return_contract']['price_basis'] = 'raw'
    return frame

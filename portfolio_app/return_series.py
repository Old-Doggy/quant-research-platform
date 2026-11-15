"""Price changes and gross total returns have separate, versioned meanings."""
import numpy as np
import pandas as pd


class ReturnContractError(ValueError):
    pass


def inferred_price_basis(frame):
    return frame.attrs.get('research_dataset', {}).get('price_basis',
        frame.attrs.get('research_timing', {}).get('price_mode', 'unspecified'))


def require_raw_execution_prices(frame):
    if inferred_price_basis(frame) not in {'raw', 'raw_ohlcv', 'synthetic', 'unspecified', 'unknown'}:
        raise ReturnContractError('资金账本成交需要原始价格；请在数据中心选择未复权数据。')


def require_action_free_proxy(frame):
    """Old exposure proxies cannot book dividend receivables or bonus shares."""
    active = False
    for name, neutral in (('cash_dividend_per_share', 0.), ('share_multiplier', 1.)):
        if name in frame:
            values = pd.to_numeric(frame[name], errors='coerce')
            active |= bool(values.notna().any() and values.dropna().ne(neutral).any())
    if active or frame.attrs.get('corporate_actions'):
        raise ReturnContractError('所选区间存在公司行为，请使用支持事件处理的资金账本；当前收益代理不能计算该区间。')


def build_return_series(frame, *, definition='price_return_v1', price_basis=None, action_coverage=None):
    if definition not in {'price_return_v1', 'total_return_v1'}:
        raise ReturnContractError('未知研究收益定义')
    if not {'trade_date', 'close'} <= set(frame):
        raise ReturnContractError('研究收益缺少日期或收盘价')
    basis = price_basis or inferred_price_basis(frame)
    close = pd.to_numeric(frame.close, errors='coerce')
    if ((close.notna()) & (~np.isfinite(close) | close.le(0))).any():
        raise ReturnContractError('收益价格必须为正且有限；缺失值保持缺失')
    keys = frame['symbol'] if 'symbol' in frame else pd.Series('', index=frame.index)
    dates = pd.to_datetime(frame.trade_date, errors='coerce')
    if dates.isna().any() or pd.DataFrame(dict(symbol=keys, date=dates)).duplicated().any():
        raise ReturnContractError('研究收益日期无效或证券日期重复')
    if any(not group.is_monotonic_increasing for _, group in dates.groupby(keys, sort=False)):
        raise ReturnContractError('研究收益需要按证券日期排序')
    previous = close.groupby(keys, sort=False).shift(1)
    if definition == 'total_return_v1':
        if basis not in {'raw', 'raw_ohlcv', 'synthetic', 'unspecified', 'unknown'}:
            raise ReturnContractError('含公司行为的总收益需要原始价格，不能重复计入复权调整')
        if action_coverage != 'complete' or not {'cash_dividend_per_share', 'share_multiplier'} <= set(frame):
            raise ReturnContractError('公司行为覆盖不完整，无法计算总收益')
        cash = pd.to_numeric(frame.cash_dividend_per_share, errors='coerce')
        shares = pd.to_numeric(frame.share_multiplier, errors='coerce')
        if cash.isna().any() or shares.isna().any() or not np.isfinite(cash).all() or not np.isfinite(shares).all() or (cash < 0).any() or (shares <= 0).any():
            raise ReturnContractError('公司行为数量或金额无效')
        # Dividend is quoted per pre-event share; multiplier includes old shares.
        result = (close * shares + cash) / previous - 1
    else:
        result = close / previous - 1
    result.name = 'return'
    result.attrs['return_contract'] = dict(definition=definition, price_basis=basis,
        version='1.0', tax='gross_before_tax' if definition == 'total_return_v1' else 'not_applied',
        action_coverage=action_coverage or 'unknown', first_observation='missing')
    return result

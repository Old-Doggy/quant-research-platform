"""Dated company actions; unsupported events fail before a run is committed."""
from dataclasses import dataclass
from datetime import date
import math
from numbers import Real


class CorporateActionError(ValueError):
    pass


@dataclass(frozen=True)
class CorporateAction:
    action_id: str
    action_type: str
    symbol: str
    record_date: str
    ex_date: str
    pay_date: str
    cash_per_share: float
    source: str
    tax_basis: str

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip() or value != value.strip()
               for value in (self.action_id, self.symbol, self.source)):
            raise CorporateActionError('公司行为缺少事件ID、证券或来源')
        if self.action_type != 'cash_dividend':
            raise CorporateActionError(f'未支持的公司行为：{self.action_type}')
        try:
            for value in (self.record_date, self.ex_date, self.pay_date):
                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError('noncanonical date')
        except (ValueError, TypeError) as exc:
            raise CorporateActionError('公司行为日期必须为ISO日期') from exc
        if not self.record_date < self.ex_date <= self.pay_date:
            raise CorporateActionError('公司行为登记、除息和支付日期顺序无效')
        if self.tax_basis != 'gross':
            raise CorporateActionError('tax_basis只支持gross；尚未实现持有期分红税')
        if (isinstance(self.cash_per_share, bool) or not isinstance(self.cash_per_share, Real)
                or not math.isfinite(self.cash_per_share) or self.cash_per_share < 0):
            raise CorporateActionError('每股现金金额无效')


def normalize_actions(actions):
    result, seen = [], set()
    for raw in actions:
        try:
            action = raw if isinstance(raw, CorporateAction) else CorporateAction(**raw)
        except TypeError as exc:
            raise CorporateActionError('公司行为字段不完整或包含未知字段') from exc
        if action.action_id in seen:
            raise CorporateActionError('公司行为ID重复；更正事件需要新的数据快照')
        seen.add(action.action_id)
        result.append(action)
    return tuple(sorted(result, key=lambda item: (item.ex_date, item.action_id)))


def resolve_frame_actions(frames, explicit=()):
    """Merge dated declarations and reject price-row events lacking a ledger event."""
    import pandas as pd

    merged = {action.action_id: action for action in normalize_actions(explicit)}
    if any(action.symbol not in frames for action in merged.values()):
        raise CorporateActionError('公司行为证券不在研究范围')
    for frame in frames.values():
        for action in normalize_actions(frame.attrs.get('corporate_actions', ())):
            if action.symbol not in frames:
                continue  # A sliced multi-security input may retain the full event metadata.
            if action.action_id in merged and merged[action.action_id] != action:
                raise CorporateActionError('公司行为事件内容冲突；请核对数据版本')
            merged[action.action_id] = action
    actions = normalize_actions(merged.values())
    for symbol, frame in frames.items():
        for field, neutral in (('cash_dividend_per_share', 0.), ('share_multiplier', 1.)):
            if field not in frame:
                continue
            numbers = pd.to_numeric(frame[field], errors='coerce')
            if numbers.isna().any() or not numbers.map(math.isfinite).all():
                raise CorporateActionError('公司行为字段缺失或无效')
            for index in frame.index[numbers.ne(neutral)]:
                session = pd.Timestamp(frame.loc[index, 'trade_date']).strftime('%Y-%m-%d')
                matching = [a for a in actions if a.symbol == symbol and a.ex_date == session]
                expected = sum(a.cash_per_share for a in matching) if field == 'cash_dividend_per_share' else 1.
                if not matching or not math.isclose(float(numbers.loc[index]), expected, abs_tol=1e-12):
                    raise CorporateActionError('价格行的公司行为未被事件账本覆盖或金额不一致')
    return actions

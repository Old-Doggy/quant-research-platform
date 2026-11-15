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
    source: str
    pay_date: str | None = None
    cash_per_share: float = 0.
    tax_basis: str | None = None
    share_multiplier: float = 1.
    listing_date: str | None = None
    supersedes: str | None = None

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip() or value != value.strip()
               for value in (self.action_id, self.symbol, self.source)):
            raise CorporateActionError('公司行为缺少事件ID、证券或来源')
        if self.action_type not in {'cash_dividend', 'bonus_share', 'split'}:
            raise CorporateActionError(f'未支持的公司行为：{self.action_type}')
        try:
            for value in (self.record_date, self.ex_date, *([self.pay_date] if self.action_type == 'cash_dividend'
                                                          else [self.listing_date])):
                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError('noncanonical date')
        except (ValueError, TypeError) as exc:
            raise CorporateActionError('公司行为日期必须为ISO日期') from exc
        settlement = self.pay_date if self.action_type == 'cash_dividend' else self.listing_date
        if not self.record_date < self.ex_date <= settlement:
            raise CorporateActionError('公司行为登记、除息和支付日期顺序无效')
        if self.action_type == 'cash_dividend' and self.tax_basis != 'gross':
            raise CorporateActionError('tax_basis只支持gross；尚未实现持有期分红税')
        if self.action_type != 'cash_dividend' and self.tax_basis is not None:
            raise CorporateActionError('股份事件税费需另行核算，不能声明现金股息税口径')
        if (isinstance(self.cash_per_share, bool) or not isinstance(self.cash_per_share, Real)
                or not math.isfinite(self.cash_per_share) or self.cash_per_share < 0):
            raise CorporateActionError('每股现金金额无效')
        if (isinstance(self.share_multiplier, bool) or not isinstance(self.share_multiplier, Real)
                or not math.isfinite(self.share_multiplier) or self.share_multiplier <= 0):
            raise CorporateActionError('股份变动比例无效')
        if self.action_type == 'cash_dividend' and (self.share_multiplier != 1 or self.listing_date is not None):
            raise CorporateActionError('现金分红不能混入股份变动；请分别声明事件')
        if self.action_type != 'cash_dividend' and (self.cash_per_share != 0 or self.pay_date is not None):
            raise CorporateActionError('股份事件不能混入现金金额或到账日期')
        if self.action_type == 'bonus_share' and self.share_multiplier <= 1:
            raise CorporateActionError('送股比例必须大于1')
        if self.supersedes is not None and (not isinstance(self.supersedes, str) or not self.supersedes.strip()
                                           or self.supersedes == self.action_id):
            raise CorporateActionError('更正关系无效')


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
    if any(a.supersedes in seen for a in result if a.supersedes):
        raise CorporateActionError('更正前后事件不能混在同一数据快照')
    share_keys = [(a.symbol, a.ex_date) for a in result if a.action_type != 'cash_dividend']
    if len(share_keys) != len(set(share_keys)):
        raise CorporateActionError('同日多项股份事件需要合并为经核验的股份比例')
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
                expected = (sum(a.cash_per_share for a in matching) if field == 'cash_dividend_per_share'
                            else math.prod(a.share_multiplier for a in matching))
                if not matching or not math.isclose(float(numbers.loc[index]), expected, abs_tol=1e-12):
                    raise CorporateActionError('价格行的公司行为未被事件账本覆盖或金额不一致')
    return actions

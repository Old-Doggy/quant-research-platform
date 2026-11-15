"""Instrument/session rules supplied with evidence; no guessed ETF category."""
from dataclasses import asdict, dataclass
from datetime import date
import math

from .offline_market_rules import AssetRule
from .research_manifest import semantic_hash


class InstrumentRuleError(ValueError):
    pass


@dataclass(frozen=True)
class InstrumentRule:
    rule_id: str
    symbol: str
    market: str
    asset_type: str
    subtype: str
    effective_from: str
    effective_to: str
    lot_size: int
    t_plus_one: bool
    tick_size: float
    limit_ratio: float | None
    sell_tax_bps: float
    source: str
    status: str

    def __post_init__(self):
        for field in ('rule_id', 'symbol', 'subtype', 'source'):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise InstrumentRuleError('证券规则缺少身份、类别或依据')
        if self.market not in {'SSE', 'SZSE', 'BSE', 'HKEX', 'US', 'SYNTHETIC'}:
            raise InstrumentRuleError('证券规则市场未知')
        if self.status not in {'supported', 'unsupported', 'unverified'}:
            raise InstrumentRuleError('证券规则支持状态无效')
        try:
            for value in (self.effective_from, self.effective_to):
                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError('date')
        except (ValueError, TypeError) as exc:
            raise InstrumentRuleError('证券规则日期无效') from exc
        if self.effective_to < self.effective_from:
            raise InstrumentRuleError('证券规则有效期倒置')
        self.asset_rule()
        values = (self.tick_size, self.sell_tax_bps, *([] if self.limit_ratio is None else [self.limit_ratio]))
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in values):
            raise InstrumentRuleError('证券规则价格或税率无效')
        if self.tick_size <= 0 or self.sell_tax_bps < 0 or (self.limit_ratio is not None and not 0 < self.limit_ratio <= 1):
            raise InstrumentRuleError('证券规则价格或税率超出范围')
        if self.asset_type == 'etf':
            known = {'stock_etf', 'bond_etf', 'money_etf', 'gold_etf', 'commodity_etf',
                     'cross_border_t0_etf', 'cross_border_t1_etf'}
            if self.subtype not in known:
                raise InstrumentRuleError('ETF类别未识别；需要证券级规则依据')
            if self.t_plus_one != (self.subtype in {'stock_etf', 'cross_border_t1_etf'}):
                raise InstrumentRuleError('ETF类别与T+1规则不一致')
        if self.asset_type == 'cn_stock' and not self.t_plus_one:
            raise InstrumentRuleError('A股规则需要T+1约束')
        if self.asset_type == 'cn_stock' and self.subtype not in {'main_a', 'star_a', 'chinext_a', 'bse_a'}:
            raise InstrumentRuleError('A股类别未知，不能套用主板规则')
        allowed_markets = {'cn_stock': {'SSE', 'SZSE', 'BSE'}, 'etf': {'SSE', 'SZSE'},
                           'us_stock': {'US'}, 'hk_stock': {'HKEX'}}
        if self.market != 'SYNTHETIC' and self.market not in allowed_markets[self.asset_type]:
            raise InstrumentRuleError('证券市场与资产类别不一致')

    def asset_rule(self):
        return AssetRule(self.asset_type, self.lot_size, self.t_plus_one, self.sell_tax_bps)


class InstrumentRuleTable:
    def __init__(self, rows):
        try:
            rules = tuple(r if isinstance(r, InstrumentRule) else InstrumentRule(**r) for r in rows)
        except TypeError as exc:
            raise InstrumentRuleError('证券规则字段不完整或未知') from exc
        self.rules = tuple(sorted(rules, key=lambda r: (r.symbol, r.effective_from, r.rule_id)))
        if len({r.rule_id for r in self.rules}) != len(self.rules):
            raise InstrumentRuleError('证券规则ID重复')
        for before, after in zip(self.rules, self.rules[1:]):
            if before.symbol == after.symbol and after.effective_from <= before.effective_to:
                raise InstrumentRuleError('证券规则有效期重叠')

    def resolve(self, symbol, session):
        matches = [r for r in self.rules if r.symbol == symbol and r.effective_from <= session <= r.effective_to]
        if len(matches) != 1:
            raise InstrumentRuleError(f'{symbol}在{session}缺少唯一有效证券规则')
        if matches[0].status != 'supported':
            raise InstrumentRuleError(f'{symbol}在{session}的证券规则尚未支持或核验')
        return matches[0]

    def to_dicts(self):
        return [asdict(r) for r in self.rules]

    @property
    def fingerprint(self):
        return semantic_hash(self.to_dicts())


def resolve_rule_table(frames, explicit=None):
    if explicit is not None:
        return InstrumentRuleTable(explicit)
    merged = {}
    for frame in frames.values():
        for rule in InstrumentRuleTable(frame.attrs.get('instrument_rules', ())).rules:
            if rule.symbol not in frames:
                continue
            if rule.rule_id in merged and rule != merged[rule.rule_id]:
                raise InstrumentRuleError('证券规则版本冲突')
            merged[rule.rule_id] = rule
    return InstrumentRuleTable(merged.values()) if merged else None

"""Provider-specific unit contracts backed by the named endpoint's documentation."""
from dataclasses import dataclass


@dataclass(frozen=True)
class DailyFieldProfile:
    profile_id: str
    provider: str
    endpoint: str
    volume_field: str
    volume_unit: str
    volume_multiplier: float
    amount_field: str
    amount_unit: str
    amount_multiplier: float
    source_url: str


DAILY_PROFILES = {
    'tushare_a_daily': DailyFieldProfile('tushare_a_daily', 'tushare', 'daily',
        'vol', 'lots_100_shares', 100., 'amount', 'thousand_CNY', 1000.,
        'https://tushare.pro/document/2?doc_id=27'),
}


def daily_profile(name):
    if name not in DAILY_PROFILES:
        raise ValueError('未知来源profile；不能猜测成交量和金额单位')
    return DAILY_PROFILES[name]


# field -> (source unit, canonical unit, multiplier). Tushare doc_id=32.
TUSHARE_BASIC_FIELDS = {
    'close': ('CNY_per_share', 'CNY_per_share', 1.),
    'turnover_rate': ('percent', 'fraction', .01),
    'turnover_rate_f': ('percent', 'fraction', .01),
    'volume_ratio': ('ratio', 'ratio', 1.),
    'pe': ('ratio', 'ratio', 1.), 'pe_ttm': ('ratio', 'ratio', 1.),
    'pb': ('ratio', 'ratio', 1.), 'ps': ('ratio', 'ratio', 1.), 'ps_ttm': ('ratio', 'ratio', 1.),
    'dv_ratio': ('percent', 'fraction', .01), 'dv_ttm': ('percent', 'fraction', .01),
    'total_share': ('ten_thousand_shares', 'shares', 10000.),
    'float_share': ('ten_thousand_shares', 'shares', 10000.),
    'free_share': ('ten_thousand_shares', 'shares', 10000.),
    'total_mv': ('ten_thousand_CNY', 'CNY', 10000.),
    'circ_mv': ('ten_thousand_CNY', 'CNY', 10000.),
}

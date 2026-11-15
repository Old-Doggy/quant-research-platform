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

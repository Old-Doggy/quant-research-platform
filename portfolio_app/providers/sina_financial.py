"""Sina latest-observed consolidated statements; never a historical PIT archive."""
from datetime import datetime
import json
import math
import re
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import pandas as pd

from .base import ProviderBatch
from ..instrument_master import _date
from ..snapshot_contracts import identity_hash


URL = 'https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022'
FIELDS = {
    'income': ('lrb', {'BIZINCO': 'revenue', 'NETPROFIT': 'n_income',
        'NETPARECOMPPROF': 'n_income_attr_p', 'PARENETP': 'n_income_attr_p', 'BASICEPS': 'basic_eps'}),
    'balancesheet': ('fzb', {'TOTASSET': 'total_assets', 'TOTLIAB': 'total_liab',
        'PARECOMPSHARRIGHT': 'total_hldr_eqy_exc_min_int', 'PARESHARRIGH': 'total_hldr_eqy_exc_min_int'}),
    'cashflow': ('llb', {'MANANETR': 'n_cashflow_act', 'INVNETCASHFLOW': 'n_cashflow_inv_act',
        'FINNETCFLOW': 'n_cash_flows_fnc_act'}),
}


def _request(**params):
    with urlopen(URL + '?' + urlencode(params), timeout=20) as response:
        # A bounded response guards against a changed endpoint returning a bulk archive.
        body = response.read(16*1024*1024+1)
    if len(body)>16*1024*1024:
        raise ValueError('财务来源响应超出预算')
    return json.loads(body)


def _day(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{8}',value):
        raise ValueError('财务来源日期无效')
    return _date(value[:4]+'-'+value[4:6]+'-'+value[6:])


class SinaFinancial:
    def __init__(self, *, transport=None):
        self.transport=transport or _request

    def reports(self, endpoint, symbol, *, periods, fetched_at=None):
        if endpoint not in FIELDS or not isinstance(symbol,str) or not re.fullmatch(r'(?:6\d{5}\.SH|[03]\d{5}\.SZ)',symbol):
            raise ValueError('新浪财务仅支持明确沪深A股和三张报表')
        if not isinstance(periods,(list,tuple)) or not 1<=len(periods)<=40 or len(set(periods))!=len(periods):
            raise ValueError('请选择1至40个不重复的季度末')
        for period in periods:
            _date(period)
            if period[5:] not in {'03-31','06-30','09-30','12-31'}:
                raise ValueError('报告期需要季度末')
        instant=datetime.now(ZoneInfo('Asia/Shanghai')) if fetched_at is None else datetime.fromisoformat(fetched_at)
        if instant.tzinfo is None:
            raise ValueError('财务抓取时间需要时区')
        fetched=instant.astimezone(ZoneInfo('Asia/Shanghai')).isoformat()
        source,mapping=FIELDS[endpoint]
        payload=self.transport(paperCode=symbol[-2:].lower()+symbol[:6],source=source,type='0',page='1',num='1000')
        try:
            data=payload['result']['data']
            count=int(data['report_count'])
            dates=[row['date_value'] for row in data['report_date']]
            reports=data['report_list']
        except (KeyError,TypeError,ValueError):
            raise ValueError('新浪财务响应结构改变') from None
        if count>=1000 or count!=len(dates) or len(set(dates))!=len(dates) or set(dates)!=set(reports):
            raise ValueError('新浪报表日期或条数不完整，未登记为完整')
        rows=[];missing=[]
        for period in sorted(periods):
            record=reports.get(period.replace('-',''))
            if record is None:
                missing.append(period)
                continue
            ann=_day(record['publish_date'])
            if ann<period or ann>instant.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat():
                raise ValueError('财务公告日期与报告期或抓取时间矛盾')
            if record['rCurrency']!='CNY' or record['rType']!='合并期末':
                raise ValueError('财务币种或报表类型未经验证')
            if record.get('data_source')!='定期报告':
                raise ValueError('财务数据不是定期报告')
            items={}
            for item in record['data']:
                field=item['item_field']
                if field not in mapping:
                    continue
                if field in items:
                    raise ValueError('财务源字段重复')
                value=item['item_value']
                if value in (None,'','--'):
                    items[field]=None
                else:
                    if isinstance(value,bool):
                        raise ValueError('财务金额类型无效')
                    number=float(value)
                    if not math.isfinite(number):
                        raise ValueError('财务金额不是有限值')
                    items[field]=number
            values={target:None for target in mapping.values()}
            for field,value in items.items():
                target=mapping[field]
                if values[target] is not None and value is not None and values[target]!=value:
                    raise ValueError('财务同义字段数值冲突')
                if value is not None:
                    values[target]=value
            row=dict(symbol=symbol,endpoint=endpoint,period=period,ann_date=ann,f_ann_date=None,
                report_type='1',update_flag='unknown',fetched_at=fetched,**values)
            row['report_version']='financial-'+identity_hash({k:v for k,v in row.items() if k!='fetched_at'})
            rows.append(row)
        raw=pd.DataFrame([dict(payload_json=json.dumps(payload,ensure_ascii=False,allow_nan=False))])
        fields={target:('CNY_per_share' if target=='basic_eps' else 'CNY') for target in mapping.values()}
        metadata=dict(provider='sina',endpoint=endpoint,symbol=symbol,periods=sorted(periods),
            missing_periods=missing,fetched_at=fetched,source_url=URL,
            batch_id='sina-financial-'+identity_hash(dict(endpoint=endpoint,symbol=symbol,fetched_at=fetched,payload=payload)),
            pit_coverage='forward_observation_only',unit_policy='sina_api_cny.v1',field_units=fields,
            unit_evidence='sina-web-wan-CNY-to-API-1e4; selected real cases 2026-11-16',
            source_revision_archive=False,automatic_fallback=False)
        return ProviderBatch(pd.DataFrame(rows),raw,metadata,'partial' if missing else 'complete')

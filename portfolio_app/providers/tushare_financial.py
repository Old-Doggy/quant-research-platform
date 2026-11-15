"""Single-security, explicit-period financial acquisition; never claims full PIT."""
from datetime import datetime
import re
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .base import ProviderBatch, ProviderError
from ..instrument_master import _date
from ..snapshot_contracts import identity_hash


FINANCIAL_PROFILES = {
    'income': dict(doc=33, fields=('total_revenue','revenue','n_income','n_income_attr_p','basic_eps')),
    'balancesheet': dict(doc=36, fields=('total_assets','total_liab','total_hldr_eqy_exc_min_int','total_share')),
    'cashflow': dict(doc=44, fields=('n_cashflow_act','n_cashflow_inv_act','n_cash_flows_fnc_act','c_cash_equ_end_period')),
    'fina_indicator': dict(doc=79, fields=('roe','roa','eps','dt_eps','profit_dedt')),
}


def _source_date(value, *, required=False):
    if pd.isna(value) or str(value).strip()=='':
        if required:
            raise ProviderError('invalid_response','财务记录缺少必需日期')
        return None
    value=str(value)
    if not re.fullmatch(r'\d{8}',value):
        raise ProviderError('invalid_response','财务来源日期格式无效')
    try:
        return _date(value[:4]+'-'+value[4:6]+'-'+value[6:])
    except ValueError as exc:
        raise ProviderError('invalid_response','财务来源日期无效') from exc


class TushareFinancial:
    def __init__(self, provider, *, row_limit=100):
        if type(row_limit) is not int or row_limit<2:
            raise ValueError('财务接口行数边界无效')
        self.provider,self.row_limit=provider,row_limit

    def reports(self, endpoint, symbol, *, periods, fetched_at=None):
        if endpoint not in FINANCIAL_PROFILES or not isinstance(symbol,str) or not re.fullmatch(r'\d{6}\.(?:SH|SZ|BJ)',symbol):
            raise ValueError('财务接口或证券无效')
        if not isinstance(periods,(list,tuple)) or not 1<=len(periods)<=80 or len(periods)!=len(set(periods)):
            raise ValueError('请选择1至80个不重复的明确报告期')
        for period in periods:
            _date(period)
            if period[5:] not in {'03-31','06-30','09-30','12-31'}:
                raise ValueError('财务报告期必须为季度末')
        instant=datetime.now(ZoneInfo('Asia/Shanghai')) if fetched_at is None else datetime.fromisoformat(fetched_at)
        if instant.tzinfo is None:
            raise ValueError('抓取时间必须明确时区')
        fetched=instant.astimezone(ZoneInfo('Asia/Shanghai')).isoformat()
        profile=FINANCIAL_PROFILES[endpoint]
        common=['ts_code','ann_date','end_date','update_flag']
        if endpoint!='fina_indicator':
            common+=['f_ann_date','report_type','comp_type','end_type']
        fields=common+list(profile['fields'])
        raw_parts=[]
        rows=[]
        missing=[]
        for period in sorted(periods):
            raw=self.provider.query(endpoint,dict(ts_code=symbol,period=period.replace('-','')),fields=','.join(fields))
            if len(raw)>=self.row_limit:
                raise ProviderError('truncated_response','单报告期仍达保守行数上限，需核对来源，未登记完整')
            if raw.empty:
                missing.append(period)
                continue
            if not set(common)<=set(raw) or not set(profile['fields'])<=set(raw):
                raise ProviderError('invalid_response','财务响应缺少请求字段')
            if not raw.ts_code.eq(symbol).all() or not raw.end_date.astype(str).eq(period.replace('-','')).all():
                raise ProviderError('invalid_response','财务响应证券或报告期不符')
            raw_parts.append(raw)
            for record in raw.to_dict('records'):
                ann=_source_date(record['ann_date'],required=True)
                actual=_source_date(record.get('f_ann_date'))
                if max(ann,actual or ann)<period:
                    raise ProviderError('invalid_response','财务公告早于报告期结束')
                report_type=str(record.get('report_type','indicator'))
                if endpoint!='fina_indicator' and report_type not in {str(i) for i in range(1,13)}:
                    raise ProviderError('unsupported_report_type','未识别财务报表类型')
                if str(record['update_flag']) not in {'0','1'}:
                    raise ProviderError('invalid_response','财务更新标记无效')
                values={}
                for field in profile['fields']:
                    value=record[field]
                    if pd.isna(value) or value=='':
                        values[field]=None
                    else:
                        try:
                            number=float(value)
                        except (ValueError,TypeError) as exc:
                            raise ProviderError('invalid_response','财务数值格式无效') from exc
                        if not np.isfinite(number):
                            raise ProviderError('invalid_response','财务数值不是有限值')
                        values[field]=number
                item=dict(symbol=symbol,endpoint=endpoint,period=period,ann_date=ann,f_ann_date=actual,
                    report_type=report_type,update_flag=str(record['update_flag']),fetched_at=fetched,
                    **values)
                item['report_version']='financial-'+identity_hash({k:v for k,v in item.items() if k!='fetched_at'})
                rows.append(item)
        raw=pd.concat(raw_parts,ignore_index=True) if raw_parts else pd.DataFrame(columns=fields)
        frame=pd.DataFrame(rows)
        metadata=dict(provider='tushare',endpoint=endpoint,symbol=symbol,periods=sorted(periods),missing_periods=missing,
            fetched_at=fetched,batch_id='tushare-financial-'+identity_hash(dict(endpoint=endpoint,symbol=symbol,
                fetched_at=fetched,raw=raw.to_json(orient='split'))),
            source_url=f"https://tushare.pro/document/2?doc_id={profile['doc']}",
            pit_coverage='unverified',unit_policy='source_values_preserved',automatic_fallback=False)
        return ProviderBatch(frame,raw,metadata,'partial' if missing else 'complete')

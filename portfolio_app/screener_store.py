"""Immutable local screen receipts, including exact input and result fingerprints."""
import copy
import json
from pathlib import Path
import re

from .dataset_registry import _atomic_write_json
from .research_result_cache import build_data_fingerprint
from .screener import SCREEN_FIELDS, screen_daily, validate_screen
from .snapshot_contracts import identity_hash


class ScreenerStore:
    def __init__(self,root):
        self.directory=Path(root)/'screens'
        self.directory.mkdir(parents=True,exist_ok=True)

    def save(self,name,result,*,x,y):
        if not isinstance(name,str) or not name.strip() or len(name)>60 or any(ord(c)<32 for c in name):
            raise ValueError('筛选名称须为1至60个可见字符')
        if x not in SCREEN_FIELDS or y not in SCREEN_FIELDS:
            raise ValueError('筛选图形字段不可用')
        validate_screen(result['config'])
        payload=dict(schema='saved-screen.v1',name=name.strip(),config=copy.deepcopy(result['config']),
            screen_id=result['screen_id'],symbols=list(result['symbols']),
            result_fingerprint=build_data_fingerprint(result['details']),view=dict(x=x,y=y),
            pool_semantics='fixed_members_selected_on_session')
        identifier='saved-screen-'+identity_hash(payload)
        path=self.directory/(identifier+'.json')
        if path.exists():
            self.open(identifier)
        else:
            _atomic_write_json(path,payload)
        return identifier

    def open(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'saved-screen-[a-f0-9]{64}',identifier):
            raise ValueError('保存筛选身份无效')
        payload=json.loads((self.directory/(identifier+'.json')).read_text(encoding='utf8'))
        if payload.get('schema')!='saved-screen.v1' or identifier!='saved-screen-'+identity_hash(payload):
            raise ValueError('保存筛选内容校验失败')
        validate_screen(payload['config'])
        return payload

    def records(self):
        rows=[]
        for path in sorted(self.directory.glob('saved-screen-*.json')):
            value=self.open(path.stem)
            rows.append(dict(identifier=path.stem,name=value['name'],session=value['config']['session'],
                snapshot_id=value['config']['snapshot_id'],count=len(value['symbols'])))
        return rows

    def reproduce(self,identifier,frame,*,manifest):
        saved=self.open(identifier)
        result=screen_daily(frame,manifest=manifest,config=saved['config'])
        if (result['screen_id']!=saved['screen_id'] or result['symbols']!=saved['symbols']
                or build_data_fingerprint(result['details'])!=saved['result_fingerprint']):
            raise ValueError('保存筛选与固定输入的复算结果不一致')
        return result

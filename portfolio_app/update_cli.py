"""Single-run update entry point usable independently of the web application."""
import argparse
import json
from pathlib import Path

from .daily_refresh import refresh_free_daily
from .dataset_registry import _atomic_write_json
from .providers.base import ProviderError
from .process_lock import process_lock
from .update_store import UpdateBusy


def execute(request):
    if not isinstance(request,dict) or set(request)-{'root','symbols','start','end','dataset_id'}:
        raise ValueError('更新请求字段无效')
    root=request['root']
    if not isinstance(root,str) or not root:
        raise ValueError('更新目录无效')
    with process_lock(Path(root)/'locks'/'free-refresh.lock'):
        return refresh_free_daily(root,symbols=request['symbols'],start=request['start'],end=request['end'],
            dataset_id=request.get('dataset_id','free-a-daily'))


def main():
    parser=argparse.ArgumentParser(description='更新并核对指定沪深股票的免费原始日线')
    parser.add_argument('--request',required=True)
    parser.add_argument('--result',required=True)
    args=parser.parse_args()
    with process_lock(Path(args.result).with_suffix('.running.lock'),wait=True):
        try:
            request=json.loads(Path(args.request).read_text(encoding='utf8'))
            report=execute(request)
        except UpdateBusy:
            report=dict(status='failed',error_code='update_busy')
        except ProviderError as exc:
            report=dict(status='failed',error_code=exc.code)
        except (ValueError,KeyError,TypeError):
            report=dict(status='failed',error_code='invalid_request')
        except Exception:
            report=dict(status='failed',error_code='local_or_network_error')
        _atomic_write_json(Path(args.result),report)
    print(json.dumps(dict(status=report['status']),ensure_ascii=False))
    return 0 if report['status'] in {'published','no_sessions'} else 1


if __name__=='__main__':
    raise SystemExit(main())

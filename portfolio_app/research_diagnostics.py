"""Allowlisted diagnostics; raw exceptions stay in a bounded internal memory tray."""
from __future__ import annotations

from collections import OrderedDict
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock
import traceback
import uuid


_OPERATIONS = {'research', 'import', 'archive', 'journal', 'configuration', 'replay'}
_MESSAGES = {
    'INPUT_INVALID': ('输入或配置未通过检查。', '请检查日期、字段映射、缺失值和参数范围，再点击运行。'),
    'ACCESS_DENIED': ('无法访问所需的本地文件。', '请检查文件权限，或选择可读取的文件后重试。'),
    'FILE_MISSING': ('所需的本地文件不可用。', '请重新选择数据文件，或恢复文件后重试。'),
    'STORAGE_ERROR': ('本地读取或保存失败。', '请检查磁盘空间和文件权限后重试；已有结果不会被覆盖。'),
    'MEMORY_LIMIT': ('研究超过可用内存。', '请缩小标的或日期范围后重新运行。'),
    'TASK_FAILED': ('本次操作失败。', '可先查看上次成功结果，再重新运行；如仍失败，请保留诊断编号。'),
}


def _safe_row(report):
    """Never forward arbitrary message strings, extras or exception information."""
    report = report if isinstance(report, dict) else {}
    identifier = report.get('error_id', '')
    return dict(schema='workbench-diagnostic.v1',
        error_id=identifier if isinstance(identifier, str) and len(identifier) == 32
            and all(c in '0123456789abcdef' for c in identifier) else 'unavailable',
        code=report.get('code') if isinstance(report.get('code'), str) and report.get('code') in _MESSAGES else 'TASK_FAILED',
        operation=report.get('operation') if isinstance(report.get('operation'), str) and report.get('operation') in _OPERATIONS else 'research')


class _SafeFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(_safe_row(record.msg), ensure_ascii=True)


class _QuietHandler(RotatingFileHandler):
    def handleError(self, record):
        # logging's default fallback prints the sink's path and traceback.
        # A failed diagnostic sink must neither leak details nor break research.
        return


def diagnostic_handler(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = _QuietHandler(path, maxBytes=256 * 1024, backupCount=2, encoding='utf8')
    handler.setFormatter(_SafeFormatter())
    return handler


_CONFIG_LOCK = RLock()


def configure_diagnostics(path):
    """Attach only the fixed local sink, once; never configure the root logger."""
    logger = logging.getLogger('portfolio_app.diagnostics')
    with _CONFIG_LOCK:
        if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
            logger.addHandler(diagnostic_handler(path))


class ErrorReports:
    def __init__(self, *, max_details=16, logger=None):
        if max_details < 1:
            raise ValueError('max_details must be positive')
        self._details = OrderedDict()
        self._lock = RLock()
        self.max_details = max_details
        self.logger = logger or logging.getLogger('portfolio_app.diagnostics')

    def capture(self, exc, *, operation='research'):
        code = ('ACCESS_DENIED' if isinstance(exc, PermissionError) else
                'FILE_MISSING' if isinstance(exc, FileNotFoundError) else
                'MEMORY_LIMIT' if isinstance(exc, MemoryError) else
                'STORAGE_ERROR' if isinstance(exc, OSError) else
                'INPUT_INVALID' if isinstance(exc, (ValueError, KeyError, TypeError)) else 'TASK_FAILED')
        if operation == 'journal' and code == 'TASK_FAILED':
            code = 'STORAGE_ERROR'
        report = _safe_row(dict(error_id=uuid.uuid4().hex, code=code, operation=operation))
        message, action = _MESSAGES[code]
        # No captured frame locals; no exception objects retained after handling.
        try:
            detail = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-8192:]
        except Exception:
            detail = 'Exception detail unavailable'
        with self._lock:
            self._details[report['error_id']] = detail
            while len(self._details) > self.max_details:
                self._details.popitem(last=False)
        try:
            self.logger.warning(report)
        except Exception:
            # Diagnostics must never prevent recovery when storage is broken.
            pass
        return {**report, 'message': message, 'action': action}

    def internal_detail(self, error_id):
        """Internal debugging only; never render, log or add this to an archive."""
        with self._lock:
            return self._details.get(error_id)


_UI_REPORTS = ErrorReports()


def capture_error(exc, *, operation='research'):
    return _UI_REPORTS.capture(exc, operation=operation)


def show_safe_error(exc, *, operation='research'):
    import streamlit as st
    report = capture_error(exc, operation=operation)
    st.error(report['message'])
    st.caption(report['action'])
    st.caption('诊断编号：' + report['error_id'])
    return report

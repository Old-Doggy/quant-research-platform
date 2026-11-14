"""One background task per session, cancellable commit and metadata-only journal.

Results stay in memory or user-downloaded archives. The journal never unpickles
objects or treats a partial file as a successful result after process restart.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
import sqlite3
from threading import RLock, Thread
import time
import uuid

from .research_jobs import CancellationToken, ResearchCancelled
from .research_result_cache import ResearchResultCache
from .research_diagnostics import ErrorReports


def _process_alive(pid):
    if pid == os.getpid():
        return True
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # Access denied is uncertain; invalid PID is definitely gone.
            return ctypes.get_last_error() != 87
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class TaskJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, key_id TEXT, pid INTEGER, status TEXT, updated REAL)')

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def begin(self, task_id, key_id, *, pid=None):
        with self._connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',
                       (task_id, key_id, os.getpid() if pid is None else pid, 'running', time.time()))

    def finish(self, task_id, status):
        if status not in {'succeeded', 'failed', 'cancelled', 'interrupted'}:
            raise ValueError('invalid terminal status')
        with self._connect() as db:
            db.execute('UPDATE tasks SET status=?, updated=? WHERE id=?', (status, time.time(), task_id))

    def recover(self):
        with self._connect() as db:
            for task_id, pid in db.execute("SELECT id,pid FROM tasks WHERE status='running'").fetchall():
                if not _process_alive(pid):
                    db.execute("UPDATE tasks SET status='interrupted',updated=? WHERE id=?", (time.time(), task_id))

    def records(self, limit=50):
        self.recover()
        with self._connect() as db:
            rows = db.execute('SELECT id,key_id,status,updated FROM tasks ORDER BY updated DESC LIMIT ?',
                              (min(100, max(1, int(limit))),)).fetchall()
        return [dict(task_id=a, key_id=b, status=c, updated=d, result_available=False) for a, b, c, d in rows]


class ResearchRunner:
    def __init__(self, *, journal=None, cache=None):
        self.journal = journal
        self.cache = cache if cache is not None else ResearchResultCache()
        self._lock = RLock()
        self._token = CancellationToken()
        self._task = dict(status='idle', task_id=None, elapsed=0., cache_hit=False)
        self._value = None
        self.last_success = None
        self.reports = ErrorReports()

    def start(self, key, compute):
        with self._lock:
            if self._task['status'] == 'running':
                raise RuntimeError('a research task is already running')
            self._token = CancellationToken()
            self._value = None
            task_id = uuid.uuid4().hex
            self._task = dict(task_id=task_id, status='running', started=time.monotonic(),
                              elapsed=0., cache_hit=False, error=None)
            if self.journal:
                try:
                    self.journal.begin(task_id, key.key_id)
                except Exception as exc:
                    failure = self.reports.capture(exc, operation='journal')
                    self._task.update(status='failed', error=failure['message'], failure=failure)
                    return task_id
            try:
                Thread(target=self._work, args=(task_id, key, compute, self._token), daemon=True).start()
            except Exception as exc:
                failure = self.reports.capture(exc)
                self._task.update(status='failed', error=failure['message'], failure=failure)
                if self.journal:
                    try:
                        self.journal.finish(task_id, 'failed')
                    except Exception:
                        pass
            return task_id

    def _work(self, task_id, key, compute, token):
        try:
            token.report(.02, 'lookup')
            cached = self.cache.lookup(key)
            value = cached if cached is not None else compute(token)
            # Cancellation and commit share the lock: a cancelled attempt cannot
            # sneak its result into either cache or current workspace.
            with self._lock:
                token.checkpoint()
                retained = copy.deepcopy(value)
                result = self.cache.submit(key, lambda: value)
                try:
                    if self.journal:
                        self.journal.finish(task_id, 'succeeded')
                except Exception:
                    if not result.cache_hit:
                        self.cache.discard(key)
                    raise
                self._value = result.value
                self.last_success = retained
                self._task.update(status='succeeded', cache_hit=result.cache_hit,
                                  elapsed=time.monotonic() - self._task['started'])
        except Exception as exc:
            status = 'cancelled' if isinstance(exc, ResearchCancelled) else 'failed'
            failure = None if status == 'cancelled' else self.reports.capture(exc)
            with self._lock:
                if self.journal:
                    try:
                        self.journal.finish(task_id, status)
                    except Exception:
                        # A broken journal cannot strand the session in RUNNING.
                        pass
                self._value = None
                self._task.update(status=status, error=failure['message'] if failure else '研究已取消', failure=failure,
                                  elapsed=time.monotonic() - self._task['started'])

    def cancel(self):
        with self._lock:
            if self._task['status'] == 'running':
                self._token.request_cancel()

    def snapshot(self):
        with self._lock:
            progress, phase = self._token.snapshot()
            return {**self._task, 'progress': progress, 'phase': phase,
                    'cancel_requested': self._token.cancelled,
                    'elapsed': time.monotonic() - self._task['started']
                    if self._task['status'] == 'running' else self._task['elapsed']}

    def result(self):
        with self._lock:
            return copy.deepcopy(self._value) if self._task['status'] == 'succeeded' else None

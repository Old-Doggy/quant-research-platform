"""Single-job coordinator for offline research submissions."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Mapping
import uuid
from threading import Event, RLock

from portfolio_app.research_result_cache import ResearchCacheKey, ResearchResultCache
from .research_diagnostics import ErrorReports


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchJobError(RuntimeError):
    pass


class ResearchCancelled(ResearchJobError):
    pass


class CancellationToken:
    def __init__(self) -> None:
        self._cancel_requested = Event()
        self._progress_lock = RLock()
        self.progress = 0.0
        self.phase = 'queued'

    @property
    def cancelled(self) -> bool:
        return self._cancel_requested.is_set()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def checkpoint(self) -> None:
        if self._cancel_requested.is_set():
            raise ResearchCancelled("research job was cancelled")

    def report(self, fraction, phase):
        self.checkpoint()
        if not 0 <= fraction <= 1:
            raise ValueError('progress must be between zero and one')
        with self._progress_lock:
            self.progress, self.phase = float(fraction), str(phase)

    def snapshot(self):
        with self._progress_lock:
            return self.progress, self.phase


@dataclass(frozen=True)
class ResearchJob:
    job_id: str
    key: ResearchCacheKey
    status: JobStatus = JobStatus.QUEUED
    result: Mapping[str, Any] | None = None
    error: str | None = None
    cache_hit: bool = False
    failure: Mapping[str, Any] | None = None


class ResearchJobCoordinator:
    """Run one offline research job at a time and commit atomically."""

    def __init__(self, cache: ResearchResultCache) -> None:
        self.cache = cache
        self._jobs: dict[str, ResearchJob] = {}
        self._active_job_id: str | None = None
        self.reports = ErrorReports()

    @property
    def active_job(self) -> ResearchJob | None:
        if self._active_job_id is None:
            return None
        return self._jobs[self._active_job_id]

    def create_job(self, key: ResearchCacheKey) -> ResearchJob:
        if self.active_job is not None and self.active_job.status is JobStatus.RUNNING:
            raise ResearchJobError("a research job is already running")
        job = ResearchJob(job_id=f"job-{uuid.uuid4().hex[:16]}", key=key)
        self._jobs[job.job_id] = job
        return job

    def cancel(self, job_id: str) -> ResearchJob:
        job = self._get(job_id)
        if job.status is JobStatus.QUEUED:
            job = ResearchJob(job_id=job.job_id, key=job.key, status=JobStatus.CANCELLED)
            self._jobs[job_id] = job
            return job
        if job.status is JobStatus.RUNNING:
            raise ResearchJobError("running jobs must be cancelled through their token")
        return job

    def run(self, job_id: str, compute: Callable[[CancellationToken], Mapping[str, Any]]) -> ResearchJob:
        job = self._get(job_id)
        if job.status is JobStatus.CANCELLED:
            raise ResearchCancelled("research job was cancelled")
        if job.status is not JobStatus.QUEUED:
            raise ResearchJobError(f"job is not runnable: {job.status.value}")
        if self.active_job is not None and self.active_job.status is JobStatus.RUNNING:
            raise ResearchJobError("a research job is already running")
        token = CancellationToken()
        running = ResearchJob(job_id=job.job_id, key=job.key, status=JobStatus.RUNNING)
        self._jobs[job_id] = running
        self._active_job_id = job_id
        try:
            token.checkpoint()
            computed = compute(token)
            token.checkpoint()
            if not isinstance(computed, Mapping):
                raise TypeError("research result must be a mapping")
            cached = self.cache.submit(job.key, lambda: dict(computed))
            completed = ResearchJob(
                job_id=job.job_id,
                key=job.key,
                status=JobStatus.SUCCEEDED,
                result=dict(cached.value),
                cache_hit=cached.cache_hit,
            )
        except ResearchCancelled as exc:
            completed = ResearchJob(job_id=job.job_id, key=job.key, status=JobStatus.CANCELLED, error='研究已取消')
        except Exception as exc:
            failure = self.reports.capture(exc)
            completed = ResearchJob(job_id=job.job_id, key=job.key, status=JobStatus.FAILED,
                                    error=failure['message'], failure=failure)
        self._jobs[job_id] = completed
        self._active_job_id = None
        return completed

    def submit(self, key: ResearchCacheKey, compute: Callable[[CancellationToken], Mapping[str, Any]]) -> ResearchJob:
        if self.active_job is not None and self.active_job.status is JobStatus.RUNNING:
            raise ResearchJobError("a research job is already running")
        cached = self.cache.lookup(key)
        if cached is not None:
            job = self.create_job(key)
            cached_result = self.cache.submit(key, lambda: cached)
            completed = ResearchJob(job_id=job.job_id, key=key, status=JobStatus.SUCCEEDED, result=dict(cached_result.value), cache_hit=True)
            self._jobs[job.job_id] = completed
            return completed
        job = self.create_job(key)
        return self.run(job.job_id, compute)

    def _get(self, job_id: str) -> ResearchJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise ResearchJobError(f"unknown research job: {job_id}") from exc

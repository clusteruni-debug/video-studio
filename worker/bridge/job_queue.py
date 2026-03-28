"""Async job queue — FIFO queue for external REST API integration.

Jobs are submitted via ``POST /api/jobs`` and polled via ``GET /api/jobs/<id>``.
A single worker thread processes jobs sequentially.
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class JobSpec:
    """One queued generation job."""

    job_id: str
    created_at: str
    payload: dict = field(default_factory=dict)
    status: str = "queued"  # queued | running | completed | failed
    result: dict | None = None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "result": self.result,
        }


class JobQueue:
    """Simple in-memory FIFO job queue with a single worker thread."""

    MAX_JOBS = 500

    def __init__(self, execute_fn=None) -> None:
        self._queue: deque[str] = deque()
        self._jobs: dict[str, JobSpec] = {}
        self._lock = threading.Lock()
        self._running = False
        self._execute_fn = execute_fn

    def set_execute_fn(self, fn) -> None:
        """Set the function that processes each job payload → result dict."""
        self._execute_fn = fn

    def submit(self, payload: dict) -> str:
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        job = JobSpec(job_id=job_id, created_at=now, payload=payload)
        with self._lock:
            self._evict_old_jobs()
            self._jobs[job_id] = job
            self._queue.append(job_id)
        self._ensure_worker()
        return job_id

    def get_job(self, job_id: str) -> JobSpec | None:
        with self._lock:
            return self._jobs.get(job_id)

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                if job.status in ("queued", "completed", "failed"):
                    del self._jobs[job_id]
                    if job_id in self._queue:
                        self._queue.remove(job_id)
                    return True
            return False

    def list_jobs(self, limit: int = 20) -> list[dict]:
        with self._lock:
            jobs = list(self._jobs.values())[-limit:]
        return [j.to_dict() for j in jobs]

    # -- internal --

    def _evict_old_jobs(self) -> None:
        """Remove oldest completed/failed jobs when over capacity.  Caller holds _lock."""
        if len(self._jobs) < self.MAX_JOBS:
            return
        done = [
            (jid, j) for jid, j in self._jobs.items()
            if j.status in ("completed", "failed")
        ]
        done.sort(key=lambda x: x[1].created_at)
        to_remove = max(1, len(done) // 2)
        for jid, _ in done[:to_remove]:
            del self._jobs[jid]

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()

    def _worker_loop(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._running = False
                    return
                job_id = self._queue.popleft()
            self._process_job(job_id)

    def _process_job(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.status = "running"
        job.started_at = datetime.now(timezone.utc).isoformat()
        try:
            if self._execute_fn is None:
                raise RuntimeError("No execute function configured")
            job.result = self._execute_fn(job.payload)
            job.status = "completed"
        except Exception as e:
            job.error = str(e)
            job.status = "failed"
        job.completed_at = datetime.now(timezone.utc).isoformat()

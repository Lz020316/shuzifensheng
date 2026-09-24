"""Background worker pool for queued task runs."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Callable

from .storage import RunJobRecord, RunRecord, TaskRecord, TaskRepository


ExecuteTaskFn = Callable[[TaskRecord, str], RunRecord]


@dataclass(slots=True)
class RunJobWorkerPool:
    """Process queued run jobs with retry support."""

    repository: TaskRepository
    execute_task_fn: ExecuteTaskFn
    worker_count: int = 2
    poll_interval_seconds: float = 0.5
    _stop_event: threading.Event = field(init=False, repr=False)
    _threads: list[threading.Thread] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        """Start worker threads."""
        if self._threads:
            return
        for index in range(max(1, self.worker_count)):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"run-job-worker-{index}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        """Stop worker threads."""
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads.clear()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            job = self.repository.claim_next_job()
            if job is None:
                self._stop_event.wait(self.poll_interval_seconds)
                continue
            self._process_job(job)

    def _process_job(self, job: RunJobRecord) -> None:
        latest_job = self.repository.get_run_job(job.job_id)
        if latest_job is None:
            return
        if latest_job.cancel_requested:
            self.repository.mark_run_job_canceled(
                job.job_id,
                reason="job canceled before execution",
            )
            return

        task = self.repository.get_task(job.task_id)
        if task is None:
            self.repository.mark_run_job_failed(
                job.job_id,
                f"task not found: {job.task_id}",
                retry=False,
            )
            return

        try:
            run = self.execute_task_fn(task, job.override_source)
        except Exception as exc:  # noqa: BLE001
            refreshed = self.repository.get_run_job(job.job_id)
            if refreshed is not None and refreshed.cancel_requested:
                self.repository.mark_run_job_canceled(
                    job.job_id,
                    reason=f"job canceled during retry window: {exc}",
                )
                return

            should_retry = job.attempt_count < job.max_attempts
            self.repository.mark_run_job_failed(job.job_id, str(exc), retry=should_retry)
            if should_retry:
                delay = self._compute_retry_delay_seconds(job.attempt_count)
                time.sleep(delay)
            return
        self.repository.mark_run_job_succeeded(job.job_id, run.run_id)

    @staticmethod
    def _compute_retry_delay_seconds(attempt_count: int) -> float:
        """Exponential backoff delay by attempt count."""
        base = 0.4
        return min(8.0, base * (2 ** max(0, attempt_count - 1)))

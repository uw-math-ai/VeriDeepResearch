from __future__ import annotations

import asyncio
import os
import time
import traceback
from job_models import JobState, JobPhase
from agent import run_agent_job
from email_sender import send_result_email


class WorkerManager:
    def __init__(self, max_concurrent: int = 2):
        self.max_concurrent = max_concurrent
        self.active_jobs: dict[str, asyncio.Task] = {}

    async def run(self):
        """Main worker loop. Polls for queued jobs every 2 seconds."""
        print("[worker] Started")
        while True:
            try:
                await self._tick()
            except Exception:
                traceback.print_exc()
            await asyncio.sleep(2)

    async def _tick(self):
        # Clean up finished tasks
        finished = [jid for jid, task in self.active_jobs.items() if task.done()]
        for jid in finished:
            task = self.active_jobs.pop(jid)
            exc = task.exception() if not task.cancelled() else None
            if exc:
                print(f"[worker] Job {jid} failed: {exc}")

        if len(self.active_jobs) >= self.max_concurrent:
            return

        # Find queued jobs + recover stale ones
        all_jobs = JobState.list_all()
        queued = []
        for j in all_jobs:
            phase = j.get_phase()
            if phase == JobPhase.QUEUED:
                queued.append(j)
            elif phase not in (JobPhase.COMPLETED, JobPhase.FAILED):
                # Running job — check if worker is alive
                if j.worker_pid and not _pid_alive(j.worker_pid):
                    j.set_phase(JobPhase.QUEUED)
                    j.worker_pid = 0
                    j.add_status("Resumed after worker restart")
                    j.save()
                    queued.append(j)

        queued.sort(key=lambda j: j.created_at)

        for job in queued:
            if len(self.active_jobs) >= self.max_concurrent:
                break
            if job.job_id not in self.active_jobs:
                task = asyncio.create_task(self._process_job(job.job_id))
                self.active_jobs[job.job_id] = task
                print(f"[worker] Started job {job.job_id}: {job.question[:60]}")

    async def _process_job(self, job_id: str):
        job = JobState.load(job_id)
        if not job:
            return

        job.worker_pid = os.getpid()
        job.started_at = job.started_at or time.time()
        job.save()

        try:
            await run_agent_job(job)
        except Exception as e:
            job.set_phase(JobPhase.FAILED)
            job.error = f"{type(e).__name__}: {e}"
            job.finished_at = time.time()
            job.add_status(f"Error: {job.error}")
            job.save()
            traceback.print_exc()

        # Reload to get latest state (run_agent_job saves throughout)
        job = JobState.load(job_id)
        if not job:
            return

        job.worker_pid = 0
        job.save()

        # Send email
        if job.email:
            _send_email(job)
            print(f"[worker] Email sent for job {job_id}")

        phase = job.get_phase()
        print(f"[worker] Job {job_id} finished: {phase.value}, cost=${job.total_cost:.4f}")

    def status(self) -> dict:
        return {
            "active_jobs": list(self.active_jobs.keys()),
            "max_concurrent": self.max_concurrent,
        }


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _send_email(job: JobState):
    elapsed = (job.finished_at or time.time()) - (job.started_at or job.created_at)
    stats = {
        "elapsed_seconds": round(elapsed, 1),
        "total_input_tokens": job.total_input_tokens,
        "total_output_tokens": job.total_output_tokens,
        "total_cost_usd": round(job.total_cost, 4),
        "tool_counts": job.tool_counts,
    }
    verified = job.best_code_verified and job.best_code_sorry_free
    send_result_email(
        to_email=job.email,
        question=job.question,
        status_log="\n".join(f"- {s}" for s in job.status_log),
        full_log="\n\n".join(job.full_log),
        answer=job.answer,
        lean_code=job.best_lean_code,
        verified=verified,
        stats=stats,
    )

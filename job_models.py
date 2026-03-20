from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional

JOBS_DIR = os.getenv("JOBS_DIR", "/data/jobs")


class JobPhase(str, Enum):
    QUEUED = "queued"
    RESEARCHING = "researching"
    PROVING_FAST = "proving_fast"
    ARISTOTLE = "aristotle"
    DECOMPOSING = "decomposing"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobState:
    job_id: str
    question: str
    email: Optional[str] = None
    phase: str = "queued"  # stored as string for JSON serialization
    created_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    # Agent conversation state (for crash recovery)
    messages: list = field(default_factory=list)
    iteration: int = 0

    # Cost tracking
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    tool_counts: dict = field(default_factory=dict)

    # Best proof so far
    best_lean_code: str = ""
    best_code_verified: bool = False
    best_code_sorry_free: bool = False
    answer: str = ""

    # Aristotle sub-jobs
    aristotle_jobs: list = field(default_factory=list)

    # Logs
    status_log: list = field(default_factory=list)
    full_log: list = field(default_factory=list)

    # Error
    error: Optional[str] = None

    # Worker lock
    worker_pid: int = 0

    @staticmethod
    def create(question: str, email: Optional[str] = None) -> JobState:
        return JobState(
            job_id=uuid.uuid4().hex[:12],
            question=question,
            email=email,
            created_at=time.time(),
        )

    def get_phase(self) -> JobPhase:
        return JobPhase(self.phase)

    def set_phase(self, p: JobPhase):
        self.phase = p.value

    def add_status(self, msg: str):
        self.status_log.append(msg)

    def add_log(self, msg: str):
        self.full_log.append(msg)

    def save(self):
        os.makedirs(JOBS_DIR, exist_ok=True)
        path = os.path.join(JOBS_DIR, f"{self.job_id}.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(asdict(self), f)
        os.replace(tmp, path)

    @staticmethod
    def load(job_id: str) -> Optional[JobState]:
        path = os.path.join(JOBS_DIR, f"{job_id}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return JobState(**{
                k: v for k, v in data.items()
                if k in JobState.__dataclass_fields__
            })
        except Exception:
            return None

    @staticmethod
    def list_all() -> list[JobState]:
        if not os.path.isdir(JOBS_DIR):
            return []
        jobs = []
        for fname in sorted(os.listdir(JOBS_DIR), reverse=True):
            if fname.endswith(".json") and not fname.endswith(".tmp"):
                job = JobState.load(fname[:-5])
                if job:
                    jobs.append(job)
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    def elapsed_str(self) -> str:
        if self.finished_at and self.started_at:
            secs = int(self.finished_at - self.started_at)
        elif self.started_at:
            secs = int(time.time() - self.started_at)
        else:
            return "-"
        mins = secs // 60
        s = secs % 60
        return f"{mins}m {s:02d}s" if mins else f"{s}s"

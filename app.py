from __future__ import annotations

import asyncio
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from job_models import JobState, JobPhase
from worker import WorkerManager

app = FastAPI(title="VeriDeepResearch")
templates = Jinja2Templates(directory="templates")
worker_manager: WorkerManager | None = None


@app.on_event("startup")
async def startup():
    global worker_manager
    worker_manager = WorkerManager(max_concurrent=3)
    asyncio.create_task(worker_manager.run())


# --- Submit form ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/submit")
async def submit_job(
    question: str = Form(...),
    email: str = Form(""),
):
    question = question.strip()
    if not question:
        return RedirectResponse("/", status_code=303)
    job = JobState.create(question, email=email.strip() if email.strip() else None)
    job.save()
    return RedirectResponse(f"/job/{job.job_id}", status_code=303)


# --- Job status page ---
@app.get("/job/{job_id}", response_class=HTMLResponse)
async def job_status_page(request: Request, job_id: str):
    job = JobState.load(job_id)
    if not job:
        return HTMLResponse("Job not found", status_code=404)
    return templates.TemplateResponse("status.html", {"request": request, "job": job})


# --- JSON API for polling ---
@app.get("/api/job/{job_id}")
async def job_api(job_id: str):
    job = JobState.load(job_id)
    if not job:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({
        "job_id": job.job_id,
        "phase": job.phase,
        "question": job.question,
        "status_log": job.status_log[-50:],  # last 50 entries
        "best_lean_code": job.best_lean_code,
        "best_code_verified": job.best_code_verified,
        "best_code_sorry_free": job.best_code_sorry_free,
        "answer": job.answer,
        "iteration": job.iteration,
        "total_cost": round(job.total_cost, 4),
        "total_input_tokens": job.total_input_tokens,
        "total_output_tokens": job.total_output_tokens,
        "tool_counts": job.tool_counts,
        "aristotle_jobs": job.aristotle_jobs,
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "elapsed": job.elapsed_str(),
    })


# --- List all jobs ---
@app.get("/jobs", response_class=HTMLResponse)
async def list_jobs(request: Request):
    jobs = JobState.list_all()
    return templates.TemplateResponse("jobs.html", {"request": request, "jobs": jobs})


# --- Download proof ---
@app.get("/job/{job_id}/proof.lean")
async def download_proof(job_id: str):
    job = JobState.load(job_id)
    if not job or not job.best_lean_code:
        return PlainTextResponse("Not available", status_code=404)
    return PlainTextResponse(
        job.best_lean_code,
        headers={"Content-Disposition": f"attachment; filename=proof_{job_id}.lean"},
    )


# --- Worker status ---
@app.get("/api/worker")
async def worker_status():
    if worker_manager:
        return JSONResponse(worker_manager.status())
    return JSONResponse({"error": "worker not started"})

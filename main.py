"""
main.py — FastAPI entry point for Railway deployment
Exposes REST endpoints to trigger the job agent.
"""

import os
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Literal, Optional
from agent import JobApplicationAgent
from notifier import parse_telegram_command
from pipeline import WorkflowOrchestrator

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AI Job Bot", version="1.0.0")
agent = JobApplicationAgent()
orchestrator = WorkflowOrchestrator()


class Job(BaseModel):
    id: str
    title: str
    company: str
    location: Optional[str] = ""
    description: Optional[str] = ""


class BatchRequest(BaseModel):
    jobs: List[Job]


class PipelineRunRequest(BaseModel):
    top_n: int = 5


class JobDecisionRequest(BaseModel):
    job_id: str
    action: Literal["APPLY", "REJECT", "SKIP"]


class TelegramUpdateRequest(BaseModel):
    update_id: Optional[int] = None
    message: Optional[dict] = None


@app.get("/")
def health():
    return {
        "status": "ok",
        "groq": agent.groq_available,
        "pending_actions": len(orchestrator.pending_actions()),
        "integrations": {
            "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        },
    }


@app.post("/process")
def process_single(job: Job):
    result = agent.process_job(job.model_dump())
    return result


@app.post("/batch")
def process_batch(req: BatchRequest):
    jobs = [j.model_dump() for j in req.jobs]
    results = agent.batch_process(jobs)
    return {"count": len(results), "results": results}


@app.post("/pipeline/run")
def run_pipeline(req: PipelineRunRequest):
    return orchestrator.run_once(top_n=req.top_n)


@app.get("/pipeline/pending")
def list_pending():
    return {"pending": orchestrator.pending_actions()}


@app.get("/pipeline/action/{job_id}")
def action_status(job_id: str):
    try:
        return orchestrator.action_status(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/pipeline/runs")
def pipeline_runs():
    return {"runs": orchestrator.recent_runs()}


@app.post("/pipeline/decision")
def decide_job(req: JobDecisionRequest):
    try:
        return orchestrator.decide(job_id=req.job_id, action=req.action)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/telegram/webhook")
def telegram_webhook(update: TelegramUpdateRequest):
    command = parse_telegram_command(update.model_dump())
    if not command:
        return {"status": "ignored"}
    try:
        result = orchestrator.decide(job_id=command["job_id"], action=command["action"])
        return {"status": "processed", "result": result}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

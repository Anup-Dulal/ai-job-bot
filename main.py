"""
main.py — FastAPI entry point for Railway deployment
Exposes REST endpoints to trigger the job agent.
"""

import os
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from agent import JobApplicationAgent

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AI Job Bot", version="1.0.0")
agent = JobApplicationAgent()


class Job(BaseModel):
    id: str
    title: str
    company: str
    location: Optional[str] = ""
    description: Optional[str] = ""


class BatchRequest(BaseModel):
    jobs: List[Job]


@app.get("/")
def health():
    return {"status": "ok", "groq": agent.groq_available}


@app.post("/process")
def process_single(job: Job):
    result = agent.process_job(job.dict())
    return result


@app.post("/batch")
def process_batch(req: BatchRequest):
    jobs = [j.dict() for j in req.jobs]
    results = agent.batch_process(jobs)
    return {"count": len(results), "results": results}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

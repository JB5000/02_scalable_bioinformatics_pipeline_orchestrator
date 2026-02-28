"""FastAPI application for bioinformatics pipeline orchestrator."""
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from src.models import SubmitPipelineRequest, JobStatusResponse, Sample, Pipeline, ExecutionProfile
from src.orchestration.engine import OrchestrationEngine
import logging

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Bioinformatics Pipeline Orchestrator API",
    description="REST API for managing genomics workflows across local, HPC, and cloud environments",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize orchestration engine
engine = OrchestrationEngine()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "bioinformatics-orchestrator"}


@app.post("/api/v1/pipelines/submit")
async def submit_pipeline(request: SubmitPipelineRequest):
    """Submit a new pipeline for execution."""
    try:
        job_ids = []
        for sample in request.samples:
            # Select optimal execution profile
            profile = engine.select_profile(
                len(request.samples),
                use_cloud=request.execution_profile == ExecutionProfile.AWSBATCH
            )
            
            # Submit job
            job_id = engine.submit_job(sample, request.pipeline_id, profile)
            job_ids.append(job_id)
        
        return {
            "status": "submitted",
            "job_ids": job_ids,
            "total_samples": len(request.samples)
        }
    except Exception as e:
        logger.error(f"Error submitting pipeline: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get status of a specific job."""
    job = engine.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        "job_id": job_id,
        "status": job.status,
        "submitted_at": job.submitted_at,
        "progress": 0.5  # Placeholder
    }


@app.post("/api/v1/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a running job."""
    success = engine.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {"status": "cancelled", "job_id": job_id}


@app.get("/api/v1/jobs")
async def list_jobs(status: Optional[str] = None):
    """List all jobs with optional filtering."""
    jobs = engine.list_jobs(status=status)
    return {
        "total": len(jobs),
        "jobs": [{"id": j.job_id_remote, "status": j.status} for j in jobs]
    }


@app.get("/api/v1/metrics")
async def get_metrics():
    """Get system metrics."""
    jobs = engine.list_jobs()
    total_jobs = len(jobs)
    completed = len([j for j in jobs if j.status == "completed"])
    failed = len([j for j in jobs if j.status == "failed"])
    
    return {
        "total_jobs": total_jobs,
        "completed_jobs": completed,
        "failed_jobs": failed,
        "success_rate": completed / max(total_jobs, 1)
    }


# Error handlers
@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {str(exc)}")
    return {"error": "Internal server error", "detail": str(exc)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""Orchestration engine for bioinformatics workflows."""
import json
import logging
import subprocess
import uuid
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass
from src.models import Job, JobStatus, ExecutionProfile, Sample
from src.validation import DataValidator


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    """Result of job execution."""
    job_id: str
    status: str
    output_path: Optional[str] = None
    error_message: Optional[str] = None
    metrics: Dict = None
    completed_at: Optional[datetime] = None


class OrchestrationEngine:
    """Manages job submission, tracking, and execution."""
    
    def __init__(self, config_path: str = "configs/default.yaml"):
        """Initialize orchestration engine."""
        self.config_path = config_path
        self.jobs: Dict[str, Job] = {}
        self.logger = logger
    
    def validate_input(self, sample: Sample) -> bool:
        """Validate input data before submission."""
        is_valid, error = DataValidator.validate_file(
            sample.data_path,
            sample.file_format
        )
        if not is_valid:
            self.logger.error(f"Validation failed for {sample.name}: {error}")
            return False
        return True
    
    def select_profile(self, samples_count: int, use_cloud: bool = False) -> ExecutionProfile:
        """Select optimal execution profile."""
        if samples_count >= 100 and use_cloud:
            return ExecutionProfile.AWSBATCH
        elif samples_count >= 20:
            return ExecutionProfile.SLURM
        else:
            return ExecutionProfile.LOCAL
    
    def submit_job(self, sample: Sample, pipeline_id: int, profile: ExecutionProfile) -> str:
        """Submit job for execution."""
        # Validate input
        if not self.validate_input(sample):
            raise ValueError(f"Input validation failed for {sample.name}")
        
        # Create job record
        job = Job(
            sample_id=sample.id or 0,
            pipeline_id=pipeline_id,
            execution_profile=profile,
            status=JobStatus.QUEUED,
            submitted_at=datetime.now()
        )
        
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        job.job_id_remote = job_id
        self.jobs[job_id] = job
        
        self.logger.info(f"Job submitted: {job_id} for sample {sample.name}")
        return job_id
    
    def get_job_status(self, job_id: str) -> Optional[Job]:
        """Get current status of job."""
        return self.jobs.get(job_id)
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel running job."""
        job = self.jobs.get(job_id)
        if job:
            job.status = JobStatus.CANCELLED
            self.logger.info(f"Job cancelled: {job_id}")
            return True
        return False
    
    def execute_local(self, command: str) -> JobResult:
        """Execute job locally."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour
            )
            
            if result.returncode == 0:
                return JobResult(
                    job_id=str(uuid.uuid4()),
                    status="completed",
                    completed_at=datetime.now()
                )
            else:
                return JobResult(
                    job_id=str(uuid.uuid4()),
                    status="failed",
                    error_message=result.stderr
                )
        except subprocess.TimeoutExpired:
            return JobResult(
                job_id=str(uuid.uuid4()),
                status="failed",
                error_message="Job timeout"
            )
        except Exception as e:
            return JobResult(
                job_id=str(uuid.uuid4()),
                status="failed",
                error_message=str(e)
            )
    
    def list_jobs(self, status: Optional[str] = None) -> List[Job]:
        """List all jobs, optionally filtered by status."""
        jobs = list(self.jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        return jobs

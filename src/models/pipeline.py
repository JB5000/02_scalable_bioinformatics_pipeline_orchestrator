"""Pydantic models for pipeline orchestration."""
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, validator


class ExecutionProfile(str, Enum):
    """Execution environment options."""
    LOCAL = "local"
    SLURM = "slurm"
    AWSBATCH = "awsbatch"


class JobStatus(str, Enum):
    """Job execution status."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Sample(BaseModel):
    """Input sample model."""
    id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=255)
    data_path: str = Field(..., description="Path to FASTQ/BAM/VCF file")
    file_format: str = Field(default="fastq")
    size_bytes: Optional[int] = None
    metadata: Dict[str, Any] = {}
    created_at: Optional[datetime] = None
    status: str = "pending"

    @validator('file_format')
    def validate_format(cls, v):
        allowed = ['fastq', 'bam', 'vcf', 'gzip']
        if v not in allowed:
            raise ValueError(f'File format must be one of {allowed}')
        return v

    class Config:
        use_enum_values = True


class Pipeline(BaseModel):
    """Pipeline/workflow definition."""
    id: Optional[int] = None
    name: str = Field(..., min_length=1)
    version: str = "1.0.0"
    description: Optional[str] = None
    nextflow_script: str = Field(..., description="Path to main.nf")
    parameters: Dict[str, Any] = {}
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        use_enum_values = True


class Job(BaseModel):
    """Job execution record."""
    id: Optional[int] = None
    sample_id: int
    pipeline_id: int
    execution_profile: ExecutionProfile
    status: JobStatus = JobStatus.QUEUED
    job_id_remote: Optional[str] = None
    log_file: Optional[str] = None
    submitted_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = {}

    class Config:
        use_enum_values = True


class Run(BaseModel):
    """Batch run of multiple samples."""
    id: Optional[int] = None
    name: str = Field(..., min_length=1)
    pipeline_id: int
    total_samples: int
    status: str = "pending"
    job_ids: list = []
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    total_duration_seconds: Optional[float] = None
    total_cost_usd: Optional[float] = None
    results: Dict[str, Any] = {}

    class Config:
        use_enum_values = True


class SubmitPipelineRequest(BaseModel):
    """API request to submit pipeline."""
    samples: list[Sample]
    pipeline_id: int
    execution_profile: ExecutionProfile = ExecutionProfile.LOCAL
    parameters: Dict[str, Any] = {}


class JobStatusResponse(BaseModel):
    """API response for job status."""
    job_id: int
    status: JobStatus
    sample_name: str
    progress: float = 0.0
    logs_url: Optional[str] = None
    estimated_completion: Optional[datetime] = None

    class Config:
        use_enum_values = True

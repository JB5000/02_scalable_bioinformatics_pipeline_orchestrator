"""Tests for orchestration engine."""
import pytest
from src.orchestration.engine import OrchestrationEngine
from src.models import Sample, ExecutionProfile


@pytest.fixture
def engine():
    return OrchestrationEngine()


def test_select_profile_local(engine):
    """Test profile selection for small workload."""
    profile = engine.select_profile(samples_count=5)
    assert profile == ExecutionProfile.LOCAL


def test_select_profile_slurm(engine):
    """Test profile selection for medium workload."""
    profile = engine.select_profile(samples_count=50)
    assert profile == ExecutionProfile.SLURM


def test_select_profile_awsbatch(engine):
    """Test profile selection for large cloud workload."""
    profile = engine.select_profile(samples_count=150, use_cloud=True)
    assert profile == ExecutionProfile.AWSBATCH


def test_job_submission(engine):
    """Test job submission."""
    sample = Sample(
        name="test_sample",
        data_path="./data/test.fastq",
        file_format="fastq"
    )
    
    job_id = engine.submit_job(sample, pipeline_id=1, profile=ExecutionProfile.LOCAL)
    assert job_id is not None
    assert job_id in engine.jobs


def test_get_job_status(engine):
    """Test getting job status."""
    sample = Sample(
        name="test_sample",
        data_path="./data/test.fastq",
        file_format="fastq"
    )
    
    job_id = engine.submit_job(sample, pipeline_id=1, profile=ExecutionProfile.LOCAL)
    job = engine.get_job_status(job_id)
    
    assert job is not None
    assert job.job_id_remote == job_id


def test_cancel_job(engine):
    """Test job cancellation."""
    sample = Sample(
        name="test_sample",
        data_path="./data/test.fastq",
        file_format="fastq"
    )
    
    job_id = engine.submit_job(sample, pipeline_id=1, profile=ExecutionProfile.LOCAL)
    success = engine.cancel_job(job_id)
    
    assert success is True
    assert engine.get_job_status(job_id).status == "cancelled"

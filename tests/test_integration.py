"""Integration tests for full pipeline."""
import pytest
from src.models.pipeline import Sample, Pipeline, ExecutionProfile, JobStatus
from src.orchestration.engine import OrchestrationEngine
from src.validation.data_validator import DataValidator
from pathlib import Path
import tempfile


@pytest.fixture
def sample_fastq():
    """Create test FASTQ file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.fastq', delete=False) as f:
        f.write("@READ1\nACGT\n+\nIIII\n")
        return f.name


@pytest.fixture
def engine():
    """Orchestration engine instance."""
    return OrchestrationEngine()


class TestPipelineSubmission:
    """Test pipeline submission workflow."""
    
    def test_submit_single_sample(self, engine, sample_fastq):
        """Test submitting single sample."""
        sample = Sample(
            name="test_sample",
            data_path=sample_fastq,
            file_format="fastq",
            size_bytes=100
        )
        
        pipeline = Pipeline(
            name="test_pipe",
            version="1.0",
            nextflow_script="test.nf",
            parameters={}
        )
        
        job = engine.submit_job([sample], pipeline, ExecutionProfile.LOCAL)
        assert job is not None
        assert job.status == JobStatus.QUEUED
        assert job.sample_id == "test_sample"
    
    def test_submit_batch_samples(self, engine, sample_fastq):
        """Test submitting batch of samples."""
        samples = [
            Sample(
                name=f"sample_{i}",
                data_path=sample_fastq,
                file_format="fastq",
                size_bytes=100
            )
            for i in range(5)
        ]
        
        pipeline = Pipeline(
            name="batch_pipe",
            version="1.0",
            nextflow_script="test.nf",
            parameters={}
        )
        
        job = engine.submit_job(samples, pipeline, ExecutionProfile.LOCAL)
        assert job is not None
        assert len(samples) == 5


class TestJobTracking:
    """Test job status tracking."""
    
    def test_job_status_tracking(self, engine, sample_fastq):
        """Test job status updates."""
        sample = Sample(
            name="track_test",
            data_path=sample_fastq,
            file_format="fastq",
            size_bytes=100
        )
        
        pipeline = Pipeline(
            name="track_pipe",
            version="1.0",
            nextflow_script="test.nf",
            parameters={}
        )
        
        job = engine.submit_job([sample], pipeline, ExecutionProfile.LOCAL)
        job_id = job.id
        
        # Check status retrieval
        retrieved = engine.get_job_status(job_id)
        assert retrieved is not None
        assert retrieved.id == job_id
        assert retrieved.status == JobStatus.QUEUED
    
    def test_list_jobs_by_status(self, engine, sample_fastq):
        """Test filtering jobs by status."""
        pipeline = Pipeline(
            name="list_pipe",
            version="1.0",
            nextflow_script="test.nf",
            parameters={}
        )
        
        for i in range(3):
            sample = Sample(
                name=f"list_sample_{i}",
                data_path=sample_fastq,
                file_format="fastq",
                size_bytes=100
            )
            engine.submit_job([sample], pipeline, ExecutionProfile.LOCAL)
        
        queued_jobs = engine.list_jobs(status=JobStatus.QUEUED.name)
        assert len(queued_jobs) >= 3


class TestProfileSelection:
    """Test execution profile selection logic."""
    
    def test_profile_selection_small(self, engine):
        """Test LOCAL profile for small workloads."""
        profile = engine.select_profile(5, False)
        assert profile == ExecutionProfile.LOCAL
    
    def test_profile_selection_medium(self, engine):
        """Test SLURM profile for medium workloads."""
        profile = engine.select_profile(50, False)
        assert profile == ExecutionProfile.SLURM
    
    def test_profile_selection_large(self, engine):
        """Test AWS Batch profile for large workloads."""
        profile = engine.select_profile(150, False)
        assert profile == ExecutionProfile.AWSBATCH
    
    def test_profile_selection_cloud(self, engine):
        """Test AWS Batch when cloud requested."""
        profile = engine.select_profile(10, use_cloud=True)
        assert profile == ExecutionProfile.AWSBATCH


class TestDataValidation:
    """Test data validation during submission."""
    
    def test_validate_fastq_content(self, sample_fastq):
        """Test FASTQ validation."""
        is_valid = DataValidator.validate_fastq(sample_fastq)
        assert is_valid is True
    
    def test_validate_missing_file(self):
        """Test validation of missing file."""
        is_valid = DataValidator.validate_fastq("/nonexistent/file.fastq")
        assert is_valid is False


class TestJobCancellation:
    """Test job cancellation."""
    
    def test_cancel_queued_job(self, engine, sample_fastq):
        """Test cancelling queued job."""
        sample = Sample(
            name="cancel_test",
            data_path=sample_fastq,
            file_format="fastq",
            size_bytes=100
        )
        
        pipeline = Pipeline(
            name="cancel_pipe",
            version="1.0",
            nextflow_script="test.nf",
            parameters={}
        )
        
        job = engine.submit_job([sample], pipeline, ExecutionProfile.LOCAL)
        success = engine.cancel_job(job.id)
        assert success is True

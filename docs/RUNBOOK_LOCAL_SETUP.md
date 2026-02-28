# Local Development Runbook

## Prerequisites

- Python 3.10+
- pip or conda
- Git
- Docker (optional, for containerized services)

## Step 1: Environment Setup

```bash
cd /home/jonyb/python_folder

# Create virtual environment
python3.10 -m venv venv

# Activate
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

## Step 2: Initialize Database

```bash
# Create data directory
mkdir -p data results logs

# Initialize SQLite database
python -c "from src.state.manager import StateManager; StateManager().close()"
```

## Step 3: Run Tests

```bash
# Unit tests
pytest tests/test_engine.py -v
pytest tests/test_validation.py -v

# Integration tests
pytest tests/test_integration.py -v

# All tests with coverage
pytest --cov=src tests/
```

## Step 4: Start API Server

```bash
# Run locally (development)
uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000

# API will be available at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

## Step 5: Submit Test Job via CLI

```bash
# Create test FASTQ file
echo -e "@READ1\nACGT\n+\nIIII\n" > test_sample.fastq

# Submit job
python scripts/cli.py submit --sample-path test_sample.fastq --format fastq

# Check status
python scripts/cli.py list-jobs

# Check specific job
python scripts/cli.py status --job-id <job_id>
```

## Step 6: Submit via API

```bash
# Submit pipeline
curl -X POST http://localhost:8000/api/v1/pipelines/submit \
  -H "Content-Type: application/json" \
  -d '{
    "samples": [{
      "name": "sample1",
      "data_path": "/path/to/file.fastq",
      "file_format": "fastq",
      "size_bytes": 1000
    }],
    "pipeline": {
      "name": "genomics-qc",
      "version": "1.0.0",
      "nextflow_script": "nextflow/main.nf",
      "parameters": {"min_quality": 20}
    },
    "execution_profile": "LOCAL"
  }'

# Get job status
curl http://localhost:8000/api/v1/jobs/<job_id>

# List jobs
curl http://localhost:8000/api/v1/jobs

# Get metrics
curl http://localhost:8000/api/v1/metrics
```

## Troubleshooting

### Port Already in Use
```bash
# Find process using port 8000
lsof -i :8000
kill -9 <PID>
```

### Database Locked
```bash
# Reset database
rm data/orchestrator.db
python -c "from src.state.manager import StateManager; StateManager().close()"
```

### Import Errors
```bash
# Check Python path
export PYTHONPATH="${PYTHONPATH}:/home/jonyb/python_folder"

# Verify imports
python -c "from src.models.pipeline import Sample; print('OK')"
```

### Tests Failing
```bash
# Check test dependencies
pip install pytest pytest-cov

# Run single test
pytest tests/test_engine.py::TestOrchestrationEngine::test_select_profile_local -v
```

## API Keys (Development)

Default development keys:
- Admin: `dev_key_admin`
- User: `dev_key_user`

Usage in requests:
```bash
curl -H "X-API-Key: dev_key_admin" http://localhost:8000/api/v1/jobs
```

## Logs

Logs are structured JSON format in `logs/` directory:

```bash
# View latest logs
tail -f logs/orchestrator.log | jq .

# Filter by level
jq 'select(.level=="ERROR")' logs/orchestrator.log
```

## Common Commands

```bash
# Health check
python scripts/cli.py health

# List all jobs
python scripts/cli.py list-jobs

# List failed jobs
python scripts/cli.py list-jobs --status-filter FAILED

# Cancel job
python scripts/cli.py cancel --job-id <job_id>
```

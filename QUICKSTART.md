# Quick Start Guide

## Installation

1. **Clone the repository:**
```bash
git clone https://github.com/JB5000/02_scalable_bioinformatics_pipeline_orchestrator.git
cd 02_scalable_bioinformatics_pipeline_orchestrator
```

2. **Install dependencies:**
```bash
pip install -e .
pip install fastapi uvicorn pydantic sqlalchemy
```

3. **Start the application with Docker:**
```bash
docker-compose up -d
```

## Quick Example

### 1. Submit a Pipeline Job

```bash
curl -X POST "http://localhost:8000/api/v1/pipelines/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "samples": [
      {
        "name": "sample1",
        "data_path": "./data/raw/sample1.fastq",
        "file_format": "fastq"
      }
    ],
    "pipeline_id": 1,
    "execution_profile": "local"
  }'
```

### 2. Check Job Status

```bash
curl "http://localhost:8000/api/v1/jobs/{job_id}"
```

### 3. Get System Metrics

```bash
curl "http://localhost:8000/api/v1/metrics"
```

## Running Locally Without Docker

```bash
# Install Python 3.10+
python --version

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e .

# Run the API server
uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000

# In another terminal, run tests
pytest tests/ -v
```

## File Structure

```
.
├── src/                          # Source code
│   ├── api/                      # FastAPI application
│   ├── models/                   # Pydantic models
│   ├── validation/               # Data validators
│   ├── orchestration/            # Orchestration engine
│   └── observability/            # Monitoring & logging
├── tests/                        # Test suite
├── configs/                      # Configuration files
├── nextflow/                     # Nextflow workflows
├── data/                         # Data directory
│   ├── raw/                      # Input data
│   └── processed/                # Output data
├── Dockerfile                    # Container definition
├── docker-compose.yml            # Local development setup
└── README.md                     # Full documentation
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/pipelines/submit` | Submit pipeline job |
| GET | `/api/v1/jobs/{job_id}` | Get job status |
| POST | `/api/v1/jobs/{job_id}/cancel` | Cancel job |
| GET | `/api/v1/jobs` | List all jobs |
| GET | `/api/v1/metrics` | Get system metrics |
| GET | `/health` | Health check |

## Common Tasks

### Submit Multiple Samples
```bash
curl -X POST "http://localhost:8000/api/v1/pipelines/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "samples": [
      {"name": "s1", "data_path": "./data/s1.fastq", "file_format": "fastq"},
      {"name": "s2", "data_path": "./data/s2.fastq", "file_format": "fastq"}
    ],
    "pipeline_id": 1
  }'
```

### Run Tests
```bash
pytest tests/ -v --cov=src
```

### View Database
```bash
# Using Docker Compose
docker-compose exec postgres psql -U orchestrator -d genomics_pipeline
```

## Configuration

Edit `configs/default.yaml` to customize:
- Execution profiles (local, SLURM, AWS Batch)
- Database settings
- API port and workers
- Logging level
- Job timeouts and retry logic

## Troubleshooting

**API not responding:**
```bash
curl http://localhost:8000/health
docker-compose logs api
```

**Database connection error:**
```bash
docker-compose ps  # Check if postgres is running
docker-compose logs postgres
```

**Jobs failing:**
- Check `/var/log/orchestrator.log`
- Review job logs via API: `/api/v1/jobs/{job_id}/logs`
- Validate input data with data validators

## Next Steps

1. **Setup Production:** Deploy to AWS/Kubernetes using Terraform
2. **Scale Up:** Configure SLURM or AWS Batch for large workloads
3. **Monitor:** Setup Prometheus/Grafana dashboards
4. **Extend:** Add custom Nextflow processes for your workflows

## Support & Documentation

- Full Architecture: [docs/architecture.md](docs/architecture.md)
- Implementation Plan: [docs/COMPLETION_PLAN.md](docs/COMPLETION_PLAN.md)
- API Documentation: http://localhost:8000/docs (when running)

---

For more information, see the [README.md](README.md) file.

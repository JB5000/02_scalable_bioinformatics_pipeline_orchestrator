"""State management for job persistence."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import asdict
from src.models import Job, Sample, Run


class StateManager:
    """Manages state persistence for jobs and samples."""
    
    def __init__(self, db_path: str = "data/orchestrator.db"):
        """Initialize state manager."""
        self.db_path = db_path
        self.conn = None
        self._init_db()
    
    def _init_db(self):
        """Initialize database."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
    
    def _create_tables(self):
        """Create database tables."""
        cursor = self.conn.cursor()
        
        # Samples table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                data_path TEXT NOT NULL,
                file_format TEXT,
                size_bytes INTEGER,
                status TEXT,
                created_at TIMESTAMP
            )
        ''')
        
        # Jobs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY,
                sample_id INTEGER,
                pipeline_id INTEGER,
                execution_profile TEXT,
                status TEXT,
                job_id_remote TEXT UNIQUE,
                submitted_at TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                error_message TEXT,
                FOREIGN KEY (sample_id) REFERENCES samples(id)
            )
        ''')
        
        # Metrics table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY,
                job_id INTEGER,
                duration_minutes REAL,
                cpu_hours REAL,
                memory_gb REAL,
                cost_usd REAL,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            )
        ''')
        
        # Runs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY,
                name TEXT,
                pipeline_id INTEGER,
                total_samples INTEGER,
                status TEXT,
                submitted_at TIMESTAMP,
                completed_at TIMESTAMP,
                total_cost_usd REAL
            )
        ''')
        
        self.conn.commit()
    
    def save_sample(self, sample: Sample) -> int:
        """Save sample to database."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO samples (name, data_path, file_format, size_bytes, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            sample.name,
            sample.data_path,
            sample.file_format,
            sample.size_bytes,
            sample.status,
            datetime.now()
        ))
        self.conn.commit()
        return cursor.lastrowid
    
    def save_job(self, job: Job) -> int:
        """Save job to database."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO jobs (sample_id, pipeline_id, execution_profile, status, job_id_remote, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            job.sample_id,
            job.pipeline_id,
            job.execution_profile.value if hasattr(job.execution_profile, 'value') else job.execution_profile,
            job.status.value if hasattr(job.status, 'value') else job.status,
            job.job_id_remote,
            job.submitted_at
        ))
        self.conn.commit()
        return cursor.lastrowid
    
    def update_job_status(self, job_id_remote: str, status: str):
        """Update job status."""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE jobs SET status = ? WHERE job_id_remote = ?
        ''', (status, job_id_remote))
        self.conn.commit()
    
    def get_job(self, job_id_remote: str) -> Optional[Dict]:
        """Get job from database."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM jobs WHERE job_id_remote = ?', (job_id_remote,))
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def list_jobs(self, status: Optional[str] = None) -> List[Dict]:
        """List jobs, optionally filtered by status."""
        cursor = self.conn.cursor()
        if status:
            cursor.execute('SELECT * FROM jobs WHERE status = ?', (status,))
        else:
            cursor.execute('SELECT * FROM jobs')
        return [dict(row) for row in cursor.fetchall()]
    
    def save_run(self, run: Run) -> int:
        """Save run to database."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO runs (name, pipeline_id, total_samples, status, submitted_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            run.name,
            run.pipeline_id,
            run.total_samples,
            run.status,
            datetime.now()
        ))
        self.conn.commit()
        return cursor.lastrowid
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()

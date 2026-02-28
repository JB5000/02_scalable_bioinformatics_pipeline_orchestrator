"""Tests for data validation."""
import pytest
from src.validation import DataValidator


def test_validate_fastq_missing_file():
    """Test validation of missing file."""
    is_valid, error = DataValidator.validate_fastq("non_existent_file.fastq")
    assert is_valid is False
    assert "not found" in error.lower()


def test_validate_bam_missing_file():
    """Test validation of missing BAM file."""
    is_valid, error = DataValidator.validate_bam("non_existent_file.bam")
    assert is_valid is False


def test_validate_vcf_missing_file():
    """Test validation of missing VCF file."""
    is_valid, error = DataValidator.validate_vcf("non_existent_file.vcf")
    assert is_valid is False


def test_validate_unknown_format():
    """Test validation with unknown format."""
    is_valid, error = DataValidator.validate_file("test.txt", "unknown")
    assert is_valid is False
    assert "unknown" in error.lower()

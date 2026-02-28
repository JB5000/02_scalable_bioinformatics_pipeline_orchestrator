"""Data validation for bioinformatics files."""
import os
import gzip
import hashlib
from pathlib import Path
from typing import Tuple, Optional


class DataValidator:
    """Validates genomics data files."""
    
    VALID_FORMATS = {'.fastq', '.fq', '.bam', '.vcf', '.gz'}
    MIN_FILE_SIZE = 1024  # 1KB
    MAX_FILE_SIZE = 500 * 1024 * 1024 * 1024  # 500GB
    
    @classmethod
    def validate_fastq(cls, filepath: str) -> Tuple[bool, Optional[str]]:
        """Validate FASTQ file format."""
        try:
            if not os.path.exists(filepath):
                return False, f"File not found: {filepath}"
            
            file_size = os.path.getsize(filepath)
            if file_size < cls.MIN_FILE_SIZE:
                return False, f"File too small: {file_size} bytes"
            if file_size > cls.MAX_FILE_SIZE:
                return False, f"File too large: {file_size} bytes"
            
            # Check first few lines
            open_func = gzip.open if filepath.endswith('.gz') else open
            with open_func(filepath, 'rt') as f:
                lines_to_check = 4
                for i in range(lines_to_check):
                    line = f.readline()
                    if not line:
                        return False, "File too short"
                    
                    # Check line format
                    if i % 4 == 0 and not line.startswith('@'):
                        return False, "Invalid FASTQ format (line should start with @)"
                    elif i % 4 == 2 and not line.startswith('+'):
                        return False, "Invalid FASTQ format (line should start with +)"
            
            return True, None
        except Exception as e:
            return False, f"Validation error: {str(e)}"
    
    @classmethod
    def validate_bam(cls, filepath: str) -> Tuple[bool, Optional[str]]:
        """Validate BAM file format (basic check)."""
        try:
            if not os.path.exists(filepath):
                return False, f"File not found: {filepath}"
            
            file_size = os.path.getsize(filepath)
            if file_size < cls.MIN_FILE_SIZE:
                return False, f"File too small"
            
            # Check BAM magic bytes
            with open(filepath, 'rb') as f:
                magic = f.read(4)
                if magic != b'BAM\x01':
                    return False, "Invalid BAM magic bytes"
            
            return True, None
        except Exception as e:
            return False, f"Validation error: {str(e)}"
    
    @classmethod
    def validate_vcf(cls, filepath: str) -> Tuple[bool, Optional[str]]:
        """Validate VCF file format."""
        try:
            if not os.path.exists(filepath):
                return False, f"File not found: {filepath}"
            
            file_size = os.path.getsize(filepath)
            if file_size < cls.MIN_FILE_SIZE:
                return False, f"File too small"
            
            open_func = gzip.open if filepath.endswith('.gz') else open
            with open_func(filepath, 'rt') as f:
                first_line = f.readline().strip()
                if not first_line.startswith('##fileformat=VCF'):
                    return False, "Missing VCF header"
            
            return True, None
        except Exception as e:
            return False, f"Validation error: {str(e)}"
    
    @classmethod
    def validate_file(cls, filepath: str, file_format: str) -> Tuple[bool, Optional[str]]:
        """Generic file validation."""
        if file_format.lower() in ['fastq', 'fq']:
            return cls.validate_fastq(filepath)
        elif file_format.lower() == 'bam':
            return cls.validate_bam(filepath)
        elif file_format.lower() == 'vcf':
            return cls.validate_vcf(filepath)
        else:
            return False, f"Unknown file format: {file_format}"
    
    @classmethod
    def calculate_checksum(cls, filepath: str, algorithm: str = 'md5') -> str:
        """Calculate file checksum."""
        hash_func = hashlib.new(algorithm)
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_func.update(chunk)
        return hash_func.hexdigest()

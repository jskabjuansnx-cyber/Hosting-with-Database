"""
Security utilities: scan scripts for dangerous patterns before running.
"""
import re
import logging
from config import DANGEROUS_PATTERNS

logger = logging.getLogger(__name__)


def scan_file(file_path: str) -> list[str]:
    """
    Scan a script file for dangerous patterns.
    Returns a list of warning strings (empty = safe).
    """
    warnings = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, content):
                warnings.append(f"Dangerous pattern detected: `{pattern}`")
    except Exception as e:
        logger.error(f"Error scanning file {file_path}: {e}")
        warnings.append(f"Could not scan file: {e}")
    return warnings

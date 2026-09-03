
# observability/detectors/pii_detector.py
"""Detect personally identifiable information in outputs."""

import logging
import re
from typing import Tuple, List
logger = logging.getLogger(__name__)


pii_patterns = {
            "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "phone": r"\b(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})\b",
            "ssn": r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0{4})\d{4}\b",
            "credit_card": r"\b(?:\d{4}[-]?){3}\d{4}\b",
             "aadhaar_like": re.compile(r"\b\d{12}\b"),
            "ip_address": r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
        }
    

class PIIDetector:
    """
    Detects PII (Personally Identifiable Information) in LLM output.
    
    Patterns:
    - Email addresses
    - Phone numbers
    - Social security numbers
    - Credit card numbers
    - Names + addresses
    """
    

   
def detect_pii(text: str) -> Tuple[float, List[str]]:
    """
    Returns (score, detected_types)
    Score is proportional to number of detections (clipped to 1.0)
    """
    detected = []
    if not text:
        return 0.0, detected
    for label, pat in pii_patterns.items():
        if pat.search(text):
            detected.append(label)
    if not detected:
        return 0.0, []
    # simple mapping: more types => higher score
    score = min(1.0, 0.5 + 0.1 * len(detected))
    return score, detected


def redact_pii(text: str) -> str:
    """
    Returns redacted text (replace PII with placeholders)
    """
    redacted = text
    for label, pat in pii_patterns.items():
        redacted = pat.sub(f"<{label.upper()}_REDACTED>", redacted)
    return redacted
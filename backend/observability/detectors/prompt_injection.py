
# observability/detectors/prompt_injection.py
"""Detect prompt injection attacks."""

import logging
import re

logger = logging.getLogger(__name__)


class PromptInjectionDetector:
    """
    Detects potential prompt injection attacks.
    
    Patterns:
    - SQL injection: SELECT, DROP, DELETE, INSERT
    - Command injection: $(), ``, ${}, |, ;
    - Prompt override: "ignore previous", "system override", "as an AI"
    - Jailbreak: "pretend you", "act as if", "roleplay"
    """
    
    def __init__(self):
        self.injection_patterns = {
            "sql_injection": [
                r"\bSELECT\b", r"\bDROP\b", r"\bDELETE\b", r"\bINSERT\b",
                r"\bUPDATE\b", r"\bUNION\b", r"\bALTER\b"
            ],
            "command_injection": [
                r"\$\(", r"`", r"\$\{", r"\|", r";", r"&&", r"\|\|"
            ],
            "prompt_override": [
                r"ignore previous", r"forget", r"system override",
                r"disregard", r"don't follow", r"forget all"
            ],
            "jailbreak": [
                r"pretend you", r"act as if", r"roleplay", r"imagine",
                r"hypothetically", r"in fiction", r"repeat after me",
            ]
        }
    
    def detect(self, prompt: str) -> float:
        """
        Analyze prompt for injection indicators.
        Returns risk score 0-1 where 1.0 = high risk.
        """
        risk_score = 0.0
        prompt_lower = prompt.lower()
        
        for category, patterns in self.injection_patterns.items():
            matches = 0
            for pattern in patterns:
                if re.search(pattern, prompt_lower, re.IGNORECASE):
                    matches += 1
            
            if matches > 0:
                category_risk = min(1.0, matches * 0.25)
                risk_score += category_risk
        
        # Normalize
        risk_score = min(1.0, risk_score)
        
        if risk_score > 0.5:
            logger.warning(f"Prompt injection risk detected: {risk_score:.2f}")
        
        return risk_score

# observability/scoring/reliability_index.py
"""Compute composite reliability score."""

import logging

logger = logging.getLogger(__name__)


class ReliabilityIndex:
    """
    Computes an overall reliability score for an LLM output.
    
    Score: 0-1 (1.0 = fully reliable, 0.0 = unreliable)
    
    Factors (with weights):
    - Hallucination (40%) - inverted (low hallucination = high score)
    - Injection Risk (30%) - inverted (low risk = high score)
    - PII Risk (20%) - inverted (no PII = high score)
    - Context Loss (10%) - inverted (no loss = high score)
    - Latency (bonus/penalty based on SLA)
    
    Example:
        - Low hallucination (0.1) = 0.9 reliability contribution (40%)
        - No injection risk = 1.0 reliability contribution (30%)
        - Latency within SLA = no penalty
        → Overall: (0.9 * 0.4) + (1.0 * 0.3) + ... = high score
    """
    
    def __init__(self):
        self.weights = {
            "hallucination": 0.4,
            "injection_risk": 0.3,
            "pii_risk": 0.2,
            "context_loss": 0.1
        }
        
        self.latency_sla_ms = 5000  # 5 second SLA
    
    def compute(
        self,
        hallucination_score: float,
        injection_risk: float,
        pii_risk: float,
        context_loss_score: float,
        latency_ms: float
    ) -> float:
        """
        Compute overall reliability score.
        
        Args:
            hallucination_score: 0-1 (1 = confident, 0 = hallucinated)
            injection_risk: 0-1 (0 = safe, 1 = high risk)
            pii_risk: 0-1 (0 = no PII, 1 = PII found)
            context_loss_score: 0-1 (0 = no loss, 1 = loss detected)
            latency_ms: Response time in milliseconds
        
        Returns:
            Composite reliability score 0-1
        """
        # Convert risks to reliability contributions (invert them)
        hallucination_contrib = hallucination_score * self.weights["hallucination"]
        injection_contrib = (1.0 - injection_risk) * self.weights["injection_risk"]
        pii_contrib = (1.0 - pii_risk) * self.weights["pii_risk"]
        context_contrib = (1.0 - context_loss_score) * self.weights["context_loss"]
        
        # Base reliability
        base_score = hallucination_contrib + injection_contrib + pii_contrib + context_contrib
        
        # Latency penalty
        if latency_ms > self.latency_sla_ms:
            latency_penalty = min(0.2, (latency_ms - self.latency_sla_ms) / 10000)
            base_score = max(0.0, base_score - latency_penalty)
        
        # Ensure bounds
        final_score = max(0.0, min(1.0, base_score))
        
        logger.debug(
            f"Reliability: hallucination={hallucination_contrib:.2f}, "
            f"injection={injection_contrib:.2f}, pii={pii_contrib:.2f}, "
            f"context={context_contrib:.2f} → final={final_score:.2f}"
        )
        
        return final_score
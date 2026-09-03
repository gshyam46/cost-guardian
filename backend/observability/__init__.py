# observability/__init__.py
"""
LLM Cost Guardian - Observability Module

This module provides comprehensive observability for LLM applications:
- Cost tracking (per-call, per-agent, per-user)
- Hallucination detection
- Security threat detection (prompt injection, PII exposure)
- Context loss detection
- Reliability scoring
- Automated incident creation
- Datadog integration

Usage:
    from observability.telemetry import TelemetryCollector
    
    telemetry = TelemetryCollector()
    
    # After each agent execution:
    metrics = telemetry.submit_agent_execution(
        agent_name="profile_analyst",
        input_prompt="...",
        output_response="...",
        model="groq/llama-3.3-70b",
        tokens_used=1500,
        latency_ms=2300,
        user_id="user123",
        session_id="sess456",
        agent_index=1,
        total_agents=5
    )
    
    # Returns: {
    #     "agent": "profile_analyst",
    #     "cost_usd": 0.0,
    #     "hallucination_score": 0.95,
    #     "injection_risk": 0.0,
    #     "pii_risk": 0.0,
    #     "context_loss": false,
    #     "reliability_score": 0.95,
    #     "latency_ms": 2300,
    #     "tokens": 1500,
    #     "timestamp": "2024-12-10T10:30:45.123Z"
    # }
"""

from observability.telemetry import TelemetryCollector
from observability.detectors.hallucination import HallucinationDetector
from observability.detectors.context_loss import ContextLossDetector
from observability.detectors.prompt_injection import PromptInjectionDetector
from observability.detectors.pii_detector import PIIDetector
from observability.scoring.cost_model import CostModel
from observability.scoring.reliability_index import ReliabilityIndex
from observability.incidents.create_incident import IncidentCreator
from observability.incidents.remediation_webhook import RemediationHandler

__all__ = [
    "TelemetryCollector",
    "HallucinationDetector",
    "ContextLossDetector",
    "PromptInjectionDetector",
    "PIIDetector",
    "CostModel",
    "ReliabilityIndex",
    "IncidentCreator",
    "RemediationHandler",
]
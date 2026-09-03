# observability/telemetry.py
"""
Central telemetry collection and submission to Datadog.
This module acts as the "nerve center" of observability.

Flow:
1. After each agent runs, call telemetry.submit_agent_execution()
2. Telemetry calculates all metrics (cost, hallucination, etc.)
3. Sends to Datadog as custom metrics + logs
4. Returns metadata for dashboard display

No dependencies on other observability modules - they are called internally.
"""

import logging
import time
import os
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from datadog_api_client.v1 import ApiClient, Configuration
from datadog_api_client.v1.api.metrics_api import MetricsApi
from datadog_api_client.v1.model.metric_payload import MetricPayload
from datadog_api_client.v1.model.metric_series import MetricSeries
from datadog_api_client.v1.model.metric_point import MetricPoint
from ddtrace import tracer
import json

from observability.detectors.hallucination import HallucinationDetector
from observability.detectors.context_loss import ContextLossDetector
from observability.detectors.prompt_injection import PromptInjectionDetector
from observability.detectors.pii_detector import PIIDetector
from observability.scoring.cost_model import CostModel
from observability.scoring.reliability_index import ReliabilityIndex
from observability.incidents.create_incident import IncidentCreator

logger = logging.getLogger(__name__)


class TelemetryCollector:
    """
    Collects and submits all observability data to Datadog.
    
    Usage in orchestrator:
        telemetry = TelemetryCollector()
        
        # After each agent runs:
        agent_result = await agent.run(context)
        telemetry.submit_agent_execution(
            agent_name="profile_analyst",
            input_prompt=user_prompt,
            output_response=agent_result.text,
            model="groq/llama-3.3-70b",
            tokens_used=usage.total_tokens,
            latency_ms=response_time,
            user_id="user123",
            session_id="sess456"
        )
    """

    def __init__(self):
        self.hallucination_detector = HallucinationDetector()
        self.context_loss_detector = ContextLossDetector()
        self.injection_detector = PromptInjectionDetector()
        self.pii_detector = PIIDetector()
        self.cost_model = CostModel()
        self.reliability_index = ReliabilityIndex()
        self.incident_creator = IncidentCreator()
        self.datadog_api = self._init_datadog()

    def _init_datadog(self) -> Optional[MetricsApi]:
        """Initialize Datadog API client."""
        try:
            api_key = os.getenv("DD_API_KEY")
            app_key = os.getenv("DD_APP_KEY")
            site = os.getenv("DD_SITE", "datadoghq.eu")
            
            if not api_key or not app_key:
                logger.warning("DD_API_KEY or DD_APP_KEY not set. Metrics won't be submitted.")
                return None
            
            config = Configuration()
            config.api_key["apiKeyAuth"] = api_key
            config.api_key["appKeyAuth"] = app_key
            config.server_variables["site"] = site
            
            api_client = ApiClient(config)
            return MetricsApi(api_client)
        except Exception as e:
            logger.error(f"Failed to initialize Datadog API: {e}")
            return None

    def submit_agent_execution(
        self,
        agent_name: str,
        input_prompt: str,
        output_response: str,
        model: str,
        tokens_used: int,
        latency_ms: float,
        user_id: str,
        session_id: str,
        agent_index: int = 1,
        total_agents: int = 5,
        extra_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Submit a single agent execution to Datadog.
        
        Returns: Dict with all computed metrics (for display in UI)
        """
        timestamp = int(time.time())
        
        # 1. Calculate cost
        cost_usd = self.cost_model.calculate(model, tokens_used)
        
        # 2. Detect hallucination
        hallucination_score = self.hallucination_detector.detect(
            prompt=input_prompt,
            response=output_response
        )
        
        # 3. Detect prompt injection
        injection_risk = self.injection_detector.detect(input_prompt)
        
        # 4. Detect PII exposure
        pii_found = self.pii_detector.detect(output_response)
        pii_risk = 1.0 if pii_found else 0.0
        
        # 5. Detect context loss (basic heuristic)
        context_lost = self.context_loss_detector.detect(
            prompt_length=len(input_prompt),
            response_length=len(output_response),
            latency_ms=latency_ms
        )
        context_loss_score = 1.0 if context_lost else 0.0
        
        # 6. Calculate reliability index (composite score)
        reliability_score = self.reliability_index.compute(
            hallucination_score=hallucination_score,
            injection_risk=injection_risk,
            pii_risk=pii_risk,
            context_loss_score=context_loss_score,
            latency_ms=latency_ms
        )
        
        # Build tags
        tags = [
            f"agent:{agent_name}",
            f"model:{model.split('/')[-1]}",
            f"provider:{model.split('/')[0]}",
            f"user:{user_id}",
            f"session:{session_id}",
            f"agent_position:{agent_index}/{total_agents}",
        ]
        
        # 7. Send metrics to Datadog
        self._submit_metrics(
            timestamp=timestamp,
            cost=cost_usd,
            hallucination=hallucination_score,
            injection_risk=injection_risk,
            pii_risk=pii_risk,
            context_loss=context_loss_score,
            reliability=reliability_score,
            latency_ms=latency_ms,
            tokens=tokens_used,
            tags=tags
        )
        
        # 8. Send structured log to Datadog
        self._submit_log(
            agent_name=agent_name,
            model=model,
            cost=cost_usd,
            hallucination_score=hallucination_score,
            injection_risk=injection_risk,
            pii_risk=pii_risk,
            context_loss=context_lost,
            reliability_score=reliability_score,
            latency_ms=latency_ms,
            tokens=tokens_used,
            user_id=user_id,
            session_id=session_id,
            tags=tags
        )
        
        # 9. Tag the Datadog trace
        span = tracer.current_span()
        if span:
            span.set_tag("llm.cost_usd", cost_usd)
            span.set_tag("llm.hallucination_score", hallucination_score)
            span.set_tag("llm.injection_risk", injection_risk)
            span.set_tag("llm.pii_risk", pii_risk)
            span.set_tag("llm.context_loss", context_lost)
            span.set_tag("llm.reliability_score", reliability_score)
        
        # 10. Check if incident should be created
        self._check_and_create_incident(
            agent_name=agent_name,
            hallucination_score=hallucination_score,
            injection_risk=injection_risk,
            pii_risk=pii_risk,
            reliability_score=reliability_score,
            cost_usd=cost_usd,
            user_id=user_id,
            tags=tags
        )
        
        logger.info(
            f"[Telemetry] {agent_name}: cost=${cost_usd:.6f}, "
            f"reliability={reliability_score:.2f}, "
            f"hallucination={hallucination_score:.2f}"
        )
        
        # Return for UI display
        return {
            "agent": agent_name,
            "cost_usd": cost_usd,
            "hallucination_score": hallucination_score,
            "injection_risk": injection_risk,
            "pii_risk": pii_risk,
            "context_loss": context_lost,
            "reliability_score": reliability_score,
            "latency_ms": latency_ms,
            "tokens": tokens_used,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def _submit_metrics(
        self,
        timestamp: int,
        cost: float,
        hallucination: float,
        injection_risk: float,
        pii_risk: float,
        context_loss: float,
        reliability: float,
        latency_ms: float,
        tokens: int,
        tags: list
    ):
        """Submit metrics to Datadog."""
        if not self.datadog_api:
            return
        
        try:
            series = [
                MetricSeries(
                    metric="llm.cost_usd",
                    type=0,  # Gauge
                    points=[MetricPoint(timestamp=timestamp, value=cost)],
                    tags=tags
                ),
                MetricSeries(
                    metric="llm.hallucination_score",
                    type=0,
                    points=[MetricPoint(timestamp=timestamp, value=hallucination)],
                    tags=tags
                ),
                MetricSeries(
                    metric="llm.injection_risk",
                    type=0,
                    points=[MetricPoint(timestamp=timestamp, value=injection_risk)],
                    tags=tags
                ),
                MetricSeries(
                    metric="llm.pii_risk",
                    type=0,
                    points=[MetricPoint(timestamp=timestamp, value=pii_risk)],
                    tags=tags
                ),
                MetricSeries(
                    metric="llm.context_loss",
                    type=0,
                    points=[MetricPoint(timestamp=timestamp, value=context_loss)],
                    tags=tags
                ),
                MetricSeries(
                    metric="llm.reliability_score",
                    type=0,
                    points=[MetricPoint(timestamp=timestamp, value=reliability)],
                    tags=tags
                ),
                MetricSeries(
                    metric="llm.latency_ms",
                    type=0,
                    points=[MetricPoint(timestamp=timestamp, value=latency_ms)],
                    tags=tags
                ),
                MetricSeries(
                    metric="llm.tokens_used",
                    type=1,  # Count
                    points=[MetricPoint(timestamp=timestamp, value=tokens)],
                    tags=tags
                ),
            ]
            
            payload = MetricPayload(series=series)
            self.datadog_api.submit_metrics(payload)
        except Exception as e:
            logger.error(f"Failed to submit metrics to Datadog: {e}")

    def _submit_log(
        self,
        agent_name: str,
        model: str,
        cost: float,
        hallucination_score: float,
        injection_risk: float,
        pii_risk: float,
        context_loss: bool,
        reliability_score: float,
        latency_ms: float,
        tokens: int,
        user_id: str,
        session_id: str,
        tags: list
    ):
        """Submit structured log to Datadog."""
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": f"Agent execution: {agent_name}",
            "agent": agent_name,
            "model": model,
            "cost_usd": cost,
            "hallucination_score": hallucination_score,
            "injection_risk": injection_risk,
            "pii_risk": pii_risk,
            "context_loss": context_loss,
            "reliability_score": reliability_score,
            "latency_ms": latency_ms,
            "tokens": tokens,
            "user_id": user_id,
            "session_id": session_id,
            "tags": tags,
            "severity": "warning" if reliability_score < 0.7 else "info"
        }
        
        logger.info(json.dumps(log_data))

    def _check_and_create_incident(
        self,
        agent_name: str,
        hallucination_score: float,
        injection_risk: float,
        pii_risk: float,
        reliability_score: float,
        cost_usd: float,
        user_id: str,
        tags: list
    ):
        """Create incident if thresholds are breached."""
        incidents = []
        
        # High hallucination risk
        if hallucination_score < 0.5:
            incidents.append({
                "title": f"High Hallucination Risk in {agent_name}",
                "severity": "SEV-2",
                "description": f"Agent {agent_name} produced output with hallucination score {hallucination_score:.2f} (threshold: 0.5)"
            })
        
        # High injection risk
        if injection_risk > 0.7:
            incidents.append({
                "title": f"Prompt Injection Detected in {agent_name}",
                "severity": "SEV-1",
                "description": f"Prompt injection risk {injection_risk:.2f} exceeds threshold (0.7)"
            })
        
        # PII exposure
        if pii_risk > 0.5:
            incidents.append({
                "title": f"PII Exposure Detected in {agent_name}",
                "severity": "SEV-1",
                "description": f"Personally identifiable information detected in output"
            })
        
        # Low reliability
        if reliability_score < 0.6:
            incidents.append({
                "title": f"Low Reliability Score: {agent_name}",
                "severity": "SEV-3",
                "description": f"Agent reliability score {reliability_score:.2f} below acceptable threshold (0.6)"
            })
        
        # Create all incidents
        for incident in incidents:
            self.incident_creator.create(
                title=incident["title"],
                severity=incident["severity"],
                description=incident["description"],
                tags=tags + [f"user:{user_id}"]
            )
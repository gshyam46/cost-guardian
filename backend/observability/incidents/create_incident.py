# observability/incidents/create_incident.py
"""Create incidents in Datadog when thresholds are breached."""

import logging
import os
from typing import List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class IncidentCreator:
    """
    Creates incidents in Datadog when observability thresholds are breached.
    
    Severity levels:
    - SEV-1: Critical (security, PII, data loss)
    - SEV-2: High (hallucination, reliability issues)
    - SEV-3: Medium (optimization opportunities)
    """
    
    def __init__(self):
        self.api_key = os.getenv("DD_API_KEY")
        self.app_key = os.getenv("DD_APP_KEY")
        self.site = os.getenv("DD_SITE", "datadoghq.eu")
        
        # For now, we'll log incidents. In production, use Datadog API:
        # from datadog_api_client.v2 import ApiClient, Configuration
        # from datadog_api_client.v2.api.incidents_api import IncidentsApi
    
    def create(
        self,
        title: str,
        severity: str,
        description: str,
        tags: List[str]
    ) -> bool:
        """
        Create an incident.
        
        Args:
            title: Short incident title
            severity: SEV-1, SEV-2, SEV-3
            description: Detailed description
            tags: List of tags (e.g., ["agent:profile_analyst", "user:user123"])
        
        Returns:
            True if created successfully
        """
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            
            incident_data = {
                "timestamp": timestamp,
                "title": title,
                "severity": severity,
                "description": description,
                "tags": tags,
                "status": "created"
            }
            
            # Log the incident (can be picked up by Datadog logging)
            logger.warning(
                f"[INCIDENT {severity}] {title} - {description}",
                extra={
                    "incident": incident_data
                }
            )
            
            # TODO: In production, use Datadog Incidents API:
            # api_instance = IncidentsApi(api_client)
            # api_instance.create_incident(...)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create incident: {e}")
            return False
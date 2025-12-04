"""Base agent class and shared context for the agentic system.

This module defines the foundation for all agents in the system.
Each agent inherits from BaseAgent and implements the run() method.
Agents share state through AgentContext which flows through the pipeline.

Observability: Each agent logs its inputs, outputs, and timing for future
Datadog/LangSmith integration. The structured logging format is designed
to be easily parsed by observability tools.
"""
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from ..llm_fallback import LlmChat




class UserMessage:
    def __init__(self, text: str):
        self.text = text
from config import get_llm_api_key

logger = logging.getLogger(__name__)


class AgentContext(BaseModel):
    """Shared context/state object that flows through all agents.
    
    This context accumulates results from each agent and is passed
    to subsequent agents in the pipeline.
    """
    # Raw user inputs (from profile)
    raw_profile: Dict[str, Any] = {}
    
    # Profile Analyst output
    profile_summary: Optional[Dict[str, Any]] = None
    
    # Market Hunter output
    candidate_niches: list = Field(default_factory=list)
    
    # Fit Evaluator output
    niche_evaluations: list = Field(default_factory=list)
    selected_niches: list = Field(default_factory=list)
    
    # Roadmap Architect output
    roadmap: Optional[Dict[str, Any]] = None
    
    # Tooling Advisor output
    tool_recommendations: list = Field(default_factory=list)
    
    # Metadata for observability
    agent_traces: list = Field(default_factory=list)


class BaseAgent(ABC):
    """Base class for all agents in the system.
    
    Each agent:
    1. Takes the shared AgentContext
    2. Calls Gemini with a carefully designed prompt
    3. Parses the response into structured data
    4. Updates the AgentContext
    5. Logs trace information for observability
    
    To add a new agent:
    1. Create a new class inheriting from BaseAgent
    2. Implement the run() method
    3. Define your prompt in get_system_prompt() and get_user_prompt()
    4. Parse the response in parse_response()
    """
    
    name: str = "base_agent"
    description: str = "Base agent"
    
    def __init__(self):
        self.api_key = get_llm_api_key()
        self.llm = LlmChat(
            api_key=self.api_key,
            session_id=f"{self.name}_{datetime.now(timezone.utc).isoformat()}",
            system_message=self.get_system_prompt()
        ).with_model("gemini", "gemini-2.0-flash")
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        pass
    
    @abstractmethod
    def get_user_prompt(self, context: AgentContext) -> str:
        """Return the user prompt based on context."""
        pass
    
    @abstractmethod
    def parse_response(self, response: str, context: AgentContext) -> AgentContext:
        """Parse the LLM response and update context."""
        pass
    
    async def run(self, context: AgentContext) -> AgentContext:
        """Execute the agent and update context.
        
        This method handles:
        - Logging for observability
        - Error handling
        - Timing metrics
        """
        start_time = datetime.now(timezone.utc)
        
        logger.info(f"[{self.name}] Starting agent execution")
        
        try:
            user_prompt = self.get_user_prompt(context)
            
            # Call LLM
            response = await self.llm.send_message(UserMessage(text=user_prompt))
            
            # Parse and update context
            context = self.parse_response(response, context)
            
            # Log trace for observability
            end_time = datetime.now(timezone.utc)
            trace = {
                "agent": self.name,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_ms": (end_time - start_time).total_seconds() * 1000,
                "status": "success",
                "prompt_length": len(user_prompt),
                "response_length": len(response)
            }
            context.agent_traces.append(trace)
            
            logger.info(f"[{self.name}] Completed in {trace['duration_ms']:.2f}ms")
            
        except Exception as e:
            logger.error(f"[{self.name}] Error: {str(e)}")
            context.agent_traces.append({
                "agent": self.name,
                "start_time": start_time.isoformat(),
                "status": "error",
                "error": str(e)
            })
            raise
        
        return context
    
    def extract_json(self, text: str) -> Dict[str, Any]:
        """Extract JSON from LLM response, handling markdown code blocks."""
        # Try to find JSON in code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:end].strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find any JSON object in the text
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                return json.loads(json_match.group())
            raise ValueError(f"Could not parse JSON from response: {text[:200]}")

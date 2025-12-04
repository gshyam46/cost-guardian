"""Agent Orchestrator using LangGraph for state management and observability.

This module orchestrates the flow of agents in the niche discovery pipeline.
It uses a simple sequential flow but is designed to be easily extended to
more complex workflows (parallel execution, conditional branching, etc.).

Observability: The orchestrator logs the entire pipeline execution with
timing metrics for each agent, making it easy to integrate with Datadog,
LangSmith, or other observability tools.
"""
import logging
from typing import Dict, Any, TypedDict
from datetime import datetime, timezone

from langgraph.graph import StateGraph, END

from services.agents import (
    AgentContext,
    ProfileAnalystAgent,
    MarketHunterAgent,
    FitEvaluatorAgent,
    RoadmapArchitectAgent,
    ToolingAdvisorAgent
)
from models.report import (
    NicheReport, ProfileSummary, Niche, Roadmap, RoadmapPhase, ToolRecommendation
)

logger = logging.getLogger(__name__)


class OrchestratorState(TypedDict):
    """State object for LangGraph orchestration."""
    context: Dict[str, Any]
    current_agent: str
    status: str
    error: str


class NicheDiscoveryOrchestrator:
    """Orchestrates the agent pipeline for niche discovery.
    
    Pipeline flow:
    1. Profile Analyst -> Summarizes user profile
    2. Market Hunter -> Identifies candidate niches
    3. Fit Evaluator -> Scores founder-niche fit
    4. Roadmap Architect -> Creates action roadmap
    5. Tooling Advisor -> Recommends tools
    
    The orchestrator:
    - Manages agent execution order
    - Passes context between agents
    - Handles errors gracefully
    - Logs metrics for observability
    
    To add a new agent:
    1. Create the agent class in services/agents/
    2. Add it to the pipeline in _build_graph()
    3. Update the node handlers
    """
    
    def __init__(self):
        self.profile_agent = ProfileAnalystAgent()
        self.market_agent = MarketHunterAgent()
        self.fit_agent = FitEvaluatorAgent()
        self.roadmap_agent = RoadmapArchitectAgent()
        self.tooling_agent = ToolingAdvisorAgent()
        
        # Build the LangGraph workflow
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state machine.
        
        The graph defines the execution order and flow control.
        Currently uses a simple linear flow, but can be extended
        for parallel execution or conditional branching.
        """
        # Define the graph with our state type
        workflow = StateGraph(OrchestratorState)
        
        # Add nodes for each agent
        workflow.add_node("profile_analyst", self._run_profile_agent)
        workflow.add_node("market_hunter", self._run_market_agent)
        workflow.add_node("fit_evaluator", self._run_fit_agent)
        workflow.add_node("roadmap_architect", self._run_roadmap_agent)
        workflow.add_node("tooling_advisor", self._run_tooling_agent)
        
        # Define edges (linear flow)
        workflow.set_entry_point("profile_analyst")
        workflow.add_edge("profile_analyst", "market_hunter")
        workflow.add_edge("market_hunter", "fit_evaluator")
        workflow.add_edge("fit_evaluator", "roadmap_architect")
        workflow.add_edge("roadmap_architect", "tooling_advisor")
        workflow.add_edge("tooling_advisor", END)
        
        return workflow.compile()
    
    async def _run_profile_agent(self, state: OrchestratorState) -> OrchestratorState:
        """Execute profile analyst agent."""
        try:
            context = AgentContext(**state["context"])
            context = await self.profile_agent.run(context)
            state["context"] = context.model_dump()
            state["current_agent"] = "profile_analyst"
            state["status"] = "completed"
        except Exception as e:
            state["status"] = "error"
            state["error"] = str(e)
            logger.error(f"Profile agent error: {e}")
        return state
    
    async def _run_market_agent(self, state: OrchestratorState) -> OrchestratorState:
        """Execute market hunter agent."""
        try:
            context = AgentContext(**state["context"])
            context = await self.market_agent.run(context)
            state["context"] = context.model_dump()
            state["current_agent"] = "market_hunter"
            state["status"] = "completed"
        except Exception as e:
            state["status"] = "error"
            state["error"] = str(e)
            logger.error(f"Market agent error: {e}")
        return state
    
    async def _run_fit_agent(self, state: OrchestratorState) -> OrchestratorState:
        """Execute fit evaluator agent."""
        try:
            context = AgentContext(**state["context"])
            context = await self.fit_agent.run(context)
            state["context"] = context.model_dump()
            state["current_agent"] = "fit_evaluator"
            state["status"] = "completed"
        except Exception as e:
            state["status"] = "error"
            state["error"] = str(e)
            logger.error(f"Fit agent error: {e}")
        return state
    
    async def _run_roadmap_agent(self, state: OrchestratorState) -> OrchestratorState:
        """Execute roadmap architect agent."""
        try:
            context = AgentContext(**state["context"])
            context = await self.roadmap_agent.run(context)
            state["context"] = context.model_dump()
            state["current_agent"] = "roadmap_architect"
            state["status"] = "completed"
        except Exception as e:
            state["status"] = "error"
            state["error"] = str(e)
            logger.error(f"Roadmap agent error: {e}")
        return state
    
    async def _run_tooling_agent(self, state: OrchestratorState) -> OrchestratorState:
        """Execute tooling advisor agent."""
        try:
            context = AgentContext(**state["context"])
            context = await self.tooling_agent.run(context)
            state["context"] = context.model_dump()
            state["current_agent"] = "tooling_advisor"
            state["status"] = "completed"
        except Exception as e:
            state["status"] = "error"
            state["error"] = str(e)
            logger.error(f"Tooling agent error: {e}")
        return state
    
    async def run(self, profile_data: Dict[str, Any], user_id: str, profile_id: str) -> NicheReport:
        """Run the complete niche discovery pipeline.
        
        Args:
            profile_data: Raw founder profile data
            user_id: ID of the user
            profile_id: ID of the saved profile
        
        Returns:
            NicheReport: Complete analysis report
        """
        start_time = datetime.now(timezone.utc)
        logger.info(f"Starting niche discovery pipeline for user {user_id}")
        
        # Initialize state
        initial_state: OrchestratorState = {
            "context": AgentContext(raw_profile=profile_data).model_dump(),
            "current_agent": "",
            "status": "pending",
            "error": ""
        }
        
        # Run the graph
        final_state = await self.graph.ainvoke(initial_state)
        
        # Extract results
        context = AgentContext(**final_state["context"])
        
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()
        logger.info(f"Pipeline completed in {duration:.2f}s")
        
        # Build the report
        report = self._build_report(context, user_id, profile_id)
        
        return report
    
    def _build_report(self, context: AgentContext, user_id: str, profile_id: str) -> NicheReport:
        """Convert agent context into a structured report."""
        # Build profile summary
        profile_summary = ProfileSummary(
            background_summary=context.profile_summary.get('background_summary', '') if context.profile_summary else '',
            key_strengths=context.profile_summary.get('key_strengths', []) if context.profile_summary else [],
            notable_skills=context.profile_summary.get('notable_skills', []) if context.profile_summary else [],
            constraints_summary=context.profile_summary.get('constraints_summary', '') if context.profile_summary else '',
            ideal_founder_archetype=context.profile_summary.get('ideal_founder_archetype', '') if context.profile_summary else ''
        )
        
        # Build niches
        niches = []
        for n in context.selected_niches or context.candidate_niches[:3]:
            niches.append(Niche(
                name=n.get('name', ''),
                description=n.get('description', ''),
                problem_statement=n.get('problem_statement', ''),
                target_audience=n.get('target_audience', ''),
                why_fits_you=n.get('why_fits_founder', ''),
                market_opportunity=n.get('market_opportunity', ''),
                competition_level=n.get('competition_level', 'medium'),
                fit_score=n.get('fit_score', 50),
                improvement_areas=n.get('improvement_areas', []),
                cofounder_skills_needed=n.get('cofounder_skills_needed', [])
            ))
        
        # Build roadmap
        roadmap_data = context.roadmap or {}
        phases = []
        for p in roadmap_data.get('phases', []):
            phases.append(RoadmapPhase(
                phase_name=p.get('phase_name', ''),
                goals=p.get('goals', []),
                actions=p.get('actions', []),
                resources=p.get('resources', []),
                milestones=p.get('milestones', []),
                deliverables=p.get('deliverables', [])
            ))
        
        roadmap = Roadmap(
            phases=phases,
            suggested_roles=roadmap_data.get('suggested_roles', []),
            first_customer_strategies=roadmap_data.get('first_customer_strategies', [])
        )
        
        # Build tool recommendations
        tools = []
        for t in context.tool_recommendations:
            tools.append(ToolRecommendation(
                name=t.get('name', ''),
                category=t.get('category', ''),
                description=t.get('description', ''),
                pricing=t.get('pricing', 'free'),
                url=t.get('url'),
                why_recommended=t.get('why_recommended', '')
            ))
        
        return NicheReport(
            user_id=user_id,
            profile_id=profile_id,
            profile_summary=profile_summary,
            recommended_niches=niches,
            selected_niche=niches[0] if niches else None,
            roadmap=roadmap,
            tool_recommendations=tools,
            status="completed"
        )

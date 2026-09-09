"""Agent Orchestrator for the niche discovery pipeline.

Runs the 5 agents in sequence, sharing one AgentContext. Every LLM call any agent
makes during a run carries the same `run_id`, which groups them into a single
Langfuse trace (see llm_fallback.py) -- that's what makes "this pipeline run
regressed" a traceable, evidence-backed statement rather than 5 unrelated LLM calls.

This module does not do observability itself; it only makes sure a run_id exists and
flows through. Detection lives in backend/guardian/.
"""
import logging
import uuid
from typing import Any, Dict

from services.agents import (
    AgentContext,
    ProfileAnalystAgent,
    MarketHunterAgent,
    FitEvaluatorAgent,
    RoadmapArchitectAgent,
    ToolingAdvisorAgent,
)
from models.report import (
    NicheReport, ProfileSummary, Niche, Roadmap, RoadmapPhase, ToolRecommendation
)

logger = logging.getLogger(__name__)


class NicheDiscoveryOrchestrator:
    """Orchestrates the agent pipeline for niche discovery."""

    def __init__(self):
        self.profile_agent = ProfileAnalystAgent()
        self.market_agent = MarketHunterAgent()
        self.fit_agent = FitEvaluatorAgent()
        self.roadmap_agent = RoadmapArchitectAgent()
        self.tooling_agent = ToolingAdvisorAgent()
        # Exposed for callers that need to correlate a run with its Langfuse trace
        # (e.g. scripts/verify_mvp.py) without changing NicheReport's schema.
        self.last_run_id: str | None = None

    async def run(self, profile_data: Dict[str, Any], user_id: str, profile_id: str) -> NicheReport:
        """Run the complete niche discovery pipeline."""
        run_id = str(uuid.uuid4())
        self.last_run_id = run_id
        logger.info(f"Starting niche discovery pipeline run={run_id} user={user_id}")

        context = AgentContext(raw_profile=profile_data, run_id=run_id, user_id=user_id)
        current_agent = ""

        try:
            current_agent = "profile_analyst"
            context = await self.profile_agent.run(context)

            current_agent = "market_hunter"
            context = await self.market_agent.run(context)

            current_agent = "fit_evaluator"
            context = await self.fit_agent.run(context)

            current_agent = "roadmap_architect"
            context = await self.roadmap_agent.run(context)

            current_agent = "tooling_advisor"
            context = await self.tooling_agent.run(context)

        except Exception as e:
            logger.error(f"Pipeline run={run_id} failed at {current_agent}: {e}")
            raise

        logger.info(f"Pipeline run={run_id} completed")
        return self._build_report(context, user_id, profile_id)

    def _build_report(self, context: AgentContext, user_id: str, profile_id: str) -> NicheReport:
        """Convert agent context into a structured report."""
        profile_summary = ProfileSummary(
            background_summary=context.profile_summary.get('background_summary', '') if context.profile_summary else '',
            key_strengths=context.profile_summary.get('key_strengths', []) if context.profile_summary else [],
            notable_skills=context.profile_summary.get('notable_skills', []) if context.profile_summary else [],
            constraints_summary=context.profile_summary.get('constraints_summary', '') if context.profile_summary else '',
            ideal_founder_archetype=context.profile_summary.get('ideal_founder_archetype', '') if context.profile_summary else ''
        )

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

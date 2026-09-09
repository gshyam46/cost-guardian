"""Roadmap Architect Agent.

This agent creates a detailed 3-6-12 month roadmap for the founder
to pursue their selected niche, including skills to acquire, projects
to build, and strategies for finding first customers.
"""
import json
from .base_agent import BaseAgent, AgentContext


class RoadmapArchitectAgent(BaseAgent):
    """Creates actionable founder roadmaps with concrete milestones."""
    
    name = "roadmap_architect"
    description = "Creates detailed founder journey roadmaps"
    
    def get_system_prompt(self) -> str:
        return """You are a Roadmap Architect specializing in founder journey planning.

Your role is to create actionable, time-bound roadmaps that help founders:
- Acquire necessary skills (using FREE or LOW-COST resources)
- Build relevant side projects or MVPs
- Develop their portfolio and content
- Find their first customers

You focus on:
- Concrete, measurable actions
- Realistic timelines based on available hours
- Free/low-cost resources (YouTube, docs, MOOCs, OSS repos)
- Progressive skill building
- Early validation strategies

Always respond with valid JSON in the exact format specified."""
    
    def get_user_prompt(self, context: AgentContext) -> str:
        profile = context.profile_summary or {}
        raw = context.raw_profile
        selected = context.selected_niches[:2] if context.selected_niches else context.candidate_niches[:2]
        
        niche_text = ""
        for niche in selected:
            niche_text += f"""\n- {niche.get('name')}: {niche.get('problem_statement')}
  Target: {niche.get('target_audience')}
  Fit Score: {niche.get('fit_score', 'N/A')}"""
        
        return f"""Create a detailed 12-month roadmap for this founder.

## Founder Profile:
- Background: {profile.get('background_summary', 'N/A')}
- Key Strengths: {', '.join(profile.get('key_strengths', []))}
- Areas to Develop: {', '.join(profile.get('areas_to_develop', []))}
- Time Available: {raw.get('hours_per_week', 10)} hours/week
- Risk Appetite: {raw.get('risk_appetite', 'medium')}
- Learning Mode: {raw.get('learning_mode', 'build-first')}
- Network Strength: {raw.get('network_strength', 'moderate')}

## Selected Niches:{niche_text}

## Task:
Create a phased roadmap broken into:
1. Phase 1 (0-3 months): Foundation & Validation
2. Phase 2 (3-6 months): Building & Learning
3. Phase 3 (6-12 months): Launch & Scale

For each phase include:
- Clear goals
- Specific actions (with time estimates)
- FREE or LOW-COST resources (include URLs where possible)
- Milestones to track progress
- Deliverables

Also suggest:
- Roles/jobs that would align with their niche journey
- Strategies for finding first customers

## Output Format (JSON):
```json
{{
  "phases": [
    {{
      "phase_name": "0-3 months: Foundation & Validation",
      "goals": ["goal1", "goal2"],
      "actions": [
        "Action 1 (X hours/week)",
        "Action 2 (X hours/week)"
      ],
      "resources": [
        {{"name": "Resource name", "url": "https://...", "type": "free"}}
      ],
      "milestones": ["milestone1", "milestone2"],
      "deliverables": ["deliverable1", "deliverable2"]
    }}
  ],
  "suggested_roles": [
    {{
      "role": "Job title",
      "company_type": "Type of company to target",
      "why": "Why this role helps the founder journey",
      "duration": "Recommended time in role"
    }}
  ],
  "first_customer_strategies": [
    "Strategy 1: Description",
    "Strategy 2: Description"
  ]
}}
```

Respond ONLY with the JSON object, no additional text."""
    
    def parse_response(self, response: str, context: AgentContext) -> AgentContext:
        data = self.extract_json(response)
        context.roadmap = data
        return context

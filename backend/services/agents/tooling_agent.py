"""Tooling & Stack Advisor Agent.

This agent recommends FREE or LOW-COST tools and platforms the founder
can use to build their startup. Focuses on open-source and freemium options.
"""
import json
from .base_agent import BaseAgent, AgentContext


class ToolingAdvisorAgent(BaseAgent):
    """Recommends free/low-cost tools for startup building."""
    
    name = "tooling_advisor"
    description = "Recommends free and low-cost tools for founders"
    
    def get_system_prompt(self) -> str:
        return """You are a Tooling & Stack Advisor specializing in cost-effective startup infrastructure.

Your role is to recommend tools and platforms that are:
- FREE or LOW-COST (< $50/month for early stage)
- Open-source when possible
- Easy to set up and use
- Scalable as the startup grows

You prioritize:
- Google Cloud services (Cloud Run, Firestore, BigQuery, Vertex AI, etc.)
- Open-source alternatives (Supabase, n8n, etc.)
- Freemium tools with generous free tiers
- Developer-friendly platforms

NEVER recommend expensive proprietary solutions for early-stage founders.

Always respond with valid JSON in the exact format specified."""
    
    def get_user_prompt(self, context: AgentContext) -> str:
        profile = context.profile_summary or {}
        raw = context.raw_profile
        selected = context.selected_niches[:2] if context.selected_niches else context.candidate_niches[:2]
        roadmap = context.roadmap or {}
        
        niche_names = [n.get('name') for n in selected]
        tech_skills = raw.get('tech_skills', [])
        
        return f"""Recommend tools and platforms for this founder's startup journey.

## Founder Profile:
- Technical Skills: {', '.join(tech_skills)}
- Learning Mode: {raw.get('learning_mode', 'build-first')}
- Budget Constraint: Early-stage founder, minimal budget

## Selected Niches:
{', '.join(niche_names)}

## Roadmap Phases:
{len(roadmap.get('phases', []))} phases defined with focus on building MVP and finding customers.

## Task:
Recommend tools across these categories:
1. AI/ML - For building AI features (prioritize Google Vertex AI, open-source models)
2. Cloud/Hosting - For deployment (prioritize Google Cloud)
3. Database - For data storage
4. Development - IDEs, frameworks, libraries
5. Analytics - For tracking and insights
6. Marketing - For growth and outreach
7. Productivity - For founder efficiency
8. Design - For UI/UX work

For each tool:
- Explain why it's recommended for this founder
- Note the pricing (free, freemium, cost)
- Provide the URL

## Output Format (JSON):
```json
{{
  "recommendations": [
    {{
      "name": "Tool name",
      "category": "AI/ML | Cloud | Database | Development | Analytics | Marketing | Productivity | Design",
      "description": "What the tool does",
      "pricing": "free | freemium | low-cost | open-source",
      "url": "https://...",
      "why_recommended": "Why this is good for this founder"
    }}
  ],
  "stack_summary": "Brief summary of the recommended stack"
}}
```

Respond ONLY with the JSON object, no additional text."""
    
    def parse_response(self, response: str, context: AgentContext) -> AgentContext:
        data = self.extract_json(response)
        context.tool_recommendations = data.get('recommendations', [])
        return context

"""Market & Problem Hunter Agent.

This agent proposes promising problem spaces/niches where the founder
could have a competitive edge based on their profile.
"""
import json
from .base_agent import BaseAgent, AgentContext


class MarketHunterAgent(BaseAgent):
    """Identifies promising problem spaces and niches for the founder."""
    
    name = "market_hunter"
    description = "Discovers promising problem spaces aligned with founder profile"
    
    def get_system_prompt(self) -> str:
        return """You are a Market & Problem Hunter specializing in startup opportunity identification.

Your role is to identify 3-7 specific problem spaces where a founder could build
a successful startup based on their unique background and skills.

You focus on:
- B2B / developer tools / clear pain points where possible
- Problems with real market demand
- Niches where the founder has unfair advantages
- Avoiding generic suggestions like "build an app"

Think step-by-step and justify each recommendation.

Always respond with valid JSON in the exact format specified."""
    
    def get_user_prompt(self, context: AgentContext) -> str:
        profile = context.profile_summary or {}
        raw = context.raw_profile
        
        return f"""Based on this founder profile, identify 4-6 promising startup niches.

## Founder Profile Summary:
- Background: {profile.get('background_summary', 'N/A')}
- Key Strengths: {', '.join(profile.get('key_strengths', []))}
- Notable Skills: {', '.join(profile.get('notable_skills', []))}
- Constraints: {profile.get('constraints_summary', 'N/A')}
- Archetype: {profile.get('ideal_founder_archetype', 'N/A')}
- Unique Advantages: {', '.join(profile.get('unique_advantages', []))}

## Their Interests:
- Excited Domains: {', '.join(raw.get('excited_domains', []))}
- Target Roles: {', '.join(raw.get('target_roles', []))}
- Risk Appetite: {raw.get('risk_appetite', 'medium')}
- Time Available: {raw.get('hours_per_week', 0)} hours/week

## Task:
Propose 4-6 specific problem spaces/niches where this founder could succeed.

For each niche:
1. Be specific (not "AI startup" but "AI-powered code review for security vulnerabilities")
2. Explain why their background gives them an edge
3. Identify the target audience
4. Assess competition level
5. Suggest complementary cofounder skills that would increase chances
6. Identify improvement areas the founder could work on

## Output Format (JSON):
```json
{{
  "niches": [
    {{
      "name": "Niche name",
      "description": "What the startup would do",
      "problem_statement": "The specific problem being solved",
      "target_audience": "Who would buy this",
      "why_fits_founder": "Why this founder is well-positioned",
      "market_opportunity": "Size and growth potential",
      "competition_level": "low/medium/high",
      "cofounder_skills_needed": ["skill1", "skill2"],
      "improvement_areas": ["area1", "area2"]
    }}
  ]
}}
```

Respond ONLY with the JSON object, no additional text."""
    
    def parse_response(self, response: str, context: AgentContext) -> AgentContext:
        data = self.extract_json(response)
        context.candidate_niches = data.get('niches', [])
        return context

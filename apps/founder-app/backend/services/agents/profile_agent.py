"""Profile & Strengths Analyst Agent.

This agent analyzes the user's raw profile data and produces a structured
summary of their background, skills, and constraints. This summary is used
by subsequent agents to tailor their recommendations.
"""
from .base_agent import BaseAgent, AgentContext


class ProfileAnalystAgent(BaseAgent):
    """Analyzes user profile and summarizes strengths, background, constraints."""
    
    name = "profile_analyst"
    description = "Analyzes founder profile and summarizes key attributes"
    
    def get_system_prompt(self) -> str:
        return """You are a Profile & Strengths Analyst specializing in founder assessment.

Your role is to analyze a founder's background, skills, and constraints to create
a comprehensive profile summary that will help identify their ideal startup niche.

You think step-by-step and produce structured, actionable insights.

Always respond with valid JSON in the exact format specified."""
    
    def get_user_prompt(self, context: AgentContext) -> str:
        profile = context.raw_profile
        
        return f"""Analyze this founder profile and create a comprehensive summary.

## Profile Data:
- Education: {profile.get('education', 'Not specified')}
- Current Role: {profile.get('current_role', 'Not specified')}
- Years of Experience: {profile.get('years_experience', 0)}
- Technical Skills: {', '.join(profile.get('tech_skills', []))}
- Domain Skills: {', '.join(profile.get('domain_skills', []))}
- Soft Skills: {', '.join(profile.get('soft_skills', []))}
- Previous Projects: {profile.get('previous_projects', 'None')}
- Excited Domains: {', '.join(profile.get('excited_domains', []))}
- Hours per Week Available: {profile.get('hours_per_week', 0)}
- Runway (months): {profile.get('runway_months', 'Not specified')}
- Location: {profile.get('location', 'Not specified')}
- Risk Appetite: {profile.get('risk_appetite', 'medium')}
- Target Roles: {', '.join(profile.get('target_roles', []))}
- Portfolio: {profile.get('existing_portfolio', 'None')}
- GitHub: {profile.get('github_url', 'None')}
- Network Strength: {profile.get('network_strength', 'moderate')}
- Learning Mode: {profile.get('learning_mode', 'build-first')}

## Task:
Analyze this profile and identify:
1. Key strengths that give them a competitive edge
2. Notable skills that could translate to startup success
3. Constraints that should influence niche selection
4. What founder archetype they fit (technical founder, domain expert, generalist, etc.)

## Output Format (JSON):
```json
{{
  "background_summary": "2-3 sentence summary of their professional background",
  "key_strengths": ["strength1", "strength2", "strength3"],
  "notable_skills": ["skill1", "skill2", "skill3"],
  "constraints_summary": "Summary of time, financial, and other constraints",
  "ideal_founder_archetype": "The founder archetype they most closely match",
  "unique_advantages": ["advantage1", "advantage2"],
  "areas_to_develop": ["area1", "area2"]
}}
```

Respond ONLY with the JSON object, no additional text."""
    
    def parse_response(self, response: str, context: AgentContext) -> AgentContext:
        data = self.extract_json(response)
        context.profile_summary = data
        return context

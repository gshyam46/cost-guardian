"""Founder-Problem Fit Evaluator Agent.

This agent evaluates how well the founder fits each candidate niche
and provides fit scores with detailed justifications.
"""
import json
from .base_agent import BaseAgent, AgentContext


class FitEvaluatorAgent(BaseAgent):
    """Evaluates founder-problem fit for each candidate niche."""
    
    name = "fit_evaluator"
    description = "Evaluates founder-problem fit and ranks niches"
    
    def get_system_prompt(self) -> str:
        return """You are a Founder-Problem Fit Evaluator specializing in startup success prediction.

Your role is to evaluate how well a founder matches each proposed startup niche
and provide detailed fit assessments with scores.

You consider:
- Skill alignment with problem requirements
- Domain expertise relevance
- Time/resource constraints vs. niche demands
- Motivation and interest alignment
- Network advantages
- Risk profile match

Be honest and critical - it's better to redirect a founder than let them pursue a poor fit.

Always respond with valid JSON in the exact format specified."""
    
    def get_user_prompt(self, context: AgentContext) -> str:
        profile = context.profile_summary or {}
        niches = context.candidate_niches
        raw = context.raw_profile
        
        niches_text = ""
        for i, niche in enumerate(niches, 1):
            niches_text += f"""\n{i}. {niche.get('name')}
   - Problem: {niche.get('problem_statement')}
   - Target: {niche.get('target_audience')}
   - Why fits: {niche.get('why_fits_founder')}"""
        
        return f"""Evaluate founder-problem fit for each proposed niche.

## Founder Profile:
- Background: {profile.get('background_summary', 'N/A')}
- Key Strengths: {', '.join(profile.get('key_strengths', []))}
- Notable Skills: {', '.join(profile.get('notable_skills', []))}
- Constraints: {profile.get('constraints_summary', 'N/A')}
- Archetype: {profile.get('ideal_founder_archetype', 'N/A')}
- Time Available: {raw.get('hours_per_week', 0)} hours/week
- Risk Appetite: {raw.get('risk_appetite', 'medium')}
- Learning Mode: {raw.get('learning_mode', 'build-first')}

## Candidate Niches:{niches_text}

## Task:
For each niche, provide:
1. A fit score (1-100)
2. Detailed justification for the score
3. Key risks or gaps
4. What would make this a better fit

Then select the top 2-3 niches that best fit this founder.

## Output Format (JSON):
```json
{{
  "evaluations": [
    {{
      "niche_name": "Name of the niche",
      "fit_score": 85,
      "score_justification": "Detailed explanation of why this score",
      "key_strengths_match": ["strength that matches"],
      "key_gaps": ["gap or risk"],
      "improvement_suggestions": ["what would improve fit"]
    }}
  ],
  "top_recommendations": [
    {{
      "rank": 1,
      "niche_name": "Best fit niche",
      "summary": "Why this is the top recommendation"
    }}
  ]
}}
```

Respond ONLY with the JSON object, no additional text."""
    
    def parse_response(self, response: str, context: AgentContext) -> AgentContext:
        data = self.extract_json(response)
        context.niche_evaluations = data.get('evaluations', [])
        
        # Merge fit scores into candidate niches
        for niche in context.candidate_niches:
            for eval in context.niche_evaluations:
                if eval.get('niche_name') == niche.get('name'):
                    niche['fit_score'] = eval.get('fit_score', 0)
                    niche['score_justification'] = eval.get('score_justification', '')
                    niche['key_gaps'] = eval.get('key_gaps', [])
                    break
        
        # Select top niches
        top_recs = data.get('top_recommendations', [])
        context.selected_niches = []
        for rec in top_recs:
            for niche in context.candidate_niches:
                if niche.get('name') == rec.get('niche_name'):
                    context.selected_niches.append(niche)
                    break
        
        return context

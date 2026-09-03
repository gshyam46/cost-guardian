# observability/scoring/cost_model.py
"""Cost calculation for LLM operations."""

import logging

logger = logging.getLogger(__name__)


class CostModel:
    """
    Calculates cost of LLM API calls based on model and tokens used.
    
    Pricing (as of Dec 2024):
    - Groq (free tier): $0 for foundational models
    - OpenRouter varies by model
    - Claude 3 Opus: $0.015/1K input, $0.075/1K output
    - GPT-4: $0.03/1K input, $0.06/1K output
    """
    
    def __init__(self):
        self.pricing = {
            # Groq (generally free or very cheap)
            "groq/llama-3.3-70b-versatile": {"input": 0.0, "output": 0.0},
            "groq/llama-3.1-8b-instant": {"input": 0.0, "output": 0.0},
            "groq/mixtral-8x7b": {"input": 0.0, "output": 0.0},
            
            # OpenRouter (variable)
            "openrouter/allenai/olmo-3-32b-think": {"input": 0.001, "output": 0.001},
            "openrouter/arcee/trinity-mini": {"input": 0.0008, "output": 0.0008},
            "openrouter/openai/gpt-oss-20b": {"input": 0.002, "output": 0.002},
            
            # Anthropic
            "claude-3-opus": {"input": 0.015, "output": 0.075},
            "claude-3-sonnet": {"input": 0.003, "output": 0.015},
            "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
            
            # OpenAI
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gpt-4-turbo": {"input": 0.01, "output": 0.03},
            "gpt-3.5-turbo": {"input": 0.0015, "output": 0.002},
            
            # Google (Gemini)
            "gemini-1.5-pro": {"input": 0.0075, "output": 0.03},
            "gemini-1.5-flash": {"input": 0.00075, "output": 0.003},
            
            # Default (fallback)
            "default": {"input": 0.001, "output": 0.002}
        }
    
    def calculate(self, model: str, tokens_used: int) -> float:
        """
        Calculate cost in USD for given model and token count.
        
        Args:
            model: Model identifier (e.g., "groq/llama-3.3-70b")
            tokens_used: Total tokens (input + output)
        
        Returns:
            Cost in USD
        """
        # Extract model key (handle both full names and short names)
        model_key = model
        for key in self.pricing.keys():
            if key in model or model in key:
                model_key = key
                break
        
        pricing = self.pricing.get(model_key, self.pricing["default"])
        
        # Rough estimate: assume 30% input, 70% output tokens
        input_tokens = int(tokens_used * 0.3)
        output_tokens = int(tokens_used * 0.7)
        
        cost = (
            (input_tokens * pricing["input"]) / 1000 +
            (output_tokens * pricing["output"]) / 1000
        )
        
        return round(cost, 6)


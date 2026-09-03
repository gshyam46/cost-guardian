# import logging
# from typing import List
# from litellm import acompletion  # async completion

# logger = logging.getLogger(__name__)

# class LlmChat:
#     """
#     Unified LLM client with automatic fallback:
#     Gemini → Groq → OpenAI → OpenRouter (optional)
#     """

#     def __init__(self, api_key: str, session_id: str, system_message: str):
#         self.api_key = api_key
#         self.session_id = session_id
#         self.system_message = system_message

#         # default model chain (highest → lowest)
#         self.fallback_chain = [
#             # "gemini/gemini-2.0-flash",
#             "openrouter/allenai/olmo-3-32b-think",
#             "openrouter/amazon/nova-2-lite",
#             "groq/llama-3.3-70b-versatile",
#             "openrouter/arcee/trinity-mini",
#             "openrouter/openai/gpt-oss-20b"
#         ]


#         self.current_model = self.fallback_chain[0]

#     def with_model(self, provider: str, model: str):
#         """Override primary model if needed."""
#         self.current_model = f"{provider}/{model}"
#         self.fallback_chain[0] = self.current_model
#         return self

#     async def send_message(self, user_message: 'UserMessage') -> str:
#         """Try each LLM provider until one responds without failing."""
#         messages = [
#             {"role": "system", "content": self.system_message},
#             {"role": "user", "content": user_message.text}
#         ]

#         last_error = None

#         for model in self.fallback_chain:
#             try:
#                 logger.info(f"[LlmChat] Trying model: {model}")

#                 resp = await run_final_llm(model, messages)

#                 return resp["choices"][0]["message"]["content"]

#             except Exception as e:
#                 logger.error(f"[LlmChat] Model failed: {model} → {e}")
#                 last_error = e
#                 continue

#         # If all models fail:
#         raise RuntimeError(f"All fallback models failed. Last error: {last_error}")


# from ddtrace.llmobs import track_llm

# @track_llm  # will trace ONLY successful requests
#   )












import logging
import time
from typing import List, Optional, Dict, Any

from ddtrace import tracer
from ddtrace.llmobs import LLMObs
from litellm import acompletion

logger = logging.getLogger(__name__)


def estimate_cost_usd(model: str, usage: Dict[str, Any]) -> float:
    """
    Rough cost estimator for LLM usage.
    Returns pseudo-cost based on token count.
    """
    prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    completion_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or 0
    total_tokens = prompt_tokens + completion_tokens
    
    # Heuristic: $0.002 per 1K tokens
    return round(total_tokens * 0.000002, 6)


class LlmChat:
    """
    Unified LLM client with automatic fallback and full Datadog LLM observability.
    
    Features:
    - Automatic provider fallback on errors
    - Per-request tracing with llm.request spans
    - Token usage and cost tracking
    - Error tracking and retry metadata
    """

    def __init__(self, api_key: str, session_id: str, system_message: str):
        self.api_key = api_key
        self.session_id = session_id
        self.system_message = system_message

        # Default model chain (highest → lowest priority)
        self.fallback_chain: List[str] = [
                        "groq/llama-3.3-70b-versatile",
            "openrouter/allenai/olmo-3-32b-think",
            "openrouter/arcee/trinity-mini",
            "openrouter/openai/gpt-oss-20b",
        ]

        self.current_model = self.fallback_chain[0]

    def with_model(self, provider: str, model: str) -> "LlmChat":
        """Override primary model if needed."""
        self.current_model = f"{provider}/{model}"
        self.fallback_chain[0] = self.current_model
        return self

    async def send_message(self, user_message: "UserMessage", agent_name: str = "default") -> str:
        """
        Try each LLM provider until one responds successfully.
        
        Creates a Datadog span for each attempt with:
        - Model and provider tags
        - Agent and user identification
        - Latency metrics
        - Token usage and cost
        - Error tracking
        """
        messages = [
            {"role": "system", "content": self.system_message},
            {"role": "user", "content": user_message.text},
        ]

        last_error: Optional[Exception] = None
        attempt_count = 0

        for model in self.fallback_chain:
            attempt_count += 1
            start = time.monotonic()
            
            logger.info(f"[LlmChat] Attempt {attempt_count}/{len(self.fallback_chain)}: {model}")

            # Create Datadog span for this attempt
            with tracer.trace("llm.request", service="founder-backend") as span:
                # Set base tags
                span.set_tag("llm.app", "founder-niche-ai")
                span.set_tag("llm.agent", agent_name)
                span.set_tag("llm.model", model)
                span.set_tag("llm.provider", model.split("/")[0])
                span.set_tag("user.id", self.session_id)
                span.set_tag("llm.attempt", attempt_count)
                span.set_tag("llm.max_attempts", len(self.fallback_chain))

                try:
                    # Make LLM request with timeout
                    resp = await acompletion(
                        model=model,
                        messages=messages,
                        timeout=30,
                    )

                    # Calculate latency
                    latency_ms = int((time.monotonic() - start) * 1000)
                    span.set_tag("llm.latency_ms", latency_ms)

                    # Extract usage metrics
                    usage = resp.get("usage", {}) or {}
                    prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
                    completion_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or 0
                    total_tokens = prompt_tokens + completion_tokens

                    # Tag token metrics
                    span.set_tag("llm.tokens.prompt", prompt_tokens)
                    span.set_tag("llm.tokens.completion", completion_tokens)
                    span.set_tag("llm.tokens.total", total_tokens)

                    # Calculate and tag cost
                    cost_usd = estimate_cost_usd(model, usage)
                    span.set_tag("llm.cost_usd", cost_usd)

                    # Mark as successful
                    span.set_tag("error", False)
                    span.set_tag("llm.success", True)
                    span.set_tag("llm.fallback_used", attempt_count > 1)

                    # Log LLMObs data for successful requests
                    try:
                        LLMObs.annotate(
                            input_data={"messages": messages},
                            output_data=resp["choices"][0]["message"]["content"],
                            metadata={
                                "model": model,
                                "agent": agent_name,
                                "session_id": self.session_id,
                                "tokens": total_tokens,
                                "cost": cost_usd,
                            },
                            tags={
                                "env": "production",
                                "service": "founder-backend",
                            },
                        )
                    except Exception as llm_obs_error:
                        logger.warning(f"[LlmChat] LLMObs annotation failed: {llm_obs_error}")

                    logger.info(
                        f"[LlmChat] Success with {model} "
                        f"(latency: {latency_ms}ms, tokens: {total_tokens}, cost: ${cost_usd})"
                    )

                    return resp["choices"][0]["message"]["content"]

                except Exception as e:
                    # Calculate latency even for failures
                    latency_ms = int((time.monotonic() - start) * 1000)
                    span.set_tag("llm.latency_ms", latency_ms)

                    # Tag error details
                    span.set_tag("error", True)
                    span.set_tag("llm.success", False)
                    span.set_tag("error.type", e.__class__.__name__)
                    span.set_tag("error.msg", str(e))
                    span.set_tag("llm.will_retry", attempt_count < len(self.fallback_chain))

                    logger.error(
                        f"[LlmChat] Model failed: {model} → {e.__class__.__name__}: {e}"
                    )
                    
                    last_error = e
                    continue

        # All models failed - create final error span
        with tracer.trace("llm.request.all_failed", service="founder-backend") as span:
            span.set_tag("llm.app", "founder-niche-ai")
            span.set_tag("llm.agent", agent_name)
            span.set_tag("user.id", self.session_id)
            span.set_tag("llm.total_attempts", attempt_count)
            span.set_tag("error", True)
            span.set_tag("error.type", "AllModelsFailed")
            span.set_tag("error.msg", str(last_error))

        raise RuntimeError(
            f"All {len(self.fallback_chain)} fallback models failed. "
            f"Last error: {last_error}"
        )
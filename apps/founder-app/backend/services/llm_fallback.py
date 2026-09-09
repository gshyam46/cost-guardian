"""Multi-provider LLM client with automatic fallback and Langfuse tracing.

Every agent call in the app flows through send_message() -> litellm.acompletion().
Langfuse capture is wired via litellm's native callback (configured once at process
startup, see configure_langfuse()) instead of hand-rolled spans -- token usage, cost,
and latency are captured automatically per call. Passing the same `trace_id` (the
pipeline's run_id) on every call in one pipeline execution groups all 5 agents' calls
into a single Langfuse trace, which is what lets a later "workflow Y regressed" incident
be traced back to one causal chain instead of 5 unrelated LLM calls.
"""
import logging
import os
from typing import List, Optional

import litellm
from litellm import acompletion

from config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 120

# The roadmap_architect agent legitimately produces ~5-6k tokens of JSON (three phases,
# each with goals/actions/resources/milestones/deliverables). Under the provider's
# default completion budget it ran out of room mid-document, and because JSON mode
# validates the result the call was rejected outright with
# "max completion tokens reached before generating a valid document" -- a loud failure
# rather than the silently-truncated JSON we used to get, but a failure nonetheless.
MAX_COMPLETION_TOKENS = 8000

_langfuse_configured = False


def configure_langfuse() -> bool:
    """Enable Langfuse tracing via litellm's callback, if credentials are present.

    Safe to call more than once. Missing credentials are a warning, not a crash --
    the app must keep working even when telemetry is unavailable. Returns whether
    tracing is active.
    """
    global _langfuse_configured
    if _langfuse_configured:
        return True

    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        logger.warning(
            "LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY not set - LLM calls will run "
            "normally but will not be traced. Guardian has nothing to analyze until "
            "these are set in backend/.env."
        )
        return False

    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", LANGFUSE_PUBLIC_KEY)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", LANGFUSE_SECRET_KEY)
    os.environ.setdefault("LANGFUSE_HOST", LANGFUSE_HOST)
    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]
    _langfuse_configured = True
    logger.info("Langfuse tracing enabled via litellm callback.")
    return True


class UserMessage:
    def __init__(self, text: str):
        self.text = text


class LlmChat:
    """Unified LLM client with automatic provider fallback.

    One instance is created per agent (see base_agent.py) and reused across every
    request that agent handles, so nothing request-specific (run_id, user id) belongs
    in __init__ -- it's passed per-call to send_message() instead.
    """

    def __init__(self, api_key: str, system_message: str):
        self.api_key = api_key
        self.system_message = system_message

        # Highest to lowest priority. Every model here was probed against the live
        # keys on 2026-09-09 with a realistic agent-sized prompt and confirmed to
        # return parseable JSON.
        #
        # The original chain was entirely dead: groq/llama-3.3-70b-versatile and
        # groq/llama-3.1-8b-instant are not available on this Groq account,
        # openrouter/allenai/olmo-3-32b-think 404s ("no endpoints found"), and
        # openrouter/arcee/trinity-mini was withdrawn ("not a valid model ID").
        #
        # Groq goes first on latency: it answers agent-sized prompts in ~1-2s, where
        # the OpenRouter models took >30s (and hit upstream rate limits on the shared
        # free pool). OpenRouter is kept as a last-resort cross-provider fallback so
        # a Groq outage doesn't take the pipeline down.
        self.fallback_chain: List[str] = [
            "groq/openai/gpt-oss-120b",
            "groq/openai/gpt-oss-20b",
            "groq/qwen/qwen3.8-27b",
            "openrouter/meta-llama/llama-3.3-70b-instruct",
        ]

    def with_model(self, provider: str, model: str) -> "LlmChat":
        """Override the primary model."""
        self.fallback_chain[0] = f"{provider}/{model}"
        return self

    async def send_message(
        self,
        user_message: "UserMessage",
        agent_name: str = "default",
        run_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Try each provider in the fallback chain until one responds successfully.

        agent_name/run_id/user_id are forwarded as litellm metadata, which the
        Langfuse callback reads to group and tag the resulting trace.
        """
        messages = [
            {"role": "system", "content": self.system_message},
            {"role": "user", "content": user_message.text},
        ]

        metadata = {
            "generation_name": agent_name,
            "tags": [f"agent:{agent_name}"],
        }
        if run_id:
            metadata["trace_id"] = run_id
            metadata["session_id"] = run_id
            metadata["trace_name"] = "niche_discovery_run"
        if user_id:
            metadata["trace_user_id"] = user_id

        last_error: Optional[Exception] = None

        for attempt, model in enumerate(self.fallback_chain, start=1):
            try:
                resp = await acompletion(
                    model=model,
                    messages=messages,
                    # 30s was too tight: agent prompts generate large JSON payloads
                    # and every OpenRouter model timed out mid-generation, taking the
                    # whole pipeline down. Groq answers in ~1-2s; this headroom is
                    # for the slower cross-provider fallback.
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    # Every caller of this client is an agent that must return JSON,
                    # so constrain decoding rather than hoping. Without this, the
                    # larger responses (~9k chars) came back with malformed JSON often
                    # enough to exhaust all 3 of base_agent's re-ask attempts and kill
                    # the pipeline. json_object also stops models wrapping output in
                    # markdown fences, which shortens responses noticeably.
                    response_format={"type": "json_object"},
                    max_tokens=MAX_COMPLETION_TOKENS,
                    metadata=metadata,
                )
                if attempt > 1:
                    logger.info(f"[LlmChat] Succeeded on fallback attempt {attempt}: {model}")
                return resp["choices"][0]["message"]["content"]
            except Exception as e:
                logger.warning(f"[LlmChat] {model} failed ({e.__class__.__name__}): {e}")
                last_error = e
                continue

        raise RuntimeError(
            f"All {len(self.fallback_chain)} fallback models failed. Last error: {last_error}"
        )

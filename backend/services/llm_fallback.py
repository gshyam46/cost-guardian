import logging
from typing import List
from litellm import acompletion  # async completion

logger = logging.getLogger(__name__)

class LlmChat:
    """
    Unified LLM client with automatic fallback:
    Gemini → Groq → OpenAI → OpenRouter (optional)
    """

    def __init__(self, api_key: str, session_id: str, system_message: str):
        self.api_key = api_key
        self.session_id = session_id
        self.system_message = system_message

        # default model chain (highest → lowest)
        self.fallback_chain = [
            "gemini/gemini-2.0-flash",
            "openrouter/allenai/olmo-3-32b-think",
            "openrouter/amazon/nova-2-lite",
            "groq/llama-3.3-70b-versatile",
            "openrouter/arcee/trinity-mini",
            "openrouter/openai/gpt-oss-20b"
        ]


        self.current_model = self.fallback_chain[0]

    def with_model(self, provider: str, model: str):
        """Override primary model if needed."""
        self.current_model = f"{provider}/{model}"
        self.fallback_chain[0] = self.current_model
        return self

    async def send_message(self, user_message: 'UserMessage') -> str:
        """Try each LLM provider until one responds without failing."""
        messages = [
            {"role": "system", "content": self.system_message},
            {"role": "user", "content": user_message.text}
        ]

        last_error = None

        for model in self.fallback_chain:
            try:
                logger.info(f"[LlmChat] Trying model: {model}")

                resp = await acompletion(
                    model=model,
                    messages=messages
                )

                return resp["choices"][0]["message"]["content"]

            except Exception as e:
                logger.error(f"[LlmChat] Model failed: {model} → {e}")
                last_error = e
                continue

        # If all models fail:
        raise RuntimeError(f"All fallback models failed. Last error: {last_error}")

# observability/detectors/context_loss.py
"""Detect context loss during multi-agent execution."""

import logging

logger = logging.getLogger(__name__)


class ContextLossDetector:
    """
    Detects if context is being lost between agent steps.
    
    Indicators:
    - Latency spike (agent taking too long to respond)
    - Response length disproportionate to input
    - Token count inconsistencies
    """
    
    def __init__(self):
        self.latency_threshold_ms = 10000  # 10 seconds
        self.length_ratio_threshold = 0.1  # Response < 10% of input
    
    def detect(self, prompt_length: int, response_length: int, latency_ms: float) -> bool:
        """
        Detect context loss indicators.
        Returns True if context loss suspected.
        """
        # Check latency spike
        if latency_ms > self.latency_threshold_ms:
            logger.warning(f"Context loss detected: latency spike {latency_ms}ms")
            return True
        
        # Check response length ratio (if response is too short relative to input)
        if prompt_length > 0:
            ratio = response_length / prompt_length
            if ratio < self.length_ratio_threshold and prompt_length > 1000:
                logger.warning(f"Context loss detected: length ratio {ratio:.2f}")
                return True
        
        return False








# # ************************************MODEL *************************************
# # observability/detectors/context_loss.py
# """
# Context loss detection:
# - token_window_check: compare prompt_tokens to model context window
# - semantic drift: embedding similarity between last-K context messages and response
# """

# from typing import List, Optional
# import os
# import logging
# import math

# logger = logging.getLogger(__name__)

# # Optional sentence-transformers usage if available (same model as hallucination)
# try:
#     from sentence_transformers import SentenceTransformer, util
#     CTX_EMBED_MODEL = SentenceTransformer(os.getenv("SENTENCE_TRANSFORMER_MODEL", "all-MiniLM-L6-v2"))
#     CTX_EMBED_AVAILABLE = True
# except Exception:
#     CTX_EMBED_MODEL = None
#     CTX_EMBED_AVAILABLE = False
#     logger.info("sentence-transformers not available for context_loss; using lexical overlap fallback.")


# def token_window_flag(prompt_tokens: int, model_context_window: int = 8192, threshold: float = 0.8) -> bool:
#     """
#     True if prompt uses >= threshold of context window (default 80%).
#     """
#     try:
#         if model_context_window <= 0:
#             return False
#         return (prompt_tokens / model_context_window) >= threshold
#     except Exception:
#         return False


# def lexical_overlap_score(reference_text: str, response_text: str) -> float:
#     """
#     Compute simple lexical overlap score between 0..1.
#     """
#     r_words = set(w.lower() for w in reference_text.split() if len(w) > 2)
#     s_words = set(w.lower() for w in response_text.split() if len(w) > 2)
#     if not r_words or not s_words:
#         return 0.0
#     overlap = r_words & s_words
#     score = len(overlap) / max(1, min(len(r_words), len(s_words)))
#     return float(score)


# def semantic_drift_score(contexts: List[str], response: str) -> float:
#     """
#     Lower score means better alignment. We return a context_loss_score 0..1
#     where 1 means high context loss (low similarity).
#     If embeddings available, use cosine similarity; else use lexical overlap.
#     """
#     if not contexts:
#         return 1.0
#     joined_context = " ".join(contexts[-6:])  # last few messages
#     if CTX_EMBED_AVAILABLE:
#         try:
#             ctx_emb = CTX_EMBED_MODEL.encode([joined_context], convert_to_tensor=True)
#             resp_emb = CTX_EMBED_MODEL.encode([response], convert_to_tensor=True)
#             sim = util.cos_sim(ctx_emb, resp_emb).item()
#             # convert similarity to loss: sim in [-1,1] normalized to 0..1
#             sim = max(-1.0, min(1.0, sim))
#             loss = 1.0 - ((sim + 1) / 2.0)  # sim=1 -> loss=0 ; sim=-1 -> loss=1
#             return float(max(0.0, min(1.0, loss)))
#         except Exception:
#             logger.exception("Embedding drift failed; falling back to lexical.")
#             return 1.0 - lexical_overlap_score(joined_context, response)
#     else:
#         overlap = lexical_overlap_score(joined_context, response)
#         return float(1.0 - overlap)

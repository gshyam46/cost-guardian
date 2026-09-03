# observability/detectors/hallucination.py
"""Detect hallucinations in LLM output."""

import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)


class HallucinationDetector:
    """
    Detects potential hallucinations in LLM responses.
    
    Uses heuristic-based approach:
    - Uncertainty phrases (I think, maybe, possibly)
    - Contradictions with input
    - Repetitive patterns
    - Unsubstantiated claims
    
    Returns score 0-1 where:
    - 1.0 = high confidence (no hallucination)
    - 0.0 = low confidence (likely hallucination)
    """
    
    def __init__(self):
        self.uncertainty_phrases = [
            "i'm not sure", "i don't know", "i think", "i believe",
            "maybe", "possibly", "probably", "might", "could",
            "seems like", "appears to be", "allegedly", "supposedly",
            "rumor has it", "i heard", "supposedly", "it seems",
            "unclear", "uncertain", "ambiguous"
        ]
        
        self.red_flags = [
            "^made up", "^fake", "^incorrect", "^wrong",
            "^lie", "^false", "^fiction", "^story"
        ]
    
    def detect(self, prompt: str, response: str) -> float:
        """
        Analyze response for hallucination indicators.
        Returns confidence score 0-1.
        """
        score = 1.0  # Start with high confidence
        
        # Check for uncertainty phrases
        uncertainty_count = 0
        for phrase in self.uncertainty_phrases:
            if phrase.lower() in response.lower():
                uncertainty_count += 1
        
        # Reduce score based on uncertainty phrases
        if uncertainty_count > 0:
            score -= min(0.2, uncertainty_count * 0.05)
        
        # Check for red flags
        for flag in self.red_flags:
            if re.search(flag, response.lower()):
                score -= 0.3
        
        # Check for contradiction with input (simple heuristic)
        if self._has_contradiction(prompt, response):
            score -= 0.2
        
        # Enforce bounds
        score = max(0.0, min(1.0, score))
        
        logger.debug(f"Hallucination score: {score:.2f}")
        return score
    
    def _has_contradiction(self, prompt: str, response: str) -> bool:
        """Simple contradiction detection."""
        # Extract key terms from prompt
        prompt_words = set(prompt.lower().split())
        
        # Check for explicit contradictions
        contradictions = [
            ("true", "false"),
            ("yes", "no"),
            ("exists", "doesn't exist"),
            ("correct", "incorrect")
        ]
        
        for term1, term2 in contradictions:
            if term1 in prompt_words and term2 in response.lower():
                return True
        
        return False













# ***************************************** HALLUCINATION MODEL ******************************************

# # observability/detectors/hallucination.py
# """
# Hallucination detector:
# - Primary approach: semantic support score using embeddings (sentence-transformers)
# - Secondary/optional: LLM verifier call (if embedder not present or for higher confidence)
# - Heuristics: overconfident language and numeric over-generation penalty

# Functions:
# - get_hallucination_score(response_text, context_texts, verifier_client=None)
# """

# from typing import List, Optional
# import re
# import logging
# import math
# import asyncio
# import os

# logger = logging.getLogger(__name__)

# # Attempt to import a local embedder for semantic similarity
# EMBEDDING_AVAILABLE = False
# try:
#     from sentence_transformers import SentenceTransformer, util
#     EMBED_MODEL = SentenceTransformer(os.getenv("SENTENCE_TRANSFORMER_MODEL", "all-MiniLM-L6-v2"))
#     EMBEDDING_AVAILABLE = True
# except Exception:
#     EMBEDDING_AVAILABLE = False
#     EMBED_MODEL = None
#     logger.info("sentence-transformers not available; hallucination will use LLM verifier and heuristics.")


# def _extract_assertions(text: str) -> List[str]:
#     """
#     Extract likely factual assertions from text.
#     Heuristic: split into sentences and keep sentences with numbers, dates or 'is/are/was' patterns.
#     """
#     sentences = re.split(r'(?<=[\.\?\!])\s+', text.strip())
#     assertions = []
#     for s in sentences:
#         s_strip = s.strip()
#         if not s_strip:
#             continue
#         # contains numbers or dates or 'is/are/was' structure or percentage
#         if re.search(r'\b\d{2,4}\b', s_strip) or re.search(r'\b(is|are|was|were|has|have|will|shall)\b', s_strip, re.I) or "%" in s_strip:
#             assertions.append(s_strip)
#     return assertions


# def _heuristic_overconfidence_penalty(text: str) -> float:
#     """
#     Return penalty 0..1 based on 'overconfident' words and improbable claims.
#     """
#     score = 0.0
#     overconfident_terms = [
#         r"\bguarantee(s|d)?\b",
#         r"\bdefinitel(y|e)\b",
#         r"\bcertainly\b",
#         r"\bwithout a doubt\b",
#         r"\bin all cases\b",
#         r"\bnever\b",
#     ]
#     for pat in overconfident_terms:
#         if re.search(pat, text, re.I):
#             score += 0.2
#     # many numeric claims: increase suspicion
#     num_count = len(re.findall(r'\d+', text))
#     if num_count >= 3:
#         score += min(0.3, num_count * 0.03)
#     return min(score, 1.0)


# def _numeric_inconsistency_penalty(response: str, contexts: List[str]) -> float:
#     """
#     Rough check: if response contains numbers that are not supported by any context sentence
#     using simple substring or digit matching.
#     """
#     nums = set(re.findall(r'\d[\d,\.]*', response))
#     if not nums:
#         return 0.0
#     supported = 0
#     for n in nums:
#         found = any(n in c for c in contexts)
#         if found:
#             supported += 1
#     if supported == 0 and nums:
#         return 0.6
#     return max(0.0, 1.0 - (supported / len(nums))) * 0.6


# async def _llm_verifier_score(response: str, contexts: List[str], verifier_call):
#     """
#     Use an external verifier LLM function if available.
#     verifier_call(response_text, context_text) -> returns float 0..1 (1 = hallucinated)
#     This function must be async.
#     """
#     if not verifier_call:
#         return 0.0
#     # call with concatenated contexts (truncate if gigantic)
#     joined_ctx = "\n\n".join(contexts[:5])
#     try:
#         score = await verifier_call(response, joined_ctx)
#         # Ensure 0..1
#         score = float(score)
#         if math.isnan(score):
#             return 0.0
#         return max(0.0, min(1.0, score))
#     except Exception as e:
#         logger.exception("Verifier call failed: %s", e)
#         return 0.0


# def _embedding_support_score(response: str, contexts: List[str]) -> float:
#     """
#     Compute a support score 0..1 where lower means unsupported.
#     Uses sentence-transformers if available.
#     Approach:
#       - Extract assertions from response
#       - For each assertion compute max cosine similarity with context sentences
#       - If similarity < threshold (0.55) => unsupported
#       - Score = fraction_unsupported (0..1)
#     """
#     if not EMBEDDING_AVAILABLE:
#         return 0.0  # caller can fallback to verifier
#     assertions = _extract_assertions(response)
#     # if no assertions, low hallucination by default
#     if not assertions:
#         return 0.0
#     # create embeddings for assertions and contexts
#     try:
#         ctx_sentences = []
#         for c in contexts:
#             ctx_sentences.extend([s.strip() for s in re.split(r'(?<=[\.\?\!])\s+', c) if s.strip()])
#         if not ctx_sentences:
#             return 1.0  # no context at all => high risk

#         a_emb = EMBED_MODEL.encode(assertions, convert_to_tensor=True)
#         c_emb = EMBED_MODEL.encode(ctx_sentences, convert_to_tensor=True)

#         # compute pairwise cosine similarities
#         sims = util.pytorch_cos_sim(a_emb, c_emb).cpu().numpy()  # shape (n_assert, n_ctx)
#         unsupported_count = 0
#         for row in sims:
#             max_sim = float(row.max())
#             # threshold adaptively: 0.55 default
#             if max_sim < 0.55:
#                 unsupported_count += 1
#         fraction_unsupported = unsupported_count / max(1, len(assertions))
#         return min(1.0, fraction_unsupported)
#     except Exception:
#         logger.exception("Embedding support score failed")
#         return 0.0


# async def get_hallucination_score(response: str, contexts: List[str], verifier_call: Optional[callable] = None) -> float:
#     """
#     Compute final hallucination score 0..1 where 1 = definitely hallucinated.
#     Steps:
#      - If embeddings available: compute embedding unsupported fraction
#      - Optionally call LLM verifier to get a second opinion (weighted)
#      - Add heuristic penalties (overconfident, numeric inconsistency)
#      - Combine into final score
#     """
#     heur_pen = _heuristic_overconfidence_penalty(response)
#     numeric_pen = _numeric_inconsistency_penalty(response, contexts)

#     emb_unsupported = 0.0
#     if EMBEDDING_AVAILABLE:
#         try:
#             emb_unsupported = _embedding_support_score(response, contexts)
#         except Exception:
#             emb_unsupported = 0.0

#     verifier_score = 0.0
#     if verifier_call:
#         verifier_score = await _llm_verifier_score(response, contexts, verifier_call)

#     # weighting: verifier (if present) highest, then embedding, then heuristics
#     if verifier_call:
#         combined = 0.5 * verifier_score + 0.3 * emb_unsupported + 0.2 * max(heur_pen, numeric_pen)
#     elif EMBEDDING_AVAILABLE:
#         combined = 0.6 * emb_unsupported + 0.4 * max(heur_pen, numeric_pen)
#     else:
#         # fallback: heuristics only
#         combined = min(1.0, max(heur_pen, numeric_pen) + 0.1)

#     return float(min(1.0, combined))

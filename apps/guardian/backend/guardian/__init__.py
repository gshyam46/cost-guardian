"""Cost Guardian's detection layer.

Sits on top of Langfuse (which owns trace capture/cost/latency) and adds the
differentiated part: deterministic anomaly detection over trace metrics, turned into
evidence-backed incidents. See docs/PRODUCT.md and docs/ARCHITECTURE.md.
"""

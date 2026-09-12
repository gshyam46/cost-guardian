"""Readiness is bounded, read-only and independent of worker/source activity."""
import asyncio


async def ready(db, configuration):
    from .bootstrap import capability, matching_state
    try:
        async with asyncio.timeout(5):
            await capability(db)
            await matching_state(db, configuration, initialized=True)
        return True
    except Exception:
        return False

---
name: add-guardian-detector
description: Scaffold a new Cost Guardian anomaly detector (pure function + test file) following the project's established pattern. Use when adding a new detector type to apps/guardian/backend/guardian/detectors/.
---

# Add a Guardian detector

Cost Guardian detectors are pure functions: metric data in, a `DetectorResult` out — no
network, no DB, no filesystem access. See `apps/guardian/backend/guardian/detectors/base.py` for the
interface and `docs/ARCHITECTURE.md` for why this boundary is non-negotiable.

## Steps

1. Ask (if not already clear): what metric does this detect on, and what's the ground
   truth / benchmark to grade its false-positive rate against? If there isn't one, flag
   that explicitly before building it — see the PII-before-prompt-injection precedent in
   `docs/PROGRESS.md`'s decisions log.
2. Create `apps/guardian/backend/guardian/detectors/<name>.py` implementing the `Detector` protocol
   from `base.py`.
3. Create `apps/guardian/backend/tests/test_<name>_detector.py` **first**, with concrete hand-built
   input fixtures and the exact expected `DetectorResult` — this is the spec.
4. Implement against the test until it passes: `pytest tests/test_<name>_detector.py -v`
5. Register the detector in `apps/guardian/backend/guardian/worker.py`'s detector list.
6. Update the detector table in `docs/PRODUCT.md` and the checklist in
   `docs/PROGRESS.md`.

For anything beyond scaffolding (tuning thresholds, debugging false positives), hand off
to the `detector-engineer` subagent rather than doing it ad hoc.

"""Guardian detectors.

Convention (see base.py and docs/ARCHITECTURE.md): each detector module is a pure
function -- no network, no database, no filesystem access -- exposing:

    NAME: str
    evaluate(baseline: list[TraceMetric], candidates: list[TraceMetric]) -> list[DetectorResult]

`baseline` is the historical window a statistical detector compares against;
`candidates` are the traces actually being checked this cycle. Detectors that don't
need a baseline (e.g. pii) simply ignore it.
"""

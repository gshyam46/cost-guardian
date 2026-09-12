"""Bounded aggregate output for incident summaries, without raw-row truncation."""
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone

from pymongo.errors import PyMongoError

MAX_TIME_MS = 2000
WAIT_SECONDS = 5
SEVERITIES = ("low", "medium", "high")
DETECTORS = ("cost_anomaly", "reliability_anomaly", "pii")
SCHEMA_VERSION = 1
MIN_DATE = datetime(1, 1, 1, tzinfo=timezone.utc)
MAX_DATE = datetime(9999, 12, 31, 23, 59, 59, 999000, tzinfo=timezone.utc)
AWARE_ISO = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"


class SummaryUnavailable(RuntimeError):
    """Safe public failure, without database/source exception text."""


def summary_window(days, now):
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError("invalid_summary_days")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("summary_time_requires_timezone")
    end = now.astimezone(timezone.utc)
    end = end.replace(microsecond=(end.microsecond // 1000) * 1000)
    midnight = end.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight - timedelta(days=days - 1)
    recent_start = midnight - timedelta(days=6)
    return start, end, recent_start


def _category(field, allowed):
    return {"$cond": [{"$in": [{"$ifNull": [field, None]}, list(allowed)]}, field, "unknown"]}


def _legacy_date():
    # $convert alone accepts naive dates and numeric epochs. Neither is an
    # established historical incident timestamp contract.
    kind = {"$type": "$created_at"}
    text = {"$cond": [{"$eq": [kind, "string"]}, "$created_at", ""]}
    return {"$switch": {"branches": [
        {"case": {"$eq": [kind, "date"]}, "then": "$created_at"},
        {"case": {"$regexMatch": {"input": text, "regex": AWARE_ISO}},
         "then": {"$convert": {"input": "$created_at", "to": "date", "onError": None, "onNull": None}}},
    ], "default": None}}


def summary_pipeline(days, now):
    start, end, recent_start = summary_window(days, now)
    first = min(start, recent_start)
    legacy = {"summary_schema": {"$ne": SCHEMA_VERSION}}
    # Expression comparisons order BSON types instead of matching array
    # elements. These indexable complements reject non-scalar/out-of-range
    # dates without fetching every valid historical record for a $type check.
    invalid_native = {"summary_schema": SCHEMA_VERSION, "$or": [
        {"$expr": {"$lt": ["$created_at_utc", MIN_DATE]}},
        {"$expr": {"$gt": ["$created_at_utc", MAX_DATE]}},
        {"created_at_utc": {"$exists": False}},
    ]}
    scalar_date = {"$expr": {"$and": [{"$gte": ["$created_at_utc", MIN_DATE]}, {"$lte": ["$created_at_utc", MAX_DATE]}]}}
    date_range = {"$gte": first, "$lt": end}
    return [
        {"$match": {"$or": [{"status": "open"}, {"created_at_utc": date_range}, legacy, invalid_native]}},
        # Drop evidence/content before the facets; only counts and date fields
        # can consume aggregation memory or reach its grouped output.
        {"$project": {"status": 1, "severity": 1, "detector": 1, "created_at": 1, "created_at_utc": 1, "summary_schema": 1}},
        {"$facet": {
            "open": [
                {"$match": {"status": "open"}},
                {"$group": {"_id": {"severity": _category("$severity", SEVERITIES),
                                     "detector": _category("$detector", DETECTORS)}, "count": {"$sum": 1}}},
            ],
            "native": [
                {"$match": {"summary_schema": SCHEMA_VERSION, "created_at_utc": {"$type": "date", **date_range}}},
                {"$match": scalar_date},
                {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at_utc"}}, "count": {"$sum": 1}}},
            ],
            "legacy": [
                {"$match": legacy},
                {"$project": {"date": _legacy_date()}},
                {"$group": {"_id": {"$cond": [
                    {"$eq": ["$date", None]}, "invalid",
                    {"$cond": [{"$and": [{"$gte": ["$date", first]}, {"$lt": ["$date", end]}]},
                               {"$dateToString": {"format": "%Y-%m-%d", "date": "$date"}}, "outside"]},
                ]}, "count": {"$sum": 1}}},
            ],
            "invalid_native": [{"$match": invalid_native}, {"$count": "count"}],
        }},
    ]


async def ensure_summary_indexes(db):
    state = vars(db).get("_guardian_summary_index_state")
    if state is None:
        state = {"ready": False, "lock": asyncio.Lock()}
        setattr(db, "_guardian_summary_index_state", state)
    if state["ready"]:
        return
    collection = db.guardian_incidents
    async with state["lock"]:
        if state["ready"]:
            return
        await collection.create_index([("status", 1), ("created_at_utc", -1)], name="incident_status_created_utc", maxTimeMS=MAX_TIME_MS)
        await collection.create_index([("created_at_utc", 1)], name="incident_created_utc", maxTimeMS=MAX_TIME_MS)
        await collection.create_index([("summary_schema", 1), ("created_at_utc", 1)], name="incident_summary_schema_date", maxTimeMS=MAX_TIME_MS)
        state["ready"] = True


class IncidentSummaryReader:
    def __init__(self, db):
        self.db = db

    async def snapshot(self, days=14, now=None):
        now = now or datetime.now(timezone.utc)
        start, end, recent_start = summary_window(days, now)

        async def read():
            await ensure_summary_indexes(self.db)
            result = await self.db.guardian_incidents.aggregate(
                summary_pipeline(days, now), maxTimeMS=MAX_TIME_MS, allowDiskUse=False,
            ).to_list(2)
            if len(result) != 1:
                raise SummaryUnavailable("incident_summary_unavailable")
            return result[0]

        try:
            result = await asyncio.wait_for(read(), timeout=WAIT_SECONDS)
        except (PyMongoError, asyncio.TimeoutError):
            raise SummaryUnavailable("incident_summary_unavailable") from None
        if len(result.get("open", [])) > 16 or len(result.get("native", [])) > 90 or len(result.get("legacy", [])) > 92:
            raise SummaryUnavailable("incident_summary_unavailable")
        by_severity, by_detector, daily = Counter(), Counter(), Counter()
        for group in result["open"]:
            count = group["count"]
            by_severity[group["_id"]["severity"]] += count
            by_detector[group["_id"]["detector"]] += count
        invalid = sum(group["count"] for group in result.get("invalid_native", []))
        for group in result["native"] + result["legacy"]:
            if group["_id"] == "invalid":
                invalid += group["count"]
            elif group["_id"] != "outside":
                daily[group["_id"]] += group["count"]
        return {
            "overview": {
                "open_incidents": sum(by_severity.values()), "open_by_severity": dict(by_severity),
                "open_by_detector": dict(by_detector),
                "incidents_last_7_days": sum(count for day, count in daily.items() if day >= recent_start.date().isoformat()),
            },
            "trends": [{"date": (start + timedelta(days=offset)).date().isoformat(),
                        "count": daily[(start + timedelta(days=offset)).date().isoformat()]} for offset in range(days)],
            "coverage": {"status": "partial" if invalid else "complete", "invalid_timestamp_count": invalid},
            "as_of": end.isoformat(), "timezone": "UTC", "window_start": start.isoformat(), "window_end": end.isoformat(),
        }

"""Independent client/server acceptance parity for the supported wire subset."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from capture.errors import CaptureError
from capture.schema import decode_batch

ROOT = Path(__file__).resolve().parents[4]
EXAMPLES = ROOT / "examples/native-capture"
TOKEN = "cg_ingest_" + "a" * 32 + "_" + "b" * 43


def cases():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = lambda value: value.isoformat().replace("+00:00", "Z")
    base = {"observation_id": "attempt-1", "trace_id": "run-1", "agent_name": "answer-generator",
            "model": "provider/model", "started_at": stamp(now - timedelta(seconds=2)),
            "ended_at": stamp(now - timedelta(seconds=1)), "status": "success"}
    rows = []

    def add(name, updates=None, *, valid=True, omit=None):
        event = deepcopy(base)
        event.update(updates or {})
        for key in omit or []:
            event.pop(key)
        rows.append({"name": name, "event": event, "valid": valid})

    add("unknown_optional_measurements")
    add("known_zero", {"cost_usd": "0.000", "input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    add("precise_cost", {"cost_usd": "0.123456789012", "input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
    add("derive_tokens", {"input_tokens": 100, "output_tokens": 20})
    add("nulls", {"parent_observation_id": None, "cost_usd": None, "total_tokens": None})
    add("parent", {"parent_observation_id": "parent:1"})
    add("unknown_status", {"status": "unknown"})
    add("error_status", {"status": "error"})
    offset = timezone(timedelta(hours=5, minutes=30))
    add("offset", {"started_at": (now - timedelta(seconds=2)).astimezone(offset).isoformat(),
                   "ended_at": (now - timedelta(seconds=1)).astimezone(offset).isoformat()})
    add("old_but_accepted", {"started_at": stamp(now - timedelta(hours=23)), "ended_at": stamp(now - timedelta(hours=22))})
    add("microseconds", {"started_at": stamp(now.replace(microsecond=123100)), "ended_at": stamp(now.replace(microsecond=123900))})
    for field in ("observation_id", "trace_id", "agent_name", "model", "started_at", "ended_at", "status"):
        add("missing_" + field, valid=False, omit=[field])
    for field in ("output", "prompt", "error", "customer_id", "project_id", "source", "observation_kind"):
        add("forbidden_" + field, {field: "private-content-canary"}, valid=False)
    add("unicode_id", {"observation_id": "call-\u00e9"}, valid=False)
    add("space_label", {"agent_name": "answer generator"}, valid=False)
    add("long_model", {"model": "a" * 121}, valid=False)
    add("bad_parent", {"parent_observation_id": "customer@example.com"}, valid=False)
    add("empty_status", {"status": ""}, valid=False)
    add("unknown_status_value", {"status": "cancelled"}, valid=False)
    for name, value in (("number", 0.1), ("negative", "-1"), ("exponent", "1e-3"),
                        ("too_precise", "0.1234567890123"), ("too_large", "1000000000"), ("nan", "NaN")):
        add("cost_" + name, {"cost_usd": value}, valid=False)
    for name, value in (("bool", True), ("fraction", 0.5), ("negative", -1),
                        ("string", "1"), ("too_large", 9007199254740992)):
        add("tokens_" + name, {"total_tokens": value}, valid=False)
    add("tokens_mismatch", {"input_tokens": 1, "output_tokens": 2, "total_tokens": 4}, valid=False)
    add("sum_overflow", {"input_tokens": 9007199254740991, "output_tokens": 1}, valid=False)
    add("naive_time", {"started_at": now.isoformat().split("+")[0]}, valid=False)
    add("invalid_calendar", {"started_at": "2026-02-30T12:00:00Z"}, valid=False)
    add("expired", {"started_at": stamp(now - timedelta(hours=25))}, valid=False)
    add("future", {"ended_at": stamp(now + timedelta(minutes=6))}, valid=False)
    add("reversed", {"ended_at": stamp(now - timedelta(seconds=3))}, valid=False)
    add("submillisecond_reversed", {"started_at": stamp(now.replace(microsecond=123900)),
                                     "ended_at": stamp(now.replace(microsecond=123100))}, valid=False)
    return rows


def load_python_exporter():
    # Its sibling import is explicit; neither module imports Guardian or providers.
    sys.path.insert(0, str(EXAMPLES))
    try:
        spec = importlib.util.spec_from_file_location("guardian_exporter_contract_probe", EXAMPLES / "guardian_exporter.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(EXAMPLES))


def test_python_admission_matches_server_for_supported_wire_contract():
    rows = cases()
    module = load_python_exporter()
    settings = SimpleNamespace(project_id="fixture-project", environment="test")
    # Block the standard urllib connection boundary even if a background worker
    # wakes during the admission loop; this check needs no sockets or credentials.
    with patch("socket.create_connection", side_effect=OSError("offline fixture")):
        exporter = module.BackgroundExporter(origin="https://guardian.invalid", token=TOKEN)
        try:
            for row in rows:
                assert exporter.emit(row["event"])["accepted"] is row["valid"], row["name"]
                envelope = {"schema_version": 1, "batch_id": str(uuid4()), "test_mode": False, "events": [row["event"]]}
                if row["valid"]:
                    assert len(decode_batch(envelope, settings).metrics) == 1
                else:
                    with pytest.raises(CaptureError):
                        decode_batch(envelope, settings)
        finally:
            exporter.close(timeout=0.1)


def test_node_admission_matches_same_server_contract_without_network():
    if not shutil.which("node"):
        pytest.skip("Node runtime is unavailable; explicit in validation evidence")
    rows = cases()
    program = "\n".join([
        f"import {{BackgroundExporter}} from {json.dumps((EXAMPLES / 'guardian_exporter.mjs').as_uri())};",
        "globalThis.fetch = async () => { throw new Error('offline fixture'); };",
        "let input=''; for await (const chunk of process.stdin) input += chunk;",
        "const {rows,token}=JSON.parse(input);",
        "const exporter=new BackgroundExporter({origin:'https://guardian.invalid',token});",
        "const results=rows.map(({name,event})=>({name,accepted:exporter.emit(event).accepted}));",
        "await exporter.close(0); console.log(JSON.stringify(results));",
    ])
    result = subprocess.run(["node", "--input-type=module", "-e", program],
                            input=json.dumps({"rows": rows, "token": TOKEN}),
                            text=True, capture_output=True, timeout=15,
                            env={key: value for key, value in os.environ.items()
                                 if key.upper() in {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATH", "PATHEXT",
                                                    "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                                                    "LANG", "LC_ALL", "LC_CTYPE"}})
    assert result.returncode == 0, "Node contract probe failed"
    assert result.stderr == ""
    assert TOKEN not in result.stdout and "private-content-canary" not in result.stdout
    assert json.loads(result.stdout) == [{"name": row["name"], "accepted": row["valid"]} for row in rows]

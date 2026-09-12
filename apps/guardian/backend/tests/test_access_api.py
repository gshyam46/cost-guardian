"""Access proves existing credentials without depending on monitored data.

Real routing/header parsing/serialization; database and telemetry objects fail if
access touches them. This does not introduce accounts, roles or tenant routing.
"""
import httpx
import pytest


KEY = "access-test-key-private-fixture"
EXPECTED = {
    "authenticated": True,
    "auth_mode": "api_key",
    "deployment_mode": "single_project",
    "permissions": ["read", "resolve_incidents"],
}


class MustNotRead:
    def __init__(self):
        self.touched = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError("Access must not read database, indexes, source or live cache")


@pytest.fixture
def environment(monkeypatch):
    import api.routes as routes
    import auth
    from server import app

    database, source, live = MustNotRead(), MustNotRead(), MustNotRead()
    monkeypatch.setattr(routes, "db", database)
    monkeypatch.setattr(routes, "_trace_source", source)
    monkeypatch.setattr(routes, "_live", live)
    monkeypatch.setattr(auth, "GUARDIAN_API_KEY", KEY)
    return app, auth, (database, source, live)


async def get(app, path="/access", headers=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        return await client.get("/api/guardian" + path, headers=headers or {})


def assert_no_data_reads(resources):
    assert all(resource.touched == [] for resource in resources)


def assert_private_response(response):
    assert "no-store" in response.headers.get("cache-control", "").lower()
    vary = {part.strip().lower() for part in response.headers.get("vary", "").split(",")}
    assert {"authorization", "x-guardian-key"} <= vary


@pytest.mark.anyio
@pytest.mark.parametrize("headers", [
    {"X-Guardian-Key": KEY},
    {"x-guardian-key": KEY},
    {"Authorization": f"Bearer {KEY}"},
    {"X-Guardian-Key": KEY, "Authorization": "Bearer wrong-key"},
    {"X-Guardian-Key": "", "Authorization": f"Bearer {KEY}"},
])
async def test_access_accepts_existing_header_and_bearer_contract_without_reading_data(environment, headers):
    app, _, resources = environment
    response = await get(app, headers=headers)
    assert response.status_code == 200
    assert response.json() == EXPECTED
    assert_private_response(response)
    assert_no_data_reads(resources)
    assert KEY not in response.text
    assert "set-cookie" not in response.headers


@pytest.mark.anyio
@pytest.mark.parametrize("headers", [
    {},
    {"X-Guardian-Key": "wrong-key"},
    {"Authorization": "Bearer wrong-key"},
    {"X-Guardian-Key": "wrong-key", "Authorization": f"Bearer {KEY}"},
    {"X-Guardian-Key": f" {KEY}"},
    {"Authorization": f"bearer {KEY}"},
    {"Authorization": f"Bearer {KEY} "},
])
async def test_rejected_credentials_are_private_401_and_preserve_header_precedence(environment, headers):
    app, _, resources = environment
    response = await get(app, headers=headers)
    assert response.status_code == 401
    assert_private_response(response)
    assert_no_data_reads(resources)
    assert KEY not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize("headers", [
    [(b"X-Guardian-Key", b"\xff")],
    [(b"X-Guardian-Key", b"\xc3\xa9")],
    [(b"Authorization", b"Bearer \xff")],
    [(b"X-Guardian-Key", b"\xff"), (b"Authorization", f"Bearer {KEY}".encode("ascii"))],
])
async def test_latin1_or_non_ascii_credentials_cannot_crash_authentication(environment, headers):
    app, _, resources = environment
    response = await get(app, headers=headers)
    assert response.status_code == 401
    assert_private_response(response)
    assert_no_data_reads(resources)


@pytest.mark.anyio
async def test_unconfigured_server_access_returns_safe_private_503(environment, monkeypatch):
    app, auth, resources = environment
    monkeypatch.setattr(auth, "GUARDIAN_API_KEY", "")
    response = await get(app, headers={"X-Guardian-Key": KEY})
    assert response.status_code == 503
    assert_private_response(response)
    assert_no_data_reads(resources)
    assert KEY not in response.text
    assert "mongodb" not in response.text.lower()
    assert "langfuse" not in response.text.lower()


@pytest.mark.anyio
async def test_valid_access_is_independent_of_failed_incident_summary(environment):
    app, _, resources = environment
    summary = await get(app, "/overview", headers={"X-Guardian-Key": KEY})
    assert summary.status_code == 503
    assert resources[0].touched
    for resource in resources:
        resource.touched.clear()

    access = await get(app, headers={"X-Guardian-Key": KEY})
    assert access.status_code == 200
    assert access.json() == EXPECTED
    assert_no_data_reads(resources)


@pytest.mark.anyio
async def test_caller_project_or_permission_claims_do_not_change_fixed_deployment_access(environment):
    app, _, resources = environment
    response = await get(
        app, "/access?project_id=other-project&organization_id=other-org&role=owner",
        headers={"X-Guardian-Key": KEY, "X-Project-ID": "other-project", "X-Role": "viewer"},
    )
    assert response.status_code == 200
    assert response.json() == EXPECTED
    assert "other-project" not in response.text
    assert "other-org" not in response.text
    assert_no_data_reads(resources)


@pytest.mark.anyio
async def test_access_never_logs_a_presented_credential(environment, caplog):
    app, _, resources = environment
    rejected_key = "rejected-private-key-fixture"
    rejected = await get(app, headers={"X-Guardian-Key": rejected_key})
    accepted = await get(app, headers={"X-Guardian-Key": KEY})
    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert rejected_key not in caplog.text
    assert KEY not in caplog.text
    assert_no_data_reads(resources)

"""Real route authentication plus fixed, bounded helper source downloads."""
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import httpx
from mongomock_motor import AsyncMongoMockClient
import pytest

import api.integrations as integrations
from identity.errors import IdentityError
from identity.settings import load_settings
from identity.store import IdentityStore
from server import app


pytestmark = pytest.mark.anyio
ORIGIN = "https://guardian.example.invalid"
ISSUER = "https://identity.example.invalid"


@pytest.fixture
async def environment(monkeypatch):
    for name, value in {
        "GUARDIAN_CAPTURE_MODE": "direct", "GUARDIAN_AUTH_MODE": "oidc", "GUARDIAN_OIDC_ISSUER": ISSUER,
        "GUARDIAN_OIDC_CLIENT_ID": "guardian-test-client", "GUARDIAN_OIDC_CLIENT_SECRET": "synthetic-client-secret",
        "GUARDIAN_PUBLIC_URL": ORIGIN, "GUARDIAN_UI_ORIGIN": ORIGIN,
        "GUARDIAN_ORGANIZATION_ID": "organization-one", "GUARDIAN_PROJECT_ID": "project-one",
        "GUARDIAN_ENVIRONMENT": "test", "GUARDIAN_PROJECT_NAME": "Project One", "GUARDIAN_CONNECTION_ID": "primary",
        "GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH": "false", "GUARDIAN_OIDC_MEMBERS_JSON": json.dumps([
            {"subject": role + "-subject", "role": role, "name": role.title()} for role in ("owner", "operator", "viewer")]),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("GUARDIAN_INTEGRATIONS_DIR", raising=False)
    database = AsyncMongoMockClient(tz_aware=True)["integration_download_tests"]
    monkeypatch.setattr(integrations, "db", database)
    settings = load_settings()
    identity = IdentityStore(database, settings)
    await identity.ensure_binding()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url=ORIGIN,
                                follow_redirects=False) as client:
        yield SimpleNamespace(client=client, db=database, settings=settings, identity=identity)


async def sign_in(env, role="owner"):
    token = await env.identity.create_session({"issuer": ISSUER, "subject": role + "-subject"})
    env.client.cookies.clear()
    env.client.cookies.set(env.settings.session_cookie, token)
    return token


def remove_junction_api(monkeypatch):
    # Python 3.13 also inherits the method from its internal PathBase class.
    for owner in Path.__mro__:
        if "is_junction" in owner.__dict__:
            monkeypatch.delattr(owner, "is_junction")


@pytest.mark.parametrize("artifact", ["python.zip", "python.whl"])
@pytest.mark.parametrize("headers", [{}, {"X-Guardian-Ingest-Key": "cg_ingest_" + "a" * 32 + "_" + "S" * 43}])
async def test_authentication_precedes_file_lookup(environment, monkeypatch, headers, artifact):
    monkeypatch.setattr(integrations, "_source_directory", lambda: pytest.fail("Unauthenticated file lookup"))
    monkeypatch.setattr(integrations, "_wheel_directory", lambda: pytest.fail("Unauthenticated wheel lookup"))
    response = await environment.client.get("/api/guardian/integrations/" + artifact, headers=headers)
    assert response.status_code == 401
    assert "no-store" in response.headers["cache-control"]
    assert "application/zip" not in response.headers["content-type"]


@pytest.mark.parametrize("role", ["owner", "operator", "viewer"])
@pytest.mark.parametrize("language", ["python", "node"])
async def test_named_readers_download_exact_current_modules_without_configuration(environment, role, language):
    token = await sign_in(environment, role)
    response = await environment.client.get(f"/api/guardian/integrations/{language}.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == f'attachment; filename="sillage-{language}.zip"'
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "cookie" in response.headers["vary"].lower()
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == [*integrations.MODULES[language], "README.md"]
        for name in integrations.MODULES[language]:
            assert archive.read(name) == (integrations._source_directory() / name).read_bytes()
        readme = archive.read("README.md").decode("utf-8")
        assert "not published pip or npm packages" in readme
        assert "not completed processing" in readme
        for item in archive.infolist():
            assert not item.is_dir()
            assert "/" not in item.filename and "\\" not in item.filename
            assert token.encode() not in archive.read(item)
            assert b"synthetic-client-secret" not in archive.read(item)
    assert await environment.db.guardian_ingestion_keys.count_documents({}) == 0
    assert await environment.db.guardian_capture_inbox.count_documents({}) == 0


@pytest.mark.parametrize("language", ["ruby", "Python", "node.exe", "__proto__"])
async def test_unsupported_language_never_reads_files(environment, monkeypatch, language):
    await sign_in(environment)
    monkeypatch.setattr(integrations, "_source_directory", lambda: pytest.fail("Unsupported file lookup"))
    response = await environment.client.get(f"/api/guardian/integrations/{language}.zip")
    assert response.status_code == 404
    assert response.json()["detail"] == "This integration is not available."


@pytest.mark.parametrize("path", ["/api/guardian/integrations/%2e%2e%2fsecret.zip", "/api/guardian/integrations/python.zip/../../.env"])
async def test_route_traversal_never_returns_an_archive_or_file(environment, path):
    await sign_in(environment)
    response = await environment.client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


async def test_missing_helper_directory_fails_closed_without_exposing_operator_path(environment, monkeypatch, tmp_path):
    await sign_in(environment)
    monkeypatch.setenv("GUARDIAN_INTEGRATIONS_DIR", str(tmp_path / "private-operator-path-missing"))
    response = await environment.client.get("/api/guardian/integrations/python.zip")
    assert response.status_code == 503
    assert "private-operator-path" not in response.text
    assert response.headers["retry-after"] == "5"
    assert "application/zip" not in response.headers["content-type"]


@pytest.mark.parametrize("failure", ["missing", "oversized", "directory", "empty"])
async def test_incomplete_or_invalid_source_never_returns_a_partial_archive(environment, monkeypatch, tmp_path, failure):
    await sign_in(environment)
    for name in integrations.MODULES["python"]:
        (tmp_path / name).write_bytes(b"# synthetic source\n")
    target = tmp_path / "guardian_openai.py"
    if failure == "missing":
        target.unlink()
    elif failure == "directory":
        target.unlink()
        target.mkdir()
    else:
        target.write_bytes(b"x" * (integrations.MAX_MODULE_BYTES + 1) if failure == "oversized" else b"")
    monkeypatch.setenv("GUARDIAN_INTEGRATIONS_DIR", str(tmp_path))
    response = await environment.client.get("/api/guardian/integrations/python.zip")
    assert response.status_code == 503
    assert "application/zip" not in response.headers["content-type"]


async def test_fixed_allowlist_ignores_other_files_in_the_source_directory(environment, monkeypatch, tmp_path):
    await sign_in(environment)
    for name in integrations.MODULES["python"]:
        (tmp_path / name).write_bytes(b"# synthetic module\n")
    (tmp_path / ".env").write_text("PRIVATE_CANARY=do-not-export", encoding="utf-8")
    (tmp_path / "README.md").write_text("private-readme-canary", encoding="utf-8")
    (tmp_path / "python_app.py").write_text("private-application-canary", encoding="utf-8")
    monkeypatch.setenv("GUARDIAN_INTEGRATIONS_DIR", str(tmp_path))
    response = await environment.client.get("/api/guardian/integrations/python.zip")
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == [*integrations.MODULES["python"], "README.md"]
        assert archive.read("README.md") == integrations.README.encode("utf-8")
        assert all(b"canary" not in archive.read(name) for name in archive.namelist())


async def test_symlinked_module_is_refused(environment, monkeypatch, tmp_path):
    await sign_in(environment)
    for name in integrations.MODULES["python"]:
        (tmp_path / name).write_bytes(b"# synthetic module\n")
    secret = tmp_path / "private-unlisted-file"
    secret.write_bytes(b"private-symlink-canary")
    target = tmp_path / "guardian_openai.py"
    target.unlink()
    try:
        target.symlink_to(secret)
    except OSError:
        pytest.skip("Creating a symlink requires local Windows permission")
    monkeypatch.setenv("GUARDIAN_INTEGRATIONS_DIR", str(tmp_path))
    response = await environment.client.get("/api/guardian/integrations/python.zip")
    assert response.status_code == 503
    assert "private-symlink-canary" not in response.text


@pytest.mark.parametrize("artifact", ["python.zip", "python.whl"])
@pytest.mark.parametrize("error", [IdentityError(503, "identity_store_unavailable"), RuntimeError("private-store-canary")])
async def test_identity_outage_does_not_bypass_authentication_or_expose_details(environment, monkeypatch, error, artifact):
    async def unavailable(*args, **kwargs):
        raise error
    monkeypatch.setattr(integrations, "require_access", unavailable)
    monkeypatch.setattr(integrations, "_source_directory", lambda: pytest.fail("File lookup after identity outage"))
    monkeypatch.setattr(integrations, "_wheel_directory", lambda: pytest.fail("Wheel lookup after identity outage"))
    response = await environment.client.get("/api/guardian/integrations/" + artifact)
    assert response.status_code == 503
    assert "private-store-canary" not in response.text


async def test_relative_operator_path_is_rejected(environment, monkeypatch):
    await sign_in(environment)
    monkeypatch.setenv("GUARDIAN_INTEGRATIONS_DIR", "examples/native-capture")
    response = await environment.client.get("/api/guardian/integrations/python.zip")
    assert response.status_code == 503


@pytest.fixture
def wheel_directory(monkeypatch, tmp_path):
    """A tiny wheel exercises delivery without depending on a local package build."""
    artifact = tmp_path / integrations.PYTHON_WHEEL
    with ZipFile(artifact, "w") as archive:
        archive.writestr("sillage_observe/__init__.py", '__version__ = "0.2.0"\n')
        archive.writestr("sillage_observe-0.2.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: sillage-observe\nVersion: 0.2.0\n")
        archive.writestr("sillage_observe-0.2.0.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr("sillage_observe-0.2.0.dist-info/RECORD", "")
    monkeypatch.setenv("GUARDIAN_INTEGRATIONS_DIR", str(tmp_path))
    return artifact


@pytest.mark.parametrize("role", ["owner", "operator", "viewer"])
async def test_named_readers_download_exact_wheel_without_workspace_secrets(environment, wheel_directory, role):
    token = await sign_in(environment, role)
    (wheel_directory.parent / ".env").write_text("PRIVATE_CANARY=never-serve-me", encoding="utf-8")
    (wheel_directory.parent / "sillage_observe-9.9.9-py3-none-any.whl").write_bytes(b"wrong-version-canary")
    response = await environment.client.get("/api/guardian/integrations/python.whl")
    assert response.status_code == 200
    assert response.content == wheel_directory.read_bytes()
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == f'attachment; filename="{integrations.PYTHON_WHEEL}"'
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "cookie" in response.headers["vary"].lower()
    assert token.encode() not in response.content
    assert b"synthetic-client-secret" not in response.content
    assert b"canary" not in response.content
    with ZipFile(BytesIO(response.content)) as archive:
        assert "sillage_observe-0.2.0.dist-info/WHEEL" in archive.namelist()
    assert await environment.db.guardian_ingestion_keys.count_documents({}) == 0
    assert await environment.db.guardian_capture_inbox.count_documents({}) == 0


@pytest.mark.parametrize("failure", ["missing", "oversized", "directory", "empty", "missing-root", "relative-root", "parent-traversal"])
async def test_missing_or_unbounded_wheel_has_fixed_safe_error(environment, monkeypatch, wheel_directory, failure):
    await sign_in(environment)
    if failure == "missing":
        wheel_directory.unlink()
    elif failure == "directory":
        wheel_directory.unlink()
        wheel_directory.mkdir()
    elif failure in {"oversized", "empty"}:
        wheel_directory.write_bytes(b"x" * (integrations.MAX_WHEEL_BYTES + 1) if failure == "oversized" else b"")
    elif failure == "missing-root":
        monkeypatch.setenv("GUARDIAN_INTEGRATIONS_DIR", str(wheel_directory.parent / "private-directory-canary"))
    elif failure == "relative-root":
        monkeypatch.setenv("GUARDIAN_INTEGRATIONS_DIR", "private-directory-canary")
    else:
        monkeypatch.setenv("GUARDIAN_INTEGRATIONS_DIR", str(wheel_directory.parent / ".." / wheel_directory.parent.name))
    response = await environment.client.get("/api/guardian/integrations/python.whl")
    assert response.status_code == 503
    assert response.json() == {"detail": "Python package download is unavailable. Retry or contact your Sillage operator."}
    assert response.headers["retry-after"] == "5"
    assert response.headers["cache-control"] == "no-store"
    assert "content-disposition" not in response.headers
    assert "private-directory-canary" not in response.text


@pytest.mark.parametrize("target", ["file", "root", "ancestor"])
@pytest.mark.parametrize("link_kind", ["is_symlink", "is_junction"])
async def test_wheel_refuses_links_at_every_path_level(environment, monkeypatch, wheel_directory, target, link_kind):
    await sign_in(environment)
    linked = wheel_directory if target == "file" else wheel_directory.parent if target == "root" else wheel_directory.parent.parent
    original = getattr(Path, link_kind, lambda _path: False)
    # The predicate is portable on Windows where creating symlinks needs extra privileges.
    monkeypatch.setattr(Path, link_kind, lambda path: path == linked or original(path), raising=False)
    response = await environment.client.get("/api/guardian/integrations/python.whl")
    assert response.status_code == 503
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize("artifact", ["python.zip", "python.whl"])
async def test_downloads_work_without_python312_junction_api(environment, monkeypatch, wheel_directory, artifact):
    await sign_in(environment)
    for name in integrations.MODULES["python"]:
        (wheel_directory.parent / name).write_bytes(b"# synthetic source\n")
    remove_junction_api(monkeypatch)
    assert not hasattr(Path, "is_junction")
    response = await environment.client.get("/api/guardian/integrations/" + artifact)
    assert response.status_code == 200
    if artifact == "python.whl":
        assert response.content == wheel_directory.read_bytes()
    else:
        with ZipFile(BytesIO(response.content)) as archive:
            assert archive.namelist() == [*integrations.MODULES["python"], "README.md"]


@pytest.mark.parametrize("target", ["file", "root", "ancestor"])
async def test_windows_reparse_points_remain_rejected_without_junction_api(environment, monkeypatch, wheel_directory, target):
    await sign_in(environment)
    linked = wheel_directory if target == "file" else wheel_directory.parent if target == "root" else wheel_directory.parent.parent
    remove_junction_api(monkeypatch)
    original = Path.lstat
    def reparse_metadata(path):
        found = original(path)
        if path != linked:
            return found
        return SimpleNamespace(st_mode=found.st_mode, st_size=found.st_size,
                               st_file_attributes=0x400, st_reparse_tag=0xA0000003)
    monkeypatch.setattr(Path, "lstat", reparse_metadata)
    response = await environment.client.get("/api/guardian/integrations/python.whl")
    assert response.status_code == 503
    assert "content-disposition" not in response.headers


async def test_wheel_reader_detects_replaced_file_before_returning_payload(environment, monkeypatch, wheel_directory):
    await sign_in(environment)
    original = integrations.os.fstat
    def changed_file(descriptor):
        found = original(descriptor)
        return SimpleNamespace(st_mode=found.st_mode, st_dev=found.st_dev, st_ino=found.st_ino + 1, st_size=found.st_size)
    monkeypatch.setattr(integrations.os, "fstat", changed_file)
    response = await environment.client.get("/api/guardian/integrations/python.whl")
    assert response.status_code == 503
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize("artifact", ["node.whl", "sillage_observe-0.2.0-py3-none-any.whl", "python.whl/extra", "%2e%2e%2fsecret.whl"])
async def test_unlisted_wheel_routes_cannot_read_files(environment, monkeypatch, artifact):
    await sign_in(environment)
    monkeypatch.setattr(integrations, "_wheel_directory", lambda: pytest.fail("Unlisted artifact lookup"))
    response = await environment.client.get("/api/guardian/integrations/" + artifact)
    assert response.status_code == 404
    assert "content-disposition" not in response.headers

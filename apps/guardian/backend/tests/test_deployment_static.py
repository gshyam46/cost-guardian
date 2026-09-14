"""Actual ASGI static/API routing without a filesystem exposure fallback."""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
import httpx
import pytest

from deployment.static import install_static, validate_static_directory

JS = "/static/js/main.1234abcd.js"
CSS = "/static/css/main.9876abcd.css"


@pytest.fixture
def build(tmp_path):
    (tmp_path / "static/js").mkdir(parents=True)
    (tmp_path / "static/css").mkdir()
    (tmp_path / JS[1:]).write_bytes(b"console.log('synthetic-build');")
    (tmp_path / CSS[1:]).write_bytes(b"body{color:black}")
    (tmp_path / "index.html").write_text(f'<!doctype html><html><head><script defer src="{JS}"></script><link rel="stylesheet" href="{CSS}"></head><body>Guardian shell</body></html>', encoding="utf-8")
    manifest = {"files": {"main.js": JS, "main.css": CSS, "index.html": "/index.html", "main.js.map": JS + ".map"},
                "entrypoints": [CSS[1:], JS[1:]]}
    (tmp_path / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / (JS[1:] + ".map")).write_bytes(b"private-source-canary")
    (tmp_path / ".env").write_bytes(b"private-env-canary")
    return tmp_path


def application(build):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/guardian/access")
    def denied():
        raise HTTPException(401, "Sign in")

    @app.get("/api/offline")
    def offline():
        raise HTTPException(503, "Unavailable")

    @app.post("/api/action")
    def mutation():
        return {"action": "received"}

    install_static(app, build)
    return app


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/", "/welcome", "/demo", "/signin", "/setup", "/live", "/incidents", "/incidents/abc-123", "/runs/trace_123:attempt-1",
    "/runs/_trace", "/runs/-trace", "/runs/:trace", "/runs/.trace", "/?guardian_login=complete"])
async def test_known_deep_links_receive_noncacheable_shell(build, path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(build)), base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 200 and "Guardian shell" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/api", "/api/unknown", "/unknown", "/setup/extra", "/welcome/extra", "/demo/extra", "/signin/extra", "/runs", "/.env", "/server.py",
    "/asset-manifest.json", "/src/App.js", JS + ".map", "/static/js/missing.1234abcd.js", "/static/%2e%2e/.env",
    "/static/js/%252e%252e/.env", "/runs/%2e%2e", "/runs/a%2Fb", "/runs/a%5Cb", "/runs/" + "a" * 129])
async def test_unknown_api_assets_source_and_traversal_never_fall_back_to_html(build, path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(build)), base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}
    assert "private" not in response.text and response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_api_auth_errors_and_mutations_are_not_shadowed(build):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(build)), base_url="http://test") as client:
        denied = await client.get("/api/guardian/access")
        offline = await client.get("/api/offline")
        mutation = await client.post("/api/action")
        wrong_method = await client.post("/setup")
    assert denied.status_code == 401 and denied.json() == {"detail": "Sign in"}
    assert offline.status_code == 503 and offline.json() == {"detail": "Unavailable"}
    assert mutation.json() == {"action": "received"} and wrong_method.status_code == 405


@pytest.mark.anyio
async def test_hashed_assets_are_immutable_and_head_is_bodyless(build):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(build)), base_url="http://test") as client:
        response = await client.get(JS)
        head = await client.head(JS)
        css = await client.get(CSS)
    assert response.content == b"console.log('synthetic-build');"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["content-type"].startswith("text/javascript")
    assert css.headers["content-type"].startswith("text/css")
    assert head.content == b"" and head.headers["content-length"] == str(len(response.content))


@pytest.mark.anyio
async def test_named_brand_assets_and_font_license_are_served_without_directory_exposure(build):
    (build / 'favicon.svg').write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    (build / 'apple-touch-icon.png').write_bytes(b'synthetic-icon')
    (build / 'IBMPlexMono-OFL.txt').write_bytes(b'Synthetic font license')
    (build / 'private-notes.txt').write_bytes(b'private-file-must-not-ship')
    app = application(build)
    # Files are immutable in memory for the process lifetime, even public copies.
    (build / 'IBMPlexMono-OFL.txt').write_bytes(b'changed-after-start')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for url, mime in [('/favicon.svg', 'image/svg+xml'), ('/apple-touch-icon.png', 'image/png'), ('/IBMPlexMono-OFL.txt', 'text/plain')]:
            response = await client.get(url)
            assert response.status_code == 200 and response.headers['content-type'].startswith(mime)
            assert response.headers['cache-control'] == 'no-store'
        assert (await client.get('/IBMPlexMono-OFL.txt')).content == b'Synthetic font license'
        assert (await client.head('/favicon.svg')).content == b''
        assert (await client.get('/private-notes.txt')).status_code == 404


def test_copied_brand_file_retains_size_bound(build, monkeypatch):
    from deployment import static
    (build / 'favicon.svg').write_bytes(b'x' * 4096)
    monkeypatch.setattr(static, 'MAX_METADATA_BYTES', 2048)
    with pytest.raises(ValueError, match='invalid_static_build'):
        validate_static_directory(build)


@pytest.mark.anyio
async def test_installed_snapshot_does_not_read_replaced_files(build):
    app = application(build)
    (build / JS[1:]).write_bytes(b"private-replacement-canary")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(JS)
    assert response.content == b"console.log('synthetic-build');"


def mutate_manifest(build, change):
    path = build / "asset-manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.parametrize("change", [
    lambda data: data["files"].update(secret="/.env"),
    lambda data: data["files"].update(secret="/static/../.env"),
    lambda data: data["files"].update(main="https://outside.invalid/app.js"),
    lambda data: data["files"].update(main="/static/js/main.js"),
    lambda data: data.update(entrypoints=["static/js/absent.1234abcd.js"]),
    lambda data: data.update(entrypoints=[]),
    lambda data: data.update(entrypoints=[CSS[1:]]),
    lambda data: data.update(entrypoints=[JS[1:], JS[1:]]),
    lambda data: data["files"].update(other=JS),
])
def test_invalid_manifest_fails_without_paths_or_payload(build, change):
    mutate_manifest(build, change)
    with pytest.raises(ValueError, match="^invalid_static_build$"):
        validate_static_directory(build)


def test_missing_or_oversized_asset_and_remote_shell_script_fail(build, monkeypatch):
    monkeypatch.setattr("deployment.static.MAX_FILE_BYTES", 4)
    with pytest.raises(ValueError, match="^invalid_static_build$"):
        validate_static_directory(build)
    monkeypatch.undo()
    (build / "index.html").write_text('<script src="https://outside.invalid/private.js"></script>', encoding="utf-8")
    with pytest.raises(ValueError, match="^invalid_static_build$"):
        validate_static_directory(build)
    (build / JS[1:]).unlink()
    with pytest.raises(ValueError, match="^invalid_static_build$"):
        validate_static_directory(build)


def test_duplicate_json_keys_are_rejected(build):
    (build / "asset-manifest.json").write_text('{"files":{},"files":{},"entrypoints":[]}', encoding="utf-8")
    with pytest.raises(ValueError, match="^invalid_static_build$"):
        validate_static_directory(build)


def test_symlink_asset_escape_is_rejected(build, tmp_path):
    asset = build / JS[1:]
    asset.unlink()
    outside = tmp_path.parent / (tmp_path.name + "-outside.txt")
    outside.write_bytes(b"private-outside-canary")
    try:
        try:
            asset.symlink_to(outside)
        except OSError:
            pytest.skip("OS does not permit creating test symlinks")
        with pytest.raises(ValueError, match="^invalid_static_build$"):
            validate_static_directory(build)
    finally:
        outside.unlink()


def test_symlink_detection_is_enforced_even_without_os_link_privilege(build, monkeypatch):
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == build / "static" or original(path))
    with pytest.raises(ValueError, match="^invalid_static_build$"):
        validate_static_directory(build)


def test_absent_static_configuration_preserves_existing_api_only_startup(monkeypatch):
    monkeypatch.delenv("GUARDIAN_STATIC_DIR", raising=False)
    app = FastAPI()
    before = len(app.routes)
    assert install_static(app) is None and len(app.routes) == before


def test_snapshot_is_readonly_and_does_not_include_maps_or_arbitrary_files(build):
    snapshot = validate_static_directory(build)
    assert set(snapshot.assets) == {"/index.html", JS, CSS}
    with pytest.raises(TypeError):
        snapshot.assets["/.env"] = object()

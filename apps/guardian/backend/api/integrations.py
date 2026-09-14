"""Authenticated downloads of fixed installable artifacts and source helpers."""
import asyncio
from io import BytesIO
import os
from pathlib import Path
import stat
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response

from auth import require_access
from db import db


router = APIRouter(prefix="/guardian/integrations", tags=["integrations"])
MODULES = {
    "python": ("guardian_capture.py", "guardian_exporter.py", "guardian_openai.py"),
    "node": ("guardian_capture.mjs", "guardian_exporter.mjs", "guardian_openai.mjs"),
}
MAX_MODULE_BYTES = 128 * 1024
PYTHON_WHEEL = "sillage_observe-0.2.0-py3-none-any.whl"
MAX_WHEEL_BYTES = 2 * 1024 * 1024
HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "Vary": "Cookie, Origin, Authorization, X-Guardian-Key",
           "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
README = """Sillage application capture helpers

These are repository source modules, not published pip or npm packages.
Keep the three source files together inside your server application.
Use the matching Python or Node recipe on the Connections page.
Sillage retains the existing guardian_* module names and GUARDIAN_* configuration
variables for compatibility with applications that already use the helpers.

Set GUARDIAN_URL to your Sillage base address and GUARDIAN_INGEST_KEY to the
write-only ingestion key created by your project owner. Keep your provider key
with your existing provider client. Sillage does not need that provider key.
The OpenAI recipe also uses your application's existing OPENAI_MODEL setting.

Create one background exporter per application process and reuse it across calls.
The helpers report completed call metadata; they do not automatically discover
your application or instrument every workflow step. Prompts, outputs, documents
and raw errors stay outside Sillage. Never put customer identifiers in metadata.
Reported token usage is preserved. USD cost remains unknown unless your own
instrumentation provides a known amount; missing usage or cost is never zero.

Test the collector with test_mode=True in Python or testMode: true in Node.
Use test_mode=False / testMode: false for real call metadata. A test creates no
production observations, totals or incidents. A receipt confirms acceptance,
not completed processing. Check the Connections receipt and processing counts,
then open the captured run and Overview to verify the result.

Exporter delivery runs in the background and is not durable across process
crashes. Check exporter diagnostics for rejected or unconfirmed events, and
flush/close during controlled application shutdown. Keep failures outside your
customer response path. See the supplied modules and Connections recipes for
streaming, cancellation and async-client usage.
"""


def _is_link(path):
    if path.is_symlink():
        return True
    junction = getattr(path, "is_junction", None)
    if callable(junction):
        return junction()
    # Path.is_junction was introduced in Python 3.12. Older supported Python
    # versions still expose Windows reparse metadata through lstat; reject
    # reparse points conservatively rather than treating a missing API as safe.
    metadata = path.lstat()
    return bool(getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _integration_directory(default):
    # The image provides this explicit path. A normal repository checkout uses
    # its existing examples; never search the filesystem or enumerate a folder.
    configured = os.environ.get("GUARDIAN_INTEGRATIONS_DIR")
    root = Path(configured) if configured is not None else Path(__file__).resolve().parents[4] / default
    if not root.is_absolute() or any(part == ".." for part in root.parts):
        raise ValueError("invalid_integration_directory")
    if any(_is_link(path) for path in (root, *root.parents)) or not root.is_dir():
        raise ValueError("invalid_integration_directory")
    return root.resolve(strict=True)


def _source_directory():
    return _integration_directory(Path("examples") / "native-capture")


def _wheel_directory():
    return _integration_directory(Path("packages") / "sillage-python" / "dist")


def _file_bytes(root, name, maximum):
    path = root / name
    before = path.lstat()
    if _is_link(path) or not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
        raise ValueError("invalid_integration_module")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        opened = os.fstat(source.fileno())
        if (not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or not 0 < opened.st_size <= maximum):
            raise ValueError("invalid_integration_module")
        data = source.read(maximum + 1)
        if not data or len(data) > maximum:
            raise ValueError("invalid_integration_module")
    return data


def _module_bytes(root, name):
    return _file_bytes(root, name, MAX_MODULE_BYTES)


def python_wheel_bytes():
    return _file_bytes(_wheel_directory(), PYTHON_WHEEL, MAX_WHEEL_BYTES)


def build_bundle(language):
    names = MODULES[language]
    root = _source_directory()
    files = [(name, _module_bytes(root, name)) for name in names]
    files.append(("README.md", README.encode("utf-8")))
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as bundle:
        for name, data in files:
            entry = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            bundle.writestr(entry, data)
    return output.getvalue()


@router.get("/python.whl")
async def download_python_wheel(request: Request):
    try:
        async with asyncio.timeout(5):
            await require_access(request, db)
            payload = await asyncio.to_thread(python_wheel_bytes)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, detail="Python package download is unavailable. Retry or contact your Sillage operator.",
                            headers={**HEADERS, "Retry-After": "5"}) from None
    return Response(payload, media_type="application/octet-stream", headers={**HEADERS,
        "Content-Disposition": f'attachment; filename="{PYTHON_WHEEL}"'})


@router.get("/{language}.zip")
async def download_integration(language: str, request: Request):
    try:
        async with asyncio.timeout(5):
            await require_access(request, db)
            if language not in MODULES:
                raise HTTPException(404, detail="This integration is not available.", headers=HEADERS)
            payload = await asyncio.to_thread(build_bundle, language)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, detail="Integration download is unavailable. Retry or contact your Sillage operator.",
                            headers={**HEADERS, "Retry-After": "5"}) from None
    return Response(payload, media_type="application/zip", headers={**HEADERS,
        "Content-Disposition": f'attachment; filename="sillage-{language}.zip"'})

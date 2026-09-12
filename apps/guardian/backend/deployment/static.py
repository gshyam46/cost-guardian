"""Bounded, immutable public build snapshot; never expose a filesystem mount."""
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType

from starlette.responses import JSONResponse, Response

MAX_FILES = 256
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_BUILD_BYTES = 32 * 1024 * 1024
MAX_METADATA_BYTES = 256 * 1024
_ASSET = re.compile(r"/static/(?:js|css|media)/[A-Za-z0-9_-][A-Za-z0-9_.-]*\.[0-9a-f]{8,64}(?:\.[A-Za-z0-9_-]+)*\.(?:js|css|svg|png|jpg|jpeg|gif|webp|ico|woff|woff2|ttf)\Z")
_MAP = re.compile(r"/static/(?:js|css)/[A-Za-z0-9_-][A-Za-z0-9_.-]*\.[0-9a-f]{8,64}\.(?:js|css)\.map\Z")
_DETAIL = re.compile(r"/(?:incidents|runs)/[A-Za-z0-9_.:-]{1,128}\Z")
_SHELL = frozenset({"/", "/setup", "/live", "/incidents"})
_PUBLIC = {"/favicon.ico": "image/x-icon", "/manifest.json": "application/manifest+json", "/robots.txt": "text/plain"}
_MIME = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
         ".ico": "image/x-icon", ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf"}


@dataclass(frozen=True)
class StaticAsset:
    content: bytes
    media_type: str
    immutable: bool = False


@dataclass(frozen=True)
class StaticBuild:
    directory: Path
    assets: object


def _read(root, relative, limit):
    parts = Path(relative).parts
    if not parts or any(part in {".", ".."} for part in parts) or Path(relative).is_absolute():
        raise ValueError()
    path = root
    for part in parts:
        path /= part
        if path.is_symlink():
            raise ValueError()
    if path.resolve(strict=True).parent != root and root not in path.resolve(strict=True).parents:
        raise ValueError()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ValueError()
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError()
        return data


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


class _Entrypoints(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.paths.append(attrs.get("src"))
        elif tag == "link" and attrs.get("rel") == "stylesheet":
            self.paths.append(attrs.get("href"))


def validate_static_directory(directory):
    """Validate and snapshot a CRA production build; errors never expose paths."""
    try:
        if not directory:
            raise ValueError()
        supplied = Path(directory)
        if supplied.is_symlink() or not supplied.is_dir():
            raise ValueError()
        root = supplied.resolve(strict=True)
        raw = _read(root, "asset-manifest.json", MAX_METADATA_BYTES)
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        if (type(manifest) is not dict or set(manifest) != {"files", "entrypoints"}
                or type(manifest["files"]) is not dict or not 1 <= len(manifest["files"]) <= MAX_FILES
                or manifest["files"].get("index.html") != "/index.html"
                or type(manifest["entrypoints"]) is not list or not 1 <= len(manifest["entrypoints"]) <= MAX_FILES):
            raise ValueError()
        assets = {}
        total = 0
        for name, url in manifest["files"].items():
            if type(name) is not str or type(url) is not str or len(url) > 512 or ".." in url.split("/"):
                raise ValueError()
            if _MAP.fullmatch(url):
                continue  # Native development builds can contain maps; they are never public.
            if url == "/index.html":
                mime, immutable, limit = "text/html", False, MAX_METADATA_BYTES
            elif _ASSET.fullmatch(url):
                mime, immutable, limit = _MIME[Path(url).suffix], True, MAX_FILE_BYTES
            elif url in _PUBLIC:
                mime, immutable, limit = _PUBLIC[url], False, MAX_METADATA_BYTES
            else:
                raise ValueError()
            if url in assets:
                raise ValueError()
            data = _read(root, url[1:], limit)
            total += len(data)
            if total > MAX_BUILD_BYTES or not data:
                raise ValueError()
            assets[url] = StaticAsset(data, mime, immutable)
        entries = manifest["entrypoints"]
        if (any(type(entry) is not str or not entry.startswith("static/") or "/" + entry not in assets for entry in entries)
                or len(set(entries)) != len(entries) or not any(entry.endswith(".js") for entry in entries)):
            raise ValueError()
        parser = _Entrypoints()
        parser.feed(assets["/index.html"].content.decode("utf-8"))
        if any(path not in assets for path in parser.paths) or not all("/" + entry in parser.paths for entry in entries):
            raise ValueError()
        return StaticBuild(root, MappingProxyType(assets))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise ValueError("invalid_static_build") from None


def install_static(app, directory=None):
    selected = os.getenv("GUARDIAN_STATIC_DIR") if directory is None else directory
    if not selected:
        return None
    build = validate_static_directory(selected)

    async def public(request):
        path = request.scope["path"]
        shell = path in _SHELL or (_DETAIL.fullmatch(path) is not None and path.rsplit("/", 1)[-1] not in {".", ".."})
        asset = build.assets.get("/index.html" if shell else path)
        if asset is None:
            return JSONResponse({"detail": "Not Found"}, status_code=404, headers={"Cache-Control": "no-store"})
        headers = {"Cache-Control": "public, max-age=31536000, immutable" if asset.immutable else "no-store",
                   "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                   "Content-Length": str(len(asset.content))}
        return Response(asset.content if request.method == "GET" else b"", media_type=asset.media_type, headers=headers)

    app.add_route("/{guardian_path:path}", public, methods=["GET", "HEAD"], include_in_schema=False)
    return build

"""Content-versioned DOGMA assets; no changes to other extensions or node execution."""
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit


def versioned_urls(urls, extension_dirs, web_directory):
    root = Path(web_directory).resolve()
    prefixes = ["/extensions/" + quote(name, safe="") + "/"
                for name, directory in extension_dirs.items()
                if Path(directory).resolve() == root]
    result = []
    for url in urls:
        parts = urlsplit(url)
        # This package has one entry module. Do not rewrite third-party URLs.
        if any(parts.path == prefix + "dogma_categories.js" for prefix in prefixes):
            digest = hashlib.sha256((root / "dogma_categories.js").read_bytes()).hexdigest()[:20]
            query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                     if k != "dogma_build"]
            query.append(("dogma_build", digest))
            url = urlunsplit(parts._replace(query=urlencode(query)))
        result.append(url)
    return result


def register_frontend(web_directory):
    from aiohttp import web
    import nodes
    from server import PromptServer

    app = PromptServer.instance.app
    if any(getattr(m, "_dogma_asset_versioning", False) for m in app.middlewares):
        return

    @web.middleware
    async def version_assets(request, handler):
        response = await handler(request)
        if request.path not in ("/extensions", "/api/extensions") or response.status != 200:
            return response
        if not isinstance(response, web.Response) or response.content_type != "application/json":
            return response
        urls = json.loads(response.text)
        if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
            return response
        updated = versioned_urls(urls, nodes.EXTENSION_WEB_DIRS, web_directory)
        response.text = json.dumps(updated)
        # The entry list must be revalidated on an ordinary page reload.
        response.headers["Cache-Control"] = "no-store"
        for header in ("ETag", "Last-Modified", "Content-Length"):
            response.headers.pop(header, None)
        return response

    version_assets._dogma_asset_versioning = True
    # Innermost: rewrite JSON before ComfyUI's optional compression middleware.
    app.middlewares.append(version_assets)

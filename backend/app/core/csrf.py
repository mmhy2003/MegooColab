from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CsrfHeaderMiddleware(BaseHTTPMiddleware):
    """Unsafe requests must prove they come from our own client, or carry a bearer token.

    Browsers can't add custom headers to cross-site form posts, so requiring one
    blocks CSRF against cookie-authenticated requests. `exempt_paths` never accept
    cookies (e.g. the bearer-only MCP endpoint), so they answer for themselves.
    """

    def __init__(self, app, exempt_paths: frozenset[str] = frozenset()) -> None:
        super().__init__(app)
        self.exempt_paths = exempt_paths

    async def dispatch(self, request: Request, call_next):
        if request.method not in SAFE_METHODS and request.url.path not in self.exempt_paths:
            from_web = request.headers.get("x-megoo-client") == "web"
            bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
            if not (from_web or bearer):
                return JSONResponse({"detail": "csrf_header_missing"}, status_code=403)
        return await call_next(request)

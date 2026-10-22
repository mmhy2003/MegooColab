from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CsrfHeaderMiddleware(BaseHTTPMiddleware):
    """Unsafe requests must prove they come from our own client, or carry a bearer token.

    Browsers can't add custom headers to cross-site form posts, so requiring one
    blocks CSRF against cookie-authenticated requests.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method not in SAFE_METHODS:
            from_web = request.headers.get("x-megoo-client") == "web"
            bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
            if not (from_web or bearer):
                return JSONResponse({"detail": "csrf_header_missing"}, status_code=403)
        return await call_next(request)

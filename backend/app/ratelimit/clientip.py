"""The visitor's address for per-IP limits.

By default the address uvicorn resolved (it reads Caddy's X-Forwarded-For). `CLIENT_IP_HEADER` names a header a
fronting proxy sets with the visitor's address (e.g. `CF-Connecting-IP`); set it only when every request comes through
that proxy, or anyone reaching Caddy directly can forge it. IPv6 counts per /64, so one machine cannot rotate through
its own block.
"""

import ipaddress
from typing import Any

from starlette.requests import HTTPConnection

from app.core.config import get_settings


def _normalise(raw: str) -> str | None:
    try:
        ip = ipaddress.ip_address(raw.strip())
    except ValueError:
        return None
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def client_ip(conn: HTTPConnection | dict[str, Any]) -> str:
    scope = conn.scope if isinstance(conn, HTTPConnection) else conn
    header = get_settings().client_ip_header.strip().lower()
    if header:
        for name, value in scope.get("headers") or []:
            if name.decode("latin-1").lower() == header:
                found = _normalise(value.decode("latin-1"))
                if found is not None:
                    return found
                break
    client = scope.get("client")
    resolved = _normalise(client[0]) if client else None
    return resolved or "unknown"

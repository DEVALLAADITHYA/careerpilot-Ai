"""SSRF protection: only public http(s) hosts are allowed."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeURLError(ValueError):
    pass


def _is_public(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return a.is_global and not (a.is_multicast or a.is_reserved or a.is_loopback
                                or a.is_link_local or a.is_private or a.is_unspecified)


def check_url(url: str, resolver=None) -> str:
    """Validate a URL synchronously; returns the URL or raises UnsafeURLError."""
    if not url or len(url) > 2048:
        raise UnsafeURLError("URL missing or too long")
    p = urlsplit(url.strip())
    if p.scheme not in ("http", "https"):
        raise UnsafeURLError("Only http/https URLs are allowed")
    if p.username or p.password:
        raise UnsafeURLError("Credentials in URLs are not allowed")
    host = p.hostname
    if not host:
        raise UnsafeURLError("URL has no host")
    try:
        port = p.port
    except ValueError as e:
        raise UnsafeURLError("Invalid port") from e
    if port not in (None, 80, 443):
        raise UnsafeURLError("Non-standard ports are not allowed")
    try:
        ips = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            infos = (resolver or socket.getaddrinfo)(host, None)
        except OSError as e:
            raise UnsafeURLError(f"Cannot resolve host: {host}") from e
        ips = sorted({i[4][0] for i in infos})
    if not ips or not all(_is_public(i) for i in ips):
        raise UnsafeURLError("URL resolves to a non-public address")
    return url


async def check_url_async(url: str) -> str:
    return await asyncio.to_thread(check_url, url)

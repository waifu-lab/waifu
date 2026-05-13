from typing import Any, Dict, Optional

import httpx


class ServerOffline(RuntimeError):
    """Raised when the local waifu server is not reachable."""


def _base_url() -> str:
    from waifu.cli.config import _load_raw

    data = _load_raw()
    gateway = data.get("gateway") if isinstance(data, dict) else {}
    host = (gateway or {}).get("host", "127.0.0.1") or "127.0.0.1"

    if host in ("0.0.0.0", "::", "localhost"):
        host = "127.0.0.1"
    port = (gateway or {}).get("port", 8765) or 8765
    return f"http://{host}:{port}"


_online_state: Optional[bool] = None


def mark_online() -> None:
    global _online_state
    _online_state = True


def mark_offline() -> None:
    global _online_state
    _online_state = False


def online_state() -> Optional[bool]:
    """Whatever the last real request told us. None = no request issued yet."""
    return _online_state


def is_online(timeout: float = 0.2) -> bool:
    """Probe /health if we don't already know. Cached after first call."""
    global _online_state
    if _online_state is not None:
        return _online_state
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.get(f"{_base_url()}/health")
            _online_state = r.status_code == 200
    except (httpx.HTTPError, OSError):
        _online_state = False
    return _online_state


def request(method: str, path: str, *, json: Optional[Dict[str, Any]] = None, timeout: float = 5.0) -> httpx.Response:
    """Issue a request. Raises ServerOffline if unreachable; updates cached state.

    Honours the offline cache: once a previous call has marked the server offline
    in this process, subsequent calls short-circuit without re-attempting TCP.
    """
    if _online_state is False:
        raise ServerOffline("cached: server unreachable")
    url = f"{_base_url()}{path}"
    httpx_timeout = httpx.Timeout(timeout, connect=0.3)
    try:
        with httpx.Client(timeout=httpx_timeout) as c:
            resp = c.request(method, url, json=json)
            mark_online()
            return resp
    except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as e:
        mark_offline()
        raise ServerOffline(str(e)) from e
